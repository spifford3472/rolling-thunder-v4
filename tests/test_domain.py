"""Tests for Rolling Thunder contact domain models."""

from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import (
    Contact,
    RadioMode,
    SynchronizationState,
)


def make_contact(**overrides: object) -> Contact:
    """Create a valid contact with optional field overrides."""
    values: dict[str, object] = {
        "callsign": "w8o",
        "frequency_hz": 14_250_000,
        "mode": "usb",
        "started_at": datetime(
            2026,
            9,
            19,
            15,
            30,
            tzinfo=UTC,
        ),
        "rst_sent": "59",
        "rst_received": "59",
        "grid": "em79XM",
        "notes": " Wright Brothers special event ",
    }
    values.update(overrides)
    return Contact.model_validate(values)


def test_contact_normalizes_operator_entered_values() -> None:
    """Common operator-entered text should be normalized."""
    contact = make_contact()

    assert contact.callsign == "W8O"
    assert contact.mode is RadioMode.USB
    assert contact.grid == "EM79xm"
    assert contact.notes == "Wright Brothers special event"
    assert contact.synchronization_state is SynchronizationState.PENDING


def test_contact_generates_unique_identifier() -> None:
    """A new contact should receive a UUID suitable for local identity."""
    first = make_contact()
    second = make_contact()

    assert isinstance(first.contact_id, UUID)
    assert first.contact_id != second.contact_id


def test_contact_accepts_portable_callsign() -> None:
    """Portable or mobile suffixes should be preserved."""
    contact = make_contact(callsign="ki5vnb/p")

    assert contact.callsign == "KI5VNB/P"


def test_contact_normalizes_timestamp_to_utc() -> None:
    """Timezone-aware timestamps should be stored in UTC."""
    eastern = timezone(timedelta(hours=-4))
    contact = make_contact(
        started_at=datetime(
            2026,
            7,
            24,
            19,
            30,
            tzinfo=eastern,
        )
    )

    assert contact.started_at == datetime(
        2026,
        7,
        24,
        23,
        30,
        tzinfo=UTC,
    )


def test_contact_rejects_naive_timestamp() -> None:
    """A timestamp without timezone information must be rejected."""
    with pytest.raises(ValidationError, match="timezone information"):
        make_contact(
            started_at=datetime(2026, 7, 24, 19, 30)  # noqa: DTZ001
        )


@pytest.mark.parametrize("report", ["59", "599", "-10", "+5"])
def test_contact_accepts_supported_signal_reports(report: str) -> None:
    """Voice, CW, and digital reports should be supported."""
    contact = make_contact(rst_sent=report, rst_received=report)

    assert contact.rst_sent == report
    assert contact.rst_received == report


@pytest.mark.parametrize("report", ["", "excellent", "5999", "-100"])
def test_contact_rejects_invalid_signal_reports(report: str) -> None:
    """Malformed signal reports should be rejected."""
    with pytest.raises(ValidationError, match="conventional report"):
        make_contact(rst_sent=report)


def test_contact_rejects_invalid_frequency() -> None:
    """Frequency must be represented by a positive number of hertz."""
    with pytest.raises(ValidationError):
        make_contact(frequency_hz=0)


def test_contact_rejects_invalid_grid() -> None:
    """Malformed Maidenhead grid locators should be rejected."""
    with pytest.raises(ValidationError, match="Maidenhead grid"):
        make_contact(grid="NOTAGRID")


def test_contact_converts_blank_notes_to_none() -> None:
    """Whitespace-only notes should not be persisted as meaningful data."""
    contact = make_contact(notes="   ")

    assert contact.notes is None


def test_contact_is_immutable() -> None:
    """Committed domain contacts should not be modified in place."""
    contact = make_contact()

    with pytest.raises(ValidationError):
        contact.callsign = "KI5VNB"


def test_contact_serialization_is_stable_and_json_compatible() -> None:
    """A contact should serialize consistently across persistence boundaries."""
    contact_id = UUID("6cf1aaf4-c54e-4ec8-ae55-229bd650ad5d")
    contact = make_contact(
        contact_id=contact_id,
        synchronization_state="synchronized",
    )

    serialized = contact.model_dump(mode="json")

    assert serialized == {
        "contact_id": "6cf1aaf4-c54e-4ec8-ae55-229bd650ad5d",
        "callsign": "W8O",
        "frequency_hz": 14_250_000,
        "mode": "USB",
        "started_at": "2026-09-19T15:30:00Z",
        "rst_sent": "59",
        "rst_received": "59",
        "grid": "EM79xm",
        "notes": "Wright Brothers special event",
        "synchronization_state": "synchronized",
    }


