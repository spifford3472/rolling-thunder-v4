"""Successful FT8 QSO integration with the existing local-first contact logger."""

from __future__ import annotations

from threading import RLock

from rolling_thunder.contact_logging import ContactLoggingService
from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.domain import FT8QsoState
from rolling_thunder.storage import StorageError


class FT8QsoLoggingService:
    """Persist only immutable successful FT8 terminal results."""

    def __init__(self, contact_logging: ContactLoggingService) -> None:
        self._contact_logging = contact_logging
        self._lock = RLock()
        self._latest_contact: Contact | None = None
        self._latest_error: str | None = None

    @property
    def latest_contact(self) -> Contact | None:
        with self._lock:
            return self._latest_contact

    @property
    def latest_error(self) -> str | None:
        with self._lock:
            return self._latest_error

    def handle_terminal_result(self, result: FT8QsoResult) -> Contact | None:
        """Log COMPLETED exactly once by stable QSO UUID; ignore all other outcomes."""
        if result.status is not FT8QsoState.COMPLETED:
            return None
        if result.received_report_db is None:
            with self._lock:
                self._latest_error = "completed FT8 QSO is missing the received signal report"
            return None

        try:
            contact = self._contact_logging.commit_completed(
                contact_id=result.context.qso_id,
                callsign=result.context.remote_callsign,
                frequency_hz=result.context.radio_frequency_hz,
                mode=RadioMode.FT8,
                started_at=result.started_utc,
                rst_sent=_format_db_report(result.sent_report_db),
                rst_received=_format_db_report(result.received_report_db),
                my_grid=result.context.local_grid,
                grid=result.context.remote_grid,
            )
        except (StorageError, ValueError) as error:
            with self._lock:
                self._latest_error = str(error)
            return None

        with self._lock:
            self._latest_contact = contact
            self._latest_error = None
        return contact


def _format_db_report(value: int) -> str:
    """Preserve FT8 signed dB text without voice-report defaults."""
    if value > 0:
        return f"+{value}"
    return str(value)
