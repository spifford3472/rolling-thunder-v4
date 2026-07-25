"""SQLite-backed persistence for Rolling Thunder contacts."""

import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import ValidationError

from rolling_thunder.domain import Contact, SynchronizationState
from rolling_thunder.storage import StorageError, initialize_database

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
                        notes,
                        synchronization_state
                    FROM contacts
                    WHERE contact_id = ?
                    """,
                    (str(contact_id),),
                ).fetchone()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contact could not be read from "
                f"{self._database_path}: {contact_id}: {error}"
            ) from error

        if row is None:
            return None

        return self._contact_from_row(row, contact_id)

    def update_synchronization_state(
        self,
        contact_id: UUID,
        state: SynchronizationState,
    ) -> Contact:
        """Persist and return a contact's new synchronization state."""
        if not isinstance(state, SynchronizationState):
            raise TypeError(
                "Synchronization state must be a SynchronizationState."
            )

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
                    raise ContactNotFoundError(
                        f"Contact does not exist: {contact_id}"
                    )

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
                f"Contact disappeared after synchronization-state update: "
                f"{contact_id}"
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
                            "Contact recovery conflict for UUID "
                            f"{contact.contact_id}."
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
                            notes,
                            synchronization_state
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                f"Contacts could not be recovered into "
                f"{self._database_path}: {error}"
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
                        notes,
                        synchronization_state
                    FROM contacts
                    ORDER BY started_at DESC, contact_id ASC
                    """
                ).fetchall()
        except sqlite3.Error as error:
            raise StorageError(
                f"Contacts could not be listed from "
                f"{self._database_path}: {error}"
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
                f"Contacts could not be listed from "
                f"{self._database_path}: {error}"
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

    @staticmethod
    def _validate_limit(limit: int) -> None:
        """Require a bounded positive contact-list limit."""
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise TypeError("Contact list limit must be an integer.")

        if limit < 1 or limit > _MAX_LIST_LIMIT:
            raise ValueError(
                f"Contact list limit must be between 1 and {_MAX_LIST_LIMIT}."
            )

    @classmethod
    def _contacts_from_rows(
        cls,
        rows: list[sqlite3.Row],
    ) -> list[Contact]:
        """Reconstruct and validate contacts from database rows."""
        return [
            cls._contact_from_row(row, row["contact_id"])
            for row in rows
        ]

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
            "notes": row["notes"],
            "synchronization_state": row["synchronization_state"],
        }

        try:
            return Contact.model_validate(values)
        except ValidationError as error:
            raise StorageError(
                f"Stored contact is invalid: {requested_contact_id}: {error}"
            ) from error