def test_contact_rejects_unknown_fields() -> None:
    """Unexpected data should not silently cross the domain boundary."""
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        make_contact(unknown_field="unexpected")


def test_frequency_exposes_common_units() -> None:
    """Frequency should retain exact hertz while exposing display units."""
    from rolling_thunder.domain import Frequency

    frequency = Frequency(hz=14_250_000)

    assert frequency.hz == 14_250_000
    assert frequency.khz == 14_250
    assert frequency.mhz == 14.25
    assert frequency.model_dump(mode="json") == 14_250_000


@pytest.mark.parametrize("frequency", [0, -1, 300_000_000_001, 14.25, True])
def test_frequency_rejects_invalid_values(frequency: object) -> None:
    """Frequency must contain a positive integer number of hertz."""
    from rolling_thunder.domain import Frequency

    with pytest.raises(ValidationError):
        Frequency(hz=frequency)


def test_connected_radio_state_normalizes_values() -> None:
    """Connected state should normalize mode, connection state, and time."""
    from rolling_thunder.domain import (
        Frequency,
        RadioConnectionState,
        RadioState,
    )

    eastern = timezone(timedelta(hours=-4))
    state = RadioState(
        connection_state=" CONNECTED ",
        frequency=Frequency(hz=7_200_000),
        mode="lsb",
        transmitting=False,
        updated_at=datetime(
            2026,
            7,
            24,
            20,
            30,
            tzinfo=eastern,
        ),
    )

    assert state.connection_state is RadioConnectionState.CONNECTED
    assert state.frequency == Frequency(hz=7_200_000)
    assert state.mode is RadioMode.LSB
    assert state.updated_at == datetime(
        2026,
        7,
        25,
        0,
        30,
        tzinfo=UTC,
    )


def test_connected_radio_state_requires_frequency_and_mode() -> None:
    """A connected radio must report its operating frequency and mode."""
    from rolling_thunder.domain import RadioState

    with pytest.raises(
        ValidationError,
        match="connected radio state requires a frequency",
    ):
        RadioState(
            connection_state="connected",
            updated_at=datetime.now(UTC),
        )


def test_transmitting_requires_connected_radio() -> None:
    """A disconnected or connecting radio cannot report transmission."""
    from rolling_thunder.domain import RadioState

    with pytest.raises(
        ValidationError,
        match="transmitting requires a connected radio",
    ):
        RadioState(
            connection_state="disconnected",
            transmitting=True,
            updated_at=datetime.now(UTC),
        )


def test_error_radio_state_requires_error_message() -> None:
    """An error state should provide actionable adapter information."""
    from rolling_thunder.domain import RadioState

    with pytest.raises(
        ValidationError,
        match="error radio state requires last_error",
    ):
        RadioState(
            connection_state="error",
            updated_at=datetime.now(UTC),
        )


def test_radio_state_normalizes_error_message() -> None:
    """Adapter errors should be trimmed before crossing the domain boundary."""
    from rolling_thunder.domain import RadioState

    state = RadioState(
        connection_state="error",
        updated_at=datetime.now(UTC),
        last_error=" CAT connection timed out ",
    )

    assert state.last_error == "CAT connection timed out"


def test_radio_state_serialization_is_stable() -> None:
    """Radio state should serialize consistently for APIs and persistence."""
    from rolling_thunder.domain import Frequency, RadioState

    state = RadioState(
        connection_state="connected",
        frequency=Frequency(hz=14_250_000),
        mode="usb",
        transmitting=True,
        updated_at=datetime(
            2026,
            7,
            25,
            0,
            15,
            tzinfo=UTC,
        ),
    )

    assert state.model_dump(mode="json") == {
        "connection_state": "connected",
        "frequency": 14_250_000,
        "mode": "USB",
        "transmitting": True,
        "updated_at": "2026-07-25T00:15:00Z",
        "last_error": None,
    }


def test_radio_state_is_immutable() -> None:
    """Radio-state snapshots should not be modified in place."""
    from rolling_thunder.domain import RadioState

    state = RadioState(
        connection_state="disconnected",
        updated_at=datetime.now(UTC),
    )

    with pytest.raises(ValidationError):
        state.transmitting = True
