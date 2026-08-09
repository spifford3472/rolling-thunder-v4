"""Tests for provider-neutral Forge mobile-location validation and publication."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_mobile_location import (
    ForgeMobileLocationService,
    ForgeMobileLocationStorageError,
    InvalidMobileLocationTimingError,
    MobileLocationRecord,
    MobileLocationState,
    StaleMobileLocationError,
)

BASE_TIME = datetime(2026, 8, 8, 23, 30, tzinfo=UTC)


def location(*, seconds: int = 0) -> MobileLocationRecord:
    fix_at = BASE_TIME + timedelta(seconds=seconds)
    return MobileLocationRecord(
        latitude=39.529,
        longitude=-84.064,
        fix_at=fix_at,
        received_at=fix_at + timedelta(seconds=1),
        speed_m_s=22.5,
        heading_degrees=15.0,
    )


class RecordingRepository:
    def __init__(self, stored: MobileLocationState | None = None) -> None:
        self.stored = stored
        self.replacements: list[MobileLocationRecord] = []
        self.replace_error: Exception | None = None

    def load(self) -> MobileLocationState | None:
        return self.stored

    def replace(self, candidate: MobileLocationRecord) -> MobileLocationState:
        self.replacements.append(candidate)
        if self.replace_error is not None:
            raise self.replace_error
        revision = 1 if self.stored is None else self.stored.revision + 1
        self.stored = MobileLocationState(revision=revision, location=candidate)
        return self.stored


def test_record_normalizes_timestamps_to_utc() -> None:
    record = MobileLocationRecord(
        latitude=39.5,
        longitude=-84.1,
        fix_at=datetime.fromisoformat("2026-08-08T19:30:00-04:00"),
        received_at=datetime.fromisoformat("2026-08-08T19:30:01-04:00"),
    )

    assert record.fix_at == datetime(2026, 8, 8, 23, 30, tzinfo=UTC)
    assert record.received_at == datetime(2026, 8, 8, 23, 30, 1, tzinfo=UTC)


def test_record_rejects_impossible_coordinates_motion_and_timing() -> None:
    with pytest.raises(ValidationError):
        MobileLocationRecord(
            latitude=91.0,
            longitude=-84.1,
            fix_at=BASE_TIME,
            received_at=BASE_TIME + timedelta(seconds=1),
        )

    with pytest.raises(ValidationError):
        MobileLocationRecord(
            latitude=39.5,
            longitude=-84.1,
            fix_at=BASE_TIME,
            received_at=BASE_TIME + timedelta(seconds=1),
            speed_m_s=101.0,
        )

    with pytest.raises(ValidationError):
        MobileLocationRecord(
            latitude=39.5,
            longitude=-84.1,
            fix_at=BASE_TIME,
            received_at=BASE_TIME + timedelta(seconds=1),
            heading_degrees=360.0,
        )

    with pytest.raises(ValidationError, match="fix_at must not be later"):
        MobileLocationRecord(
            latitude=39.5,
            longitude=-84.1,
            fix_at=BASE_TIME + timedelta(seconds=2),
            received_at=BASE_TIME,
        )

    with pytest.raises(ValidationError, match="no more than 30 seconds"):
        MobileLocationRecord(
            latitude=39.5,
            longitude=-84.1,
            fix_at=BASE_TIME,
            received_at=BASE_TIME + timedelta(seconds=31),
        )


def test_state_requires_revision_and_location_to_agree() -> None:
    with pytest.raises(ValidationError, match="revision 0"):
        MobileLocationState(revision=0, location=location())

    with pytest.raises(ValidationError, match="positive revision"):
        MobileLocationState(revision=1)


def test_service_persists_before_publishing() -> None:
    repository = RecordingRepository()
    service = ForgeMobileLocationService(
        repository,
        now=lambda: BASE_TIME + timedelta(seconds=5),
    )
    candidate = location()

    state = service.publish(candidate)

    assert repository.replacements == [candidate]
    assert state.revision == 1
    assert state.location == candidate
    assert service.get_state() == state


def test_service_rejects_old_or_future_received_time_before_persistence() -> None:
    repository = RecordingRepository()
    service = ForgeMobileLocationService(
        repository,
        now=lambda: BASE_TIME + timedelta(minutes=5),
    )

    with pytest.raises(InvalidMobileLocationTimingError, match="120 seconds old"):
        service.publish(location())
    assert repository.replacements == []

    future_repository = RecordingRepository()
    future_service = ForgeMobileLocationService(
        future_repository,
        now=lambda: BASE_TIME,
    )
    future = MobileLocationRecord(
        latitude=39.5,
        longitude=-84.1,
        fix_at=BASE_TIME + timedelta(seconds=40),
        received_at=BASE_TIME + timedelta(seconds=40),
    )
    with pytest.raises(InvalidMobileLocationTimingError, match="30 seconds ahead"):
        future_service.publish(future)
    assert future_repository.replacements == []


def test_storage_failure_keeps_prior_location_published() -> None:
    first = location()
    prior = MobileLocationState(revision=4, location=first)
    repository = RecordingRepository(prior)
    repository.replace_error = ForgeMobileLocationStorageError("disk full")
    service = ForgeMobileLocationService(
        repository,
        now=lambda: BASE_TIME + timedelta(seconds=20),
    )

    with pytest.raises(ForgeMobileLocationStorageError, match="disk full"):
        service.publish(location(seconds=10))

    state = service.get_state()
    assert state.revision == 4
    assert state.location == first
    assert state.persistence_error == "disk full"


def test_stale_repository_rejection_keeps_prior_state() -> None:
    first = location()
    prior = MobileLocationState(revision=4, location=first)
    repository = RecordingRepository(prior)
    repository.replace_error = StaleMobileLocationError("not newer")
    service = ForgeMobileLocationService(
        repository,
        now=lambda: BASE_TIME + timedelta(seconds=20),
    )

    with pytest.raises(StaleMobileLocationError, match="not newer"):
        service.publish(location(seconds=10))

    assert service.get_state() == prior
