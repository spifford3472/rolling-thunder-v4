"""Durable Forge-side idempotency and Wavelog synchronization service."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Protocol
from uuid import UUID

from rolling_thunder.domain import Contact
from rolling_thunder.home_platform import (
    ContactUploadDisposition,
    ContactUploadResult,
    HomePlatformAvailability,
    HomePlatformState,
)
from rolling_thunder.wavelog import (
    WavelogError,
    WavelogStationTarget,
    WavelogUploadDisposition,
    contact_to_adif,
)

Clock = Callable[[], datetime]


class WavelogContactSync(Protocol):
    """Narrow Forge station-routing and QSO-write boundary."""

    def verify_health_target(self) -> None: ...

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget: ...

    def upload_contact(
        self,
        contact: Contact,
        *,
        target: WavelogStationTarget,
    ) -> WavelogUploadDisposition: ...


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ForgeContactSyncStorageError(RuntimeError):
    """Raised when the Forge synchronization ledger cannot be used safely."""


class ForgeContactPayloadConflictError(RuntimeError):
    """Raised when one contact UUID is reused with different remote QSO data."""


class ForgeContactLedgerState(StrEnum):
    """Durable certainty state for one contact upload."""

    PENDING = "pending"
    SYNCHRONIZED = "synchronized"


class ForgeContactClaimDisposition(StrEnum):
    """Result of claiming one idempotency key in the durable ledger."""

    ATTEMPT = "attempt"
    ALREADY_SYNCHRONIZED = "already_synchronized"


class ForgeContactSyncRepository:
    """SQLite ledger that survives Forge and Wavelog restarts."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = database_path
        try:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(database_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS forge_contact_sync_ledger (
                        contact_id TEXT PRIMARY KEY,
                        payload_sha256 TEXT NOT NULL CHECK(length(payload_sha256) = 64),
                        station_profile_id INTEGER NOT NULL CHECK(station_profile_id > 0),
                        state TEXT NOT NULL CHECK(state IN ('pending', 'synchronized')),
                        remote_disposition TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        synchronized_at TEXT,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE INDEX IF NOT EXISTS forge_contact_sync_state_index
                    ON forge_contact_sync_ledger (state, updated_at)
                    """
                )
                connection.commit()
        except (OSError, sqlite3.Error) as error:
            raise ForgeContactSyncStorageError(
                f"Forge contact synchronization ledger could not be initialized: {database_path}"
            ) from error

    def claim(
        self,
        contact_id: UUID,
        *,
        payload_sha256: str,
        station_profile_id: int,
    ) -> ForgeContactClaimDisposition:
        """Claim one stable contact identity, rejecting any changed payload or target."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    """
                    SELECT payload_sha256, station_profile_id, state
                    FROM forge_contact_sync_ledger
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                ).fetchone()
                if row is None:
                    connection.execute(
                        """
                        INSERT INTO forge_contact_sync_ledger (
                            contact_id,
                            payload_sha256,
                            station_profile_id,
                            state
                        )
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            str(contact_id),
                            payload_sha256,
                            station_profile_id,
                            ForgeContactLedgerState.PENDING.value,
                        ),
                    )
                    connection.commit()
                    return ForgeContactClaimDisposition.ATTEMPT

                stored_hash, stored_station_id, stored_state = row
                if stored_hash != payload_sha256 or stored_station_id != station_profile_id:
                    connection.rollback()
                    raise ForgeContactPayloadConflictError(
                        "Contact idempotency key was already used with different QSO data "
                        "or a different Wavelog station location."
                    )
                connection.commit()
                if stored_state == ForgeContactLedgerState.SYNCHRONIZED.value:
                    return ForgeContactClaimDisposition.ALREADY_SYNCHRONIZED
                return ForgeContactClaimDisposition.ATTEMPT
        except ForgeContactPayloadConflictError:
            raise
        except sqlite3.Error as error:
            raise ForgeContactSyncStorageError(
                f"Forge contact synchronization ledger claim failed: {contact_id}"
            ) from error

    def mark_synchronized(
        self,
        contact_id: UUID,
        *,
        synchronized_at: datetime,
        remote_disposition: WavelogUploadDisposition,
    ) -> None:
        """Durably record that Wavelog accepted or recognized one contact."""
        timestamp = synchronized_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        try:
            with sqlite3.connect(self._database_path) as connection:
                result = connection.execute(
                    """
                    UPDATE forge_contact_sync_ledger
                    SET state = ?,
                        remote_disposition = ?,
                        synchronized_at = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE contact_id = ?
                    """,
                    (
                        ForgeContactLedgerState.SYNCHRONIZED.value,
                        remote_disposition.value,
                        timestamp,
                        str(contact_id),
                    ),
                )
                if result.rowcount != 1:
                    raise ForgeContactSyncStorageError(
                        f"Forge contact synchronization ledger lost claim: {contact_id}"
                    )
                connection.commit()
        except ForgeContactSyncStorageError:
            raise
        except sqlite3.Error as error:
            raise ForgeContactSyncStorageError(
                f"Forge contact synchronization ledger update failed: {contact_id}"
            ) from error


class ForgeContactSyncService:
    """Serialize Wavelog writes behind a durable UUID-keyed Forge ledger."""

    def __init__(
        self,
        repository: ForgeContactSyncRepository,
        wavelog: WavelogContactSync,
        *,
        clock: Clock = _utc_now,
    ) -> None:
        self._repository = repository
        self._wavelog = wavelog
        self._clock = clock
        self._lock = Lock()

    def health(self) -> HomePlatformState:
        """Return a typed availability snapshot after verifying the configured location."""
        checked_at = self._timestamp()
        try:
            self._wavelog.verify_health_target()
        except WavelogError as error:
            return HomePlatformState(
                availability=HomePlatformAvailability.UNAVAILABLE,
                checked_at=checked_at,
                last_error=str(error)[:500],
            )
        return HomePlatformState(
            availability=HomePlatformAvailability.AVAILABLE,
            checked_at=checked_at,
        )

    def synchronize(self, contact: Contact) -> ContactUploadResult:
        """Synchronize one contact idempotently, retrying uncertain remote outcomes safely."""
        with self._lock:
            target = self._wavelog.resolve_station_target(contact)
            payload_sha256 = _remote_payload_sha256(
                contact,
                station_profile_id=target.location.station_id,
            )
            claim = self._repository.claim(
                contact.contact_id,
                payload_sha256=payload_sha256,
                station_profile_id=target.location.station_id,
            )
            received_at = self._timestamp()
            if claim is ForgeContactClaimDisposition.ALREADY_SYNCHRONIZED:
                return ContactUploadResult(
                    contact_id=contact.contact_id,
                    disposition=ContactUploadDisposition.ALREADY_EXISTS,
                    received_at=received_at,
                )

            remote_disposition = self._wavelog.upload_contact(contact, target=target)
            self._repository.mark_synchronized(
                contact.contact_id,
                synchronized_at=received_at,
                remote_disposition=remote_disposition,
            )
            disposition = (
                ContactUploadDisposition.ALREADY_EXISTS
                if remote_disposition is WavelogUploadDisposition.DUPLICATE
                else ContactUploadDisposition.ACCEPTED
            )
            return ContactUploadResult(
                contact_id=contact.contact_id,
                disposition=disposition,
                received_at=received_at,
            )

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Forge contact synchronization clock must be timezone-aware.")
        return timestamp.astimezone(UTC)


def _remote_payload_sha256(contact: Contact, *, station_profile_id: int) -> str:
    """Hash only stable Wavelog-bound data, excluding local synchronization state."""
    payload = f"{station_profile_id}\n{contact_to_adif(contact)}".encode()
    return hashlib.sha256(payload).hexdigest()
