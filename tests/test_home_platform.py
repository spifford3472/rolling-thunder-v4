"""Tests for typed Home Station Platform boundary models."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Contact, RadioMode, SynchronizationState
from rolling_thunder.home_platform import (
    ContactUploadDisposition,
    ContactUploadRequest,
    ContactUploadResult,
    HomePlatformAvailability,
    HomePlatformState,
)

_CONTACT_ID = UUID("11111111-2222-3333-4444-555555555555")


def timestamp() -> datetime:
    return datetime(2026, 7, 26, 11, 0, tzinfo=UTC)


def contact() -> Contact:
    return Contact(
        contact_id=_CONTACT_ID,
        callsign="W8O",
        frequency_hz=14_250_000,
        mode=RadioMode.USB,
        started_at=timestamp(),
        rst_sent="59",
        rst_received="59",
        grid="EM79",
        synchronization_state=SynchronizationState.PENDING,
    )


def test_platform_state_normalizes_values_and_serializes_utc() -> None:
    eastern = timezone(timedelta(hours=-4))

    state = HomePlatformState(
        availability=" AVAILABLE ",
        checked_at=datetime(2026, 7, 26, 7, 0, tzinfo=eastern),
    )

    assert state.availability is HomePlatformAvailability.AVAILABLE
    assert state.checked_at == timestamp()
    assert state.model_dump(mode="json")["checked_at"] == "2026-07-26T11:00:00Z"


def test_unavailable_platform_state_requires_error() -> None:
    with pytest.raises(ValidationError, match="requires last_error"):
        HomePlatformState(
            availability=HomePlatformAvailability.UNAVAILABLE,
            checked_at=timestamp(),
        )


def test_platform_state_trims_error_and_is_immutable() -> None:
    state = HomePlatformState(
        availability=HomePlatformAvailability.UNAVAILABLE,
        checked_at=timestamp(),
        last_error="  connection refused  ",
    )

    assert state.last_error == "connection refused"
    with pytest.raises(ValidationError, match="frozen"):
        state.last_error = "changed"


def test_upload_request_uses_contact_id_as_idempotency_key() -> None:
    request = ContactUploadRequest(contact=contact())

    assert request.idempotency_key == _CONTACT_ID
    assert request.contact.synchronization_state is SynchronizationState.PENDING


def test_upload_result_normalizes_and_serializes() -> None:
    result = ContactUploadResult(
        contact_id=_CONTACT_ID,
        disposition=" ALREADY_EXISTS ",
        received_at=timestamp(),
    )

    assert result.disposition is ContactUploadDisposition.ALREADY_EXISTS
    assert result.model_dump(mode="json") == {
        "contact_id": str(_CONTACT_ID),
        "disposition": "already_exists",
        "received_at": "2026-07-26T11:00:00Z",
    }


@pytest.mark.parametrize("field", ["checked_at", "received_at"])
def test_platform_timestamps_require_timezone(field: str) -> None:
    naive = datetime(2026, 7, 26, 11, 0)  # noqa: DTZ001

    if field == "checked_at":
        with pytest.raises(ValidationError, match="timezone"):
            HomePlatformState(
                availability=HomePlatformAvailability.UNKNOWN,
                checked_at=naive,
            )
    else:
        with pytest.raises(ValidationError, match="timezone"):
            ContactUploadResult(
                contact_id=_CONTACT_ID,
                disposition=ContactUploadDisposition.ACCEPTED,
                received_at=naive,
            )
