"""Tests for confirmed background repeater Active persistence."""

from collections.abc import Callable
from decimal import Decimal

from rolling_thunder.domain import Frequency
from rolling_thunder.repeater_active_override_controller import (
    RepeaterActiveOverrideController,
)
from rolling_thunder.repeater_domain import (
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)
from rolling_thunder.repeater_nearby import NearbyRepeater
from rolling_thunder.repeater_panel import StagedRepeaterActiveAction
from rolling_thunder.storage import StorageError


class RecordingRepository:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.writes: list[tuple[str, bool]] = []

    def write(self, identity: RepeaterIdentity, active: bool) -> None:
        self.writes.append((identity.stable_key, active))
        if self.fail:
            raise StorageError("disk unavailable")


def action(*, active: bool = True) -> StagedRepeaterActiveAction:
    rx = Frequency(hz=52_010_000)
    record = RepeaterRecord(
        identity=RepeaterIdentity(name="K1AAA Alpha", rx_frequency=rx),
        name="K1AAA Alpha",
        callsign="K1AAA",
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=51_010_000),
        bandwidth_khz=Decimal(25),
        rx_tone_hz=Decimal("100.0"),
        tx_tone_hz=Decimal("100.0"),
        location=RepeaterLocation(latitude=39.5, longitude=-84.0),
        source_active=True,
    )
    return StagedRepeaterActiveAction.from_nearby(
        NearbyRepeater(record, distance_miles=5.0, effective_active=active)
    )


def test_confirmed_action_is_written_exactly_once_and_published() -> None:
    repository = RecordingRepository()
    controller = RepeaterActiveOverrideController(
        repository,
        worker_launcher=lambda worker: worker(),
    )
    staged = action(active=True)

    assert controller.start_persist(staged) is True

    assert repository.writes == [(staged.stable_key, False)]
    status = controller.status
    assert status.saving is False
    assert status.last_completed_action == staged
    assert status.completion_revision == 1
    assert status.last_error is None


def test_persistence_failure_is_explicit_and_does_not_claim_completion() -> None:
    repository = RecordingRepository(fail=True)
    controller = RepeaterActiveOverrideController(
        repository,
        worker_launcher=lambda worker: worker(),
    )
    staged = action(active=False)

    assert controller.start_persist(staged) is True

    status = controller.status
    assert repository.writes == [(staged.stable_key, True)]
    assert status.last_completed_action is None
    assert status.completion_revision == 0
    assert status.last_error == "disk unavailable"


def test_busy_controller_rejects_ambiguous_second_submission() -> None:
    repository = RecordingRepository()
    queued: list[Callable[[], None]] = []

    def queue(worker: Callable[[], None]) -> None:
        queued.append(worker)

    controller = RepeaterActiveOverrideController(
        repository,
        worker_launcher=queue,
    )
    first = action(active=True)
    second = action(active=False)

    assert controller.start_persist(first) is True
    assert controller.status.saving is True
    assert controller.start_persist(second) is False
    assert repository.writes == []
    assert len(queued) == 1
