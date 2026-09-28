"""Deterministic mock Home Station Platform client."""

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from rolling_thunder.home_platform import (
    ContactUploadDisposition,
    ContactUploadRequest,
    ContactUploadResult,
    HomePlatformAvailability,
    HomePlatformConnectionError,
    HomePlatformState,
    HomePlatformUploadError,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MockHomePlatformClient:
    """Predictable in-memory platform client for tests and mock operation."""

    def __init__(
        self,
        *,
        clock: Clock = _utc_now,
        available: bool = True,
    ) -> None:
        self._clock = clock
        self._available = available
        self._uploaded_ids: set[UUID] = set()
        self._next_upload_error: str | None = None
        self._state = HomePlatformState(
            availability=HomePlatformAvailability.UNKNOWN,
            checked_at=self._timestamp(),
        )

    def get_state(self) -> HomePlatformState:
        """Return the latest immutable state without performing work."""
        return self._state

    def check_health(self) -> HomePlatformState:
        """Publish deterministic available or unavailable state."""
        if self._available:
            self._state = HomePlatformState(
                availability=HomePlatformAvailability.AVAILABLE,
                checked_at=self._timestamp(),
            )
            return self._state

        self._state = HomePlatformState(
            availability=HomePlatformAvailability.UNAVAILABLE,
            checked_at=self._timestamp(),
            last_error="Home Station Platform is unavailable.",
        )
        return self._state

    def upload_contact(self, request: ContactUploadRequest) -> ContactUploadResult:
        """Store one contact ID and return an idempotent deterministic result."""
        if not self._available:
            raise HomePlatformConnectionError(
                "Cannot upload contact while Home Station Platform is unavailable."
            )
        if self._next_upload_error is not None:
            message = self._next_upload_error
            self._next_upload_error = None
            raise HomePlatformUploadError(message)

        contact_id = request.idempotency_key
        disposition = ContactUploadDisposition.ACCEPTED
        if contact_id in self._uploaded_ids:
            disposition = ContactUploadDisposition.ALREADY_EXISTS
        else:
            self._uploaded_ids.add(contact_id)

        return ContactUploadResult(
            contact_id=contact_id,
            disposition=disposition,
            received_at=self._timestamp(),
        )

    def set_available(self, available: bool) -> None:
        """Configure the next health and upload behavior."""
        self._available = available

    def fail_next_upload(self, message: str) -> None:
        """Configure one deterministic typed upload failure."""
        normalized = message.strip()
        if not normalized:
            raise ValueError("mock upload error message must not be empty")
        self._next_upload_error = normalized

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(
                "Mock Home Station Platform clock must return a timezone-aware datetime."
            )
        return timestamp.astimezone(UTC)
