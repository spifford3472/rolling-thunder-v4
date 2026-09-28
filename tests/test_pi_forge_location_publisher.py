"""Tests for fresh-fix selection and Pi-to-Forge publication policy."""

from __future__ import annotations

from datetime import UTC, datetime

from rolling_thunder.domain import GPSFixState, GPSPosition
from rolling_thunder.forge_location_client import (
    ForgeLocationConnectionError,
    ForgeLocationPublishReceipt,
    ForgeLocationStaleError,
)
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.gps import (
    GPSConnectionState,
    GPSState,
    GPSUTCObservation,
    GPSUTCSource,
)
from rolling_thunder.pi_forge_location_publisher import (
    PiForgeLocationPublisher,
    PiForgeLocationPublishStatus,
)


class RecordingClient:
    def __init__(self) -> None:
        self.locations: list[MobileLocationRecord] = []
        self.failures: list[BaseException] = []

    def publish(self, location: MobileLocationRecord) -> ForgeLocationPublishReceipt:
        self.locations.append(location)
        if self.failures:
            raise self.failures.pop(0)
        return ForgeLocationPublishReceipt(
            api_schema_version="1",
            revision=len(self.locations),
            location=location,
        )


def connected_state(
    *,
    fix_at: datetime,
    received_monotonic_s: float = 100.0,
    trusted: bool = True,
    speed_m_s: float | None = 10.0,
) -> GPSState:
    position = GPSPosition(
        fix_state=GPSFixState.THREE_DIMENSIONAL,
        latitude=39.529,
        longitude=-84.064,
        altitude_m=250.0,
        speed_m_s=speed_m_s,
        heading_degrees=91.0,
        updated_at=fix_at,
    )
    utc = GPSUTCObservation(
        value=fix_at,
        source=GPSUTCSource.RMC,
        valid=True,
        fix_valid=trusted,
        advancing=trusted,
        fresh=trusted,
        age_s=0.5,
        received_monotonic_s=received_monotonic_s,
    )
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=position,
        updated_at=fix_at,
        utc=utc,
    )


def test_valid_fresh_fix_publishes_typed_rmc_utc_and_motion() -> None:
    fix_at = datetime(2026, 8, 9, 0, 20, 0, tzinfo=UTC)
    now = datetime(2026, 8, 9, 0, 20, 1, tzinfo=UTC)
    client = RecordingClient()
    publisher = PiForgeLocationPublisher(
        lambda: connected_state(fix_at=fix_at),
        client,
        clock=lambda: now,
        monotonic_clock=lambda: 100.5,
    )

    state = publisher.publish_latest()

    assert state.status is PiForgeLocationPublishStatus.PUBLISHED
    assert state.attempt_count == 1
    assert state.success_count == 1
    assert state.last_fix_at == fix_at
    assert state.last_revision == 1
    assert state.last_error is None
    assert len(client.locations) == 1
    published = client.locations[0]
    assert published.fix_at == fix_at
    assert published.received_at == now
    assert published.latitude == 39.529
    assert published.longitude == -84.064
    assert published.speed_m_s == 10.0
    assert published.heading_degrees == 91.0


def test_untrusted_or_stale_gps_never_calls_forge() -> None:
    fix_at = datetime(2026, 8, 9, 0, 20, 0, tzinfo=UTC)
    now = datetime(2026, 8, 9, 0, 20, 1, tzinfo=UTC)

    for state, monotonic_value in (
        (connected_state(fix_at=fix_at, trusted=False), 100.5),
        (connected_state(fix_at=fix_at), 106.0),
    ):
        client = RecordingClient()
        publisher = PiForgeLocationPublisher(
            lambda state=state: state,
            client,
            clock=lambda: now,
            monotonic_clock=lambda value=monotonic_value: value,
        )

        result = publisher.publish_latest()

        assert result.status is PiForgeLocationPublishStatus.SKIPPED
        assert result.attempt_count == 0
        assert client.locations == []


def test_no_fix_and_impossible_speed_are_skipped_without_network() -> None:
    fix_at = datetime(2026, 8, 9, 0, 20, 0, tzinfo=UTC)
    now = datetime(2026, 8, 9, 0, 20, 1, tzinfo=UTC)
    no_fix = GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.NO_FIX,
            updated_at=fix_at,
        ),
        updated_at=fix_at,
    )

    for state in (
        no_fix,
        connected_state(fix_at=fix_at, speed_m_s=101.0),
    ):
        client = RecordingClient()
        publisher = PiForgeLocationPublisher(
            lambda state=state: state,
            client,
            clock=lambda: now,
            monotonic_clock=lambda: 100.5,
        )

        result = publisher.publish_latest()

        assert result.status is PiForgeLocationPublishStatus.SKIPPED
        assert client.locations == []


def test_success_consumes_fix_and_prevents_identical_resend() -> None:
    fix_at = datetime(2026, 8, 9, 0, 20, 0, tzinfo=UTC)
    client = RecordingClient()
    publisher = PiForgeLocationPublisher(
        lambda: connected_state(fix_at=fix_at),
        client,
        clock=lambda: datetime(2026, 8, 9, 0, 20, 1, tzinfo=UTC),
        monotonic_clock=lambda: 100.5,
    )

    first = publisher.publish_latest()
    second = publisher.publish_latest()

    assert first.status is PiForgeLocationPublishStatus.PUBLISHED
    assert second.status is PiForgeLocationPublishStatus.SKIPPED
    assert second.attempt_count == 1
    assert len(client.locations) == 1


def test_network_failure_is_retained_but_same_fresh_fix_may_retry() -> None:
    fix_at = datetime(2026, 8, 9, 0, 20, 0, tzinfo=UTC)
    client = RecordingClient()
    client.failures.append(ForgeLocationConnectionError("offline"))
    publisher = PiForgeLocationPublisher(
        lambda: connected_state(fix_at=fix_at),
        client,
        clock=lambda: datetime(2026, 8, 9, 0, 20, 1, tzinfo=UTC),
        monotonic_clock=lambda: 100.5,
    )

    failed = publisher.publish_latest()
    recovered = publisher.publish_latest()

    assert failed.status is PiForgeLocationPublishStatus.FAILED
    assert failed.last_error == "offline"
    assert recovered.status is PiForgeLocationPublishStatus.PUBLISHED
    assert recovered.attempt_count == 2
    assert recovered.success_count == 1
    assert len(client.locations) == 2


def test_stale_rejection_consumes_fix_and_does_not_hammer_forge() -> None:
    fix_at = datetime(2026, 8, 9, 0, 20, 0, tzinfo=UTC)
    client = RecordingClient()
    client.failures.append(ForgeLocationStaleError("already retained"))
    publisher = PiForgeLocationPublisher(
        lambda: connected_state(fix_at=fix_at),
        client,
        clock=lambda: datetime(2026, 8, 9, 0, 20, 1, tzinfo=UTC),
        monotonic_clock=lambda: 100.5,
    )

    rejected = publisher.publish_latest()
    repeated = publisher.publish_latest()

    assert rejected.status is PiForgeLocationPublishStatus.REJECTED
    assert repeated.status is PiForgeLocationPublishStatus.SKIPPED
    assert rejected.attempt_count == 1
    assert repeated.attempt_count == 1
    assert len(client.locations) == 1
