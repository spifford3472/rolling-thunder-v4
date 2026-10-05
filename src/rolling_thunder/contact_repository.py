"""SQLite-backed persistence for Rolling Thunder contacts."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    ContactGridSource,
    RadioMode,
    SynchronizationState,
)
from rolling_thunder.storage import StorageError, initialize_database
from rolling_thunder.value_types import MaidenheadGrid

_MAX_LIST_LIMIT = 1_000


class ContactAlreadyExistsError(StorageError):
    """Raised when a contact UUID is already stored."""


class ContactNotFoundError(StorageError):
    """Raised when a requested contact does not exist."""


class ContactConflictError(StorageError):
    """Raised when an existing UUID contains different contact data."""


class ContactRepository:
    """Create, retrieve, and list durable contacts from SQLite."""

    def __init__(self, database_path: Path) -> None:
        """Prepare a repository backed by the configured database."""
        self._database_path = database_path
        initialize_database(database_path)

    def add(self, contact: Contact) -> None:
        """Persist a contact and commit it before returning."""
        values = {
            "contact_id": str(contact.contact_id),
            "callsign": contact.callsign,
            "frequency_hz": contact.frequency_hz,
            "mode": contact.mode.value,
            "started_at": contact.started_at.isoformat().replace("+00:00", "Z"),
            "rst_sent": contact.rst_sent,
            "rst_received": contact.rst_received,
            "grid": contact.grid,
            "my_grid": contact.my_grid,
            "my_latitude": contact.my_latitude,
            "my_longitude": contact.my_longitude,
            "my_state": contact.my_state,
            "my_cq_zone": contact.my_cq_zone,
            "my_itu_zone": contact.my_itu_zone,
            "pota_reference": contact.pota_reference,
            "grid_source": (contact.grid_source.value if contact.grid_source is not None else None),
            "enrichment_state": contact.enrichment_state.value,
            "notes": contact.notes,
            "synchronization_state": contact.synchronization_state.value,
        }

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.execute(
                    """
                    INSERT INTO contacts (
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    )
                    VALUES (
                        :contact_id,
                        :callsign,
                        :frequency_hz,
                        :mode,
                        :started_at,
                        :rst_sent,
                        :rst_received,
                        :grid,
                        :my_grid,
                        :my_latitude,
                        :my_longitude,
                        :my_state,
                        :my_cq_zone,
                        :my_itu_zone,
                        :pota_reference,
                        :grid_source,
                        :enrichment_state,
                        :notes,
                        :synchronization_state
                    )
                    """,
                    values,
                )
                connection.commit()
        except sqlite3.IntegrityError as error:
            if self.get(contact.contact_id) is not None:
                raise ContactAlreadyExistsError(
                    f"Contact already exists: {contact.contact_id}"
                ) from error

            raise StorageError(
                f"Contact could not be stored because it violates "
                f"the database schema: {contact.contact_id}: {error}"
            ) from error
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact could not be stored in "
                f"{self._database_path}: {contact.contact_id}: {error}"
            ) from error

    def add_idempotent(self, contact: Contact) -> Contact:
        """Persist once, returning the existing identical contact on replay."""
        try:
            self.add(contact)
            return contact
        except ContactAlreadyExistsError:
            existing = self.get(contact.contact_id)
            if existing is not None and self._same_idempotent_payload(existing, contact):
                return existing
            raise ContactConflictError(
                f"Contact UUID was reused with different data: {contact.contact_id}"
            )

    def get(self, contact_id: UUID) -> Contact | None:
        """Retrieve one contact by UUID, or return None when it is absent."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact could not be read from {self._database_path}: {contact_id}: {error}"
            ) from error

        if row is None:
            return None

        return self._contact_from_row(row, contact_id)

    def update(self, contact: Contact) -> Contact:
        """Atomically replace one stored contact and return it."""
        values = {
            "contact_id": str(contact.contact_id),
            "callsign": contact.callsign,
            "frequency_hz": contact.frequency_hz,
            "mode": contact.mode.value,
            "started_at": contact.started_at.isoformat().replace(
                "+00:00",
                "Z",
            ),
            "rst_sent": contact.rst_sent,
            "rst_received": contact.rst_received,
            "grid": contact.grid,
            "my_grid": contact.my_grid,
            "my_latitude": contact.my_latitude,
            "my_longitude": contact.my_longitude,
            "my_state": contact.my_state,
            "my_cq_zone": contact.my_cq_zone,
            "my_itu_zone": contact.my_itu_zone,
            "pota_reference": contact.pota_reference,
            "grid_source": (contact.grid_source.value if contact.grid_source is not None else None),
            "enrichment_state": contact.enrichment_state.value,
            "notes": contact.notes,
            "synchronization_state": contact.synchronization_state.value,
        }

        try:
            with sqlite3.connect(self._database_path) as connection:
                result = connection.execute(
                    """
                    UPDATE contacts
                    SET callsign = :callsign,
                        frequency_hz = :frequency_hz,
                        mode = :mode,
                        started_at = :started_at,
                        rst_sent = :rst_sent,
                        rst_received = :rst_received,
                        grid = :grid,
                        my_grid = :my_grid,
                        my_latitude = :my_latitude,
                        my_longitude = :my_longitude,
                        my_state = :my_state,
                        my_cq_zone = :my_cq_zone,
                        my_itu_zone = :my_itu_zone,
                        pota_reference = :pota_reference,
                        grid_source = :grid_source,
                        enrichment_state = :enrichment_state,
                        notes = :notes,
                        synchronization_state = :synchronization_state,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE contact_id = :contact_id
                    """,
                    values,
                )

                if result.rowcount == 0:
                    raise ContactNotFoundError(f"Contact does not exist: {contact.contact_id}")

                connection.commit()
        except ContactNotFoundError:
            raise
        except sqlite3.IntegrityError as error:
            raise StorageError(
                "Contact could not be updated because it violates "
                f"the database schema: {contact.contact_id}: {error}"
            ) from error
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact could not be updated in "
                f"{self._database_path}: {contact.contact_id}: {error}"
            ) from error

        updated_contact = self.get(contact.contact_id)

        if updated_contact is None:
            raise StorageError(f"Contact disappeared after update: {contact.contact_id}")

        return updated_contact

    def delete(self, contact_id: UUID) -> Contact:
        """Atomically delete and return one stored contact."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                row = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                ).fetchone()

                if row is None:
                    raise ContactNotFoundError(f"Contact does not exist: {contact_id}")

                contact = self._contact_from_row(row, contact_id)

                result = connection.execute(
                    """
                    DELETE FROM contacts
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                )

                if result.rowcount != 1:
                    raise StorageError(
                        "Contact deletion affected an unexpected number "
                        f"of rows: {contact_id}: {result.rowcount}"
                    )

                connection.commit()
        except (ContactNotFoundError, StorageError):
            raise
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact could not be deleted from {self._database_path}: {contact_id}: {error}"
            ) from error

        return contact

    def update_synchronization_state(
        self,
        contact_id: UUID,
        state: SynchronizationState,
    ) -> Contact:
        """Persist and return a contact's new synchronization state."""
        if not isinstance(state, SynchronizationState):
            raise TypeError("Synchronization state must be a SynchronizationState.")

        try:
            with sqlite3.connect(self._database_path) as connection:
                result = connection.execute(
                    """
                    UPDATE contacts
                    SET synchronization_state = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE contact_id = ?
                    """,
                    (state.value, str(contact_id)),
                )

                if result.rowcount == 0:
                    raise ContactNotFoundError(f"Contact does not exist: {contact_id}")

                connection.commit()
        except ContactNotFoundError:
            raise
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact synchronization state could not be updated in "
                f"{self._database_path}: {contact_id}: {error}"
            ) from error

        updated_contact = self.get(contact_id)

        if updated_contact is None:
            raise StorageError(
                f"Contact disappeared after synchronization-state update: {contact_id}"
            )

        return updated_contact

    def recover_contacts(
        self,
        contacts: list[Contact],
    ) -> tuple[int, int]:
        """Transactionally import contacts, skipping exact duplicates."""
        imported_count = 0
        skipped_count = 0

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row

                for contact in contacts:
                    existing_row = connection.execute(
                        """
                        SELECT
                            contact_id,
                            callsign,
                            frequency_hz,
                            mode,
                            started_at,
                            rst_sent,
                            rst_received,
                            grid,
                            my_grid,
                            my_latitude,
                            my_longitude,
                            my_state,
                            my_cq_zone,
                            my_itu_zone,
                            pota_reference,
                            grid_source,
                            enrichment_state,
                            notes,
                            synchronization_state
                        FROM contacts
                        WHERE contact_id = ?
                        """,
                        (str(contact.contact_id),),
                    ).fetchone()

                    if existing_row is not None:
                        existing = self._contact_from_row(
                            existing_row,
                            contact.contact_id,
                        )

                        if existing == contact:
                            skipped_count += 1
                            continue

                        raise ContactConflictError(
                            f"Contact recovery conflict for UUID {contact.contact_id}."
                        )

                    connection.execute(
                        """
                        INSERT INTO contacts (
                            contact_id,
                            callsign,
                            frequency_hz,
                            mode,
                            started_at,
                            rst_sent,
                            rst_received,
                            grid,
                            my_grid,
                            my_latitude,
                            my_longitude,
                            my_state,
                            my_cq_zone,
                            my_itu_zone,
                            pota_reference,
                            grid_source,
                            enrichment_state,
                            notes,
                            synchronization_state
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            str(contact.contact_id),
                            contact.callsign,
                            contact.frequency_hz,
                            contact.mode.value,
                            contact.started_at.isoformat().replace(
                                "+00:00",
                                "Z",
                            ),
                            contact.rst_sent,
                            contact.rst_received,
                            contact.grid,
                            contact.my_grid,
                            contact.my_latitude,
                            contact.my_longitude,
                            contact.my_state,
                            contact.my_cq_zone,
                            contact.my_itu_zone,
                            contact.pota_reference,
                            (
                                contact.grid_source.value
                                if contact.grid_source is not None
                                else None
                            ),
                            contact.enrichment_state.value,
                            contact.notes,
                            contact.synchronization_state.value,
                        ),
                    )
                    imported_count += 1

                connection.commit()
        except ContactConflictError:
            raise
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be recovered into {self._database_path}: {error}"
            ) from error

        return imported_count, skipped_count

    def list_all(self) -> list[Contact]:
        """List every contact from newest to oldest."""
        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    ORDER BY started_at DESC, contact_id ASC
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be listed from {self._database_path}: {error}"
            ) from error

        return self._contacts_from_rows(rows)

    def list_since(
        self,
        started_at: datetime,
        *,
        mode: RadioMode | None = None,
    ) -> list[Contact]:
        """List contacts at or after one UTC instant, optionally limited by mode."""
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        normalized = started_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
        query = """
            SELECT
                contact_id,
                callsign,
                frequency_hz,
                mode,
                started_at,
                rst_sent,
                rst_received,
                grid,
                my_grid,
                my_latitude,
                my_longitude,
                pota_reference,
                grid_source,
                enrichment_state,
                notes,
                synchronization_state
            FROM contacts
            WHERE started_at >= ?
        """
        parameters: tuple[object, ...]
        if mode is None:
            parameters = (normalized,)
        else:
            query += " AND mode = ?"
            parameters = (normalized, mode.value)
        query += " ORDER BY started_at DESC, contact_id ASC"

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(query, parameters).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be listed from {self._database_path}: {error}"
            ) from error
        return self._contacts_from_rows(rows)

    def list_recent(self, *, limit: int = 100) -> list[Contact]:
        """List contacts from newest to oldest."""
        self._validate_limit(limit)

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    ORDER BY started_at DESC, contact_id ASC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be listed from {self._database_path}: {error}"
            ) from error

        return self._contacts_from_rows(rows)

    def list_by_synchronization_state(
        self,
        state: SynchronizationState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        """List contacts in one synchronization state, newest first."""
        self._validate_limit(limit)

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    WHERE synchronization_state = ?
                    ORDER BY started_at DESC, contact_id ASC
                    LIMIT ?
                    """,
                    (state.value, limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be listed from "
                f"{self._database_path}: synchronization_state="
                f"{state.value}: {error}"
            ) from error

        return self._contacts_from_rows(rows)

    def list_synchronization_eligible(
        self,
        state: SynchronizationState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        """List contacts ready for remote synchronization."""
        self._validate_limit(limit)

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    WHERE synchronization_state = ?
                      AND enrichment_state = 'ready'
                    ORDER BY started_at DESC, contact_id ASC
                    LIMIT ?
                    """,
                    (state.value, limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Synchronization-eligible contacts could not be listed from "
                f"{self._database_path}: synchronization_state="
                f"{state.value}: {error}"
            ) from error

        return self._contacts_from_rows(rows)

    def list_by_enrichment_state(
        self,
        state: ContactEnrichmentState,
        *,
        limit: int = 100,
    ) -> list[Contact]:
        """List contacts in one enrichment state, newest first."""
        self._validate_limit(limit)

        if not isinstance(state, ContactEnrichmentState):
            raise TypeError("Contact enrichment state must be a ContactEnrichmentState.")

        try:
            with sqlite3.connect(self._database_path) as connection:
                connection.row_factory = sqlite3.Row
                rows = connection.execute(
                    """
                    SELECT
                        contact_id,
                        callsign,
                        frequency_hz,
                        mode,
                        started_at,
                        rst_sent,
                        rst_received,
                        grid,
                        my_grid,
                        my_latitude,
                        my_longitude,
                        my_state,
                        my_cq_zone,
                        my_itu_zone,
                        pota_reference,
                        grid_source,
                        enrichment_state,
                        notes,
                        synchronization_state
                    FROM contacts
                    WHERE enrichment_state = ?
                    ORDER BY started_at DESC, contact_id ASC
                    LIMIT ?
                    """,
                    (state.value, limit),
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be listed from "
                f"{self._database_path}: enrichment_state="
                f"{state.value}: {error}"
            ) from error

        return self._contacts_from_rows(rows)

    def complete_enrichment(
        self,
        contact_id: UUID,
        *,
        grid: MaidenheadGrid | None,
        grid_source: ContactGridSource | None,
    ) -> Contact:
        """Atomically complete optional contacted-grid enrichment."""
        existing = self.get(contact_id)
        if existing is None:
            raise ContactNotFoundError(f"Contact does not exist: {contact_id}")

        candidate = Contact.model_validate(
            {
                **existing.model_dump(mode="python"),
                "grid": grid,
                "grid_source": grid_source,
                "enrichment_state": ContactEnrichmentState.READY,
            }
        )

        try:
            with sqlite3.connect(self._database_path) as connection:
                result = connection.execute(
                    """
                    UPDATE contacts
                    SET grid = ?,
                        grid_source = ?,
                        enrichment_state = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE contact_id = ?
                      AND enrichment_state = ?
                    """,
                    (
                        candidate.grid,
                        (
                            candidate.grid_source.value
                            if candidate.grid_source is not None
                            else None
                        ),
                        ContactEnrichmentState.READY.value,
                        str(contact_id),
                        ContactEnrichmentState.PENDING_QRZ.value,
                    ),
                )
                connection.commit()
        except sqlite3.IntegrityError as error:
            raise StorageError(
                "Contact enrichment could not be completed because it "
                f"violates the database schema: {contact_id}: {error}"
            ) from error
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact enrichment could not be completed in "
                f"{self._database_path}: {contact_id}: {error}"
            ) from error

        if result.rowcount == 0:
            current = self.get(contact_id)
            if current is not None and current.enrichment_state is ContactEnrichmentState.READY:
                return current
            raise StorageError(f"Contact enrichment state changed unexpectedly: {contact_id}")

        completed = self.get(contact_id)
        if completed is None:
            raise StorageError(f"Contact disappeared after enrichment: {contact_id}")
        return completed

    @staticmethod
    def _same_idempotent_payload(existing: Contact, candidate: Contact) -> bool:
        """Compare immutable QSO data while allowing later sync/enrichment state changes."""
        if (
            existing.callsign != candidate.callsign
            or existing.frequency_hz != candidate.frequency_hz
            or existing.mode is not candidate.mode
            or existing.started_at != candidate.started_at
            or existing.rst_sent != candidate.rst_sent
            or existing.rst_received != candidate.rst_received
            or existing.my_grid != candidate.my_grid
            or existing.my_latitude != candidate.my_latitude
            or existing.my_longitude != candidate.my_longitude
            or existing.my_state != candidate.my_state
            or existing.my_cq_zone != candidate.my_cq_zone
            or existing.my_itu_zone != candidate.my_itu_zone
            or existing.pota_reference != candidate.pota_reference
            or existing.notes != candidate.notes
        ):
            return False
        return candidate.grid is None or existing.grid == candidate.grid

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Require a bounded positive contact-list limit."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("Contact list limit must be an integer.")

        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(f"Contact list limit must be between 1 and {_MAX_LIST_LIMIT}.")

    @classmethod
    def _contacts_from_rows(
        cls,
        rows: list[sqlite3.Row],
    ) -> list[Contact]:
        """Reconstruct and validate contacts from database rows."""
        return [cls._contact_from_row(row, row["contact_id"]) for row in rows]

    @staticmethod
    def _contact_from_row(
        row: sqlite3.Row,
        requested_contact_id: object,
    ) -> Contact:
        """Reconstruct and validate a domain contact from one database row."""
        values: dict[str, Any] = {
            "contact_id": row["contact_id"],
            "callsign": row["callsign"],
            "frequency_hz": row["frequency_hz"],
            "mode": row["mode"],
            "started_at": row["started_at"],
            "rst_sent": row["rst_sent"],
            "rst_received": row["rst_received"],
            "grid": row["grid"],
            "my_grid": row["my_grid"],
            "my_latitude": row["my_latitude"],
            "my_longitude": row["my_longitude"],
            "my_state": row["my_state"],
            "my_cq_zone": row["my_cq_zone"],
            "my_itu_zone": row["my_itu_zone"],
            "pota_reference": row["pota_reference"],
            "grid_source": row["grid_source"],
            "enrichment_state": row["enrichment_state"],
            "notes": row["notes"],
            "synchronization_state": row["synchronization_state"],
        }

        try:
            return Contact.model_validate(values)
        except ValidationError as error:
            raise StorageError(
                f"Stored contact is invalid: {requested_contact_id}: {error}"
            ) from error
