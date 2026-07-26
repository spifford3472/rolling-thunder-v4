"""Tests for the deterministic mock Home Station Platform client."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.home_platform import (
    ContactUploadDisposition,
    ContactUploadRequest,
    HomePlatformAvailability,
    HomePlatformConnectionError,
    HomePlatformUploadError,
)
from rolling_thunder.mock_home_platform import MockHomePlatformClient

_CONTACT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")


def timestamp() -> datetime:
    return datetime(2026, 7, 26, 12, 0, tzinfo=UTC)


def request() -> ContactUploadRequest:
    return ContactUploadRequest(
        contact=Contact(
            contact_id=_CONTACT_ID,
            callsign="KI5VNB",
            frequency_hz=7_255_000,
            mode=RadioMode.LSB,
            started_at=timestamp(),
            rst_sent="59",
            rst_received="59",
        )
    )


def test_mock_starts_with_unknown_state_without_health_check() -> None:
    client = MockHomePlatformClient(clock=timestamp)

    state = client.get_state()

    assert state.availability is HomePlatformAvailability.UNKNOWN
    assert state.checked_at == timestamp()


def test_health_check_reports_available_and_unavailable() -> None:
    client = MockHomePlatformClient(clock=timestamp)

    available = client.check_health()
    client.set_available(False)
    unavailable = client.check_health()

    assert available.availability is HomePlatformAvailability.AVAILABLE
    assert available.last_error is None
    assert unavailable.availability is HomePlatformAvailability.UNAVAILABLE
    assert unavailable.last_error == "Home Station Platform is unavailable."


def test_upload_is_idempotent_by_contact_id() -> None:
    client = MockHomePlatformClient(clock=timestamp)

    first = client.upload_contact(request())
    second = client.upload_contact(request())

    assert first.contact_id == _CONTACT_ID
    assert first.disposition is ContactUploadDisposition.ACCEPTED
    assert second.contact_id == _CONTACT_ID
    assert second.disposition is ContactUploadDisposition.ALREADY_EXISTS


def test_unavailable_upload_raises_typed_connection_error() -> None:
    client = MockHomePlatformClient(clock=timestamp, available=False)

    with pytest.raises(HomePlatformConnectionError, match="unavailable"):
        client.upload_contact(request())


def test_configured_upload_failure_occurs_once() -> None:
    client = MockHomePlatformClient(clock=timestamp)
    client.fail_next_upload("remote validation rejected contact")

    with pytest.raises(HomePlatformUploadError, match="remote validation"):
        client.upload_contact(request())

    result = client.upload_contact(request())
    assert result.disposition is ContactUploadDisposition.ACCEPTED


def test_blank_upload_failure_message_is_rejected() -> None:
    client = MockHomePlatformClient(clock=timestamp)

    with pytest.raises(ValueError, match="must not be empty"):
        client.fail_next_upload("   ")


def test_mock_clock_must_be_timezone_aware() -> None:
    def naive_clock() -> datetime:
        return datetime(2026, 7, 26, 12, 0)

    with pytest.raises(ValueError, match="timezone-aware"):
        MockHomePlatformClient(clock=naive_clock)
