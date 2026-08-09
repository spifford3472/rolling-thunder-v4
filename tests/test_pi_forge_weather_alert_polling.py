"""Tests for background-only Pi retained weather-alert polling."""

from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from typing import Any

from rolling_thunder.domain import (
    GPSFixState,
    GPSPosition,
)
from rolling_thunder.forge_weather_alert_client import (
    ForgeRemoteWeatherAlertHealth,
)
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertApplicability,
    WeatherAlertCertainty,
    WeatherAlertProviderStatus,
    WeatherAlertRecord,
    WeatherAlertSeverity,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
    WeatherAlertUrgency,
)
from rolling_thunder.gps import (
    GPSConnectionState,
    GPSState,
    GPSUTCObservation,
    GPSUTCSource,
)
from rolling_thunder.pi_forge_weather_alert_polling import (
    PiForgeWeatherAlertPollingService,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertState,
    PiForgeWeatherAlertStateKind,
)
from rolling_thunder.pi_weather_alert_location_guard import (
    PiWeatherAlertLocationGuard,
)
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.weather_alert_notification_policy import (
    WeatherAlertAudioCue,
    WeatherAlertNotificationController,
)

NOW = datetime(2026, 8, 9, 6, 40, tzinfo=UTC)


class ImmediateExecutor(Executor):
    def submit(
        self,
        fn: Any,
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()

        try:
            future.set_result(
                fn(*args, **kwargs)
            )
        except Exception as error:  # noqa: BLE001
            future.set_exception(error)

        return future

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        del wait, cancel_futures


class ManualScheduledPoll:
    def __init__(
        self,
        callback: PollCallback,
    ) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll


class MemoryLedger:
    def __init__(self) -> None:
        self.claimed: set[str] = set()

    def claim(
        self,
        alert_id: str,
        event: str,
        *,
        claimed_at: datetime,
    ) -> bool:
        del event, claimed_at

        if alert_id in self.claimed:
            return False

        self.claimed.add(alert_id)
        return True


class FakeService:
    def __init__(
        self,
        state: PiForgeWeatherAlertState,
    ) -> None:
        self.state = state
        self.refreshes = 0

    def get_state(
        self,
    ) -> PiForgeWeatherAlertState:
        return self.state

    def refresh(
        self,
    ) -> PiForgeWeatherAlertState:
        self.refreshes += 1
        return self.state


def warning_state() -> PiForgeWeatherAlertState:
    alert = WeatherAlertRecord(
        alert_id="urn:test:tornado-warning",
        event="Tornado Warning",
        severity=WeatherAlertSeverity.EXTREME,
        urgency=WeatherAlertUrgency.IMMEDIATE,
        certainty=WeatherAlertCertainty.OBSERVED,
        headline="Tornado Warning issued",
        area_description="Test Area",
        sent_at=NOW - timedelta(minutes=5),
        effective_at=NOW - timedelta(minutes=5),
        onset_at=NOW - timedelta(minutes=5),
        ends_at=NOW + timedelta(minutes=20),
        expires_at=NOW + timedelta(minutes=30),
    )

    return PiForgeWeatherAlertState(
        kind=PiForgeWeatherAlertStateKind.LIVE,
        snapshot_revision=9,
        snapshot=WeatherAlertSnapshot(
            latitude=39.5245,
            longitude=-84.0625,
            fetched_at=NOW - timedelta(seconds=5),
            alerts=(alert,),
            source=WeatherAlertSourceMetadata(
                provider_id="nws",
                provider_name="National Weather Service",
                attribution_text="National Weather Service alerts",
                attribution_url="https://www.weather.gov/",
            ),
        ),
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.HEALTHY,
            applicability=(
                WeatherAlertApplicability.VERIFIED_CURRENT
            ),
            revision=9,
        ),
        applicability=WeatherAlertApplicability.VERIFIED_CURRENT,
        last_attempt_at=NOW,
        last_success_at=NOW,
    )


def gps_state(
    *,
    trusted: bool = True,
) -> GPSState:
    return GPSState(
        connection_state=GPSConnectionState.CONNECTED,
        position=GPSPosition(
            fix_state=GPSFixState.THREE_DIMENSIONAL,
            latitude=39.5245,
            longitude=-84.0625,
            speed_m_s=0.0,
            accuracy_m=3.0,
            updated_at=NOW,
        ),
        updated_at=NOW,
        utc=GPSUTCObservation(
            value=NOW,
            source=GPSUTCSource.RMC,
            valid=True,
            fix_valid=True,
            advancing=trusted,
            fresh=True,
            age_s=0.0,
            received_monotonic_s=100.0,
        ),
    )


def build_polling(
    service: FakeService,
    *,
    trusted_gps: bool = True,
) -> tuple[
    PiForgeWeatherAlertPollingService,
    ManualScheduler,
    MemoryLedger,
]:
    scheduler = ManualScheduler()
    ledger = MemoryLedger()

    guard = PiWeatherAlertLocationGuard(
        lambda: gps_state(
            trusted=trusted_gps
        ),
        monotonic_clock=lambda: 102.0,
    )

    polling = PiForgeWeatherAlertPollingService(
        service,  # type: ignore[arg-type]
        guard,
        WeatherAlertNotificationController(
            ledger,
            now=lambda: NOW,
        ),
        scheduler,
        interval_s=30.0,
        refresh_on_start=False,
        executor_factory=ImmediateExecutor,
    )

    return polling, scheduler, ledger


def test_poll_refresh_claims_one_event_and_never_replays_poll() -> None:
    service = FakeService(warning_state())
    polling, scheduler, ledger = build_polling(service)

    startup = polling.start()

    assert startup.is_verified_current is True
    assert scheduler.interval_s == 30.0
    assert scheduler.poll is not None
    assert service.refreshes == 0
    assert polling.latest_notification_batch.sequence == 0

    scheduler.poll.callback()

    assert service.refreshes == 1
    batch = polling.latest_notification_batch

    assert batch.sequence == 1
    assert len(batch.decisions) == 1
    assert (
        batch.decisions[0].cue
        is WeatherAlertAudioCue.URGENT
    )
    assert ledger.claimed == {
        "urn:test:tornado-warning"
    }

    scheduler.poll.callback()

    assert service.refreshes == 2
    assert polling.latest_notification_batch.sequence == 1

    polling.stop()

    assert scheduler.poll.cancelled is True


def test_untrusted_local_gps_blocks_notification_claim() -> None:
    service = FakeService(warning_state())
    polling, scheduler, ledger = build_polling(
        service,
        trusted_gps=False,
    )

    polling.start()

    assert scheduler.poll is not None
    scheduler.poll.callback()

    assert polling.latest_state.is_verified_current is False
    assert polling.latest_notification_batch.sequence == 0
    assert ledger.claimed == set()

    polling.stop()


class RecordingAudioPlayer:
    def __init__(
        self,
        *,
        fail: bool = False,
    ) -> None:
        self.fail = fail
        self.cues: list[WeatherAlertAudioCue] = []

    def play(
        self,
        cue: WeatherAlertAudioCue,
    ) -> None:
        from rolling_thunder.weather_alert_audio import (
            WeatherAlertAudioError,
        )

        self.cues.append(cue)

        if self.fail:
            raise WeatherAlertAudioError(
                "test audio device failed"
            )


def test_new_claimed_warning_plays_once_in_background_worker() -> None:
    service = FakeService(warning_state())
    scheduler = ManualScheduler()
    ledger = MemoryLedger()
    audio = RecordingAudioPlayer()

    polling = PiForgeWeatherAlertPollingService(
        service,  # type: ignore[arg-type]
        PiWeatherAlertLocationGuard(
            lambda: gps_state(),
            monotonic_clock=lambda: 102.0,
        ),
        WeatherAlertNotificationController(
            ledger,
            now=lambda: NOW,
        ),
        scheduler,
        interval_s=30.0,
        refresh_on_start=False,
        executor_factory=ImmediateExecutor,
        audio_player=audio,
    )

    polling.start()

    assert scheduler.poll is not None
    scheduler.poll.callback()

    assert audio.cues == [
        WeatherAlertAudioCue.URGENT
    ]

    first_batch = polling.latest_notification_batch
    assert first_batch.sequence == 1
    assert first_batch.audio_error is None

    # Same stable provider alert ID is already durably claimed.
    scheduler.poll.callback()

    assert audio.cues == [
        WeatherAlertAudioCue.URGENT
    ]
    assert polling.latest_notification_batch.sequence == 1

    polling.stop()


def test_audio_failure_isolated_and_not_retried_for_claimed_alert() -> None:
    service = FakeService(warning_state())
    scheduler = ManualScheduler()
    ledger = MemoryLedger()
    audio = RecordingAudioPlayer(
        fail=True,
    )

    polling = PiForgeWeatherAlertPollingService(
        service,  # type: ignore[arg-type]
        PiWeatherAlertLocationGuard(
            lambda: gps_state(),
            monotonic_clock=lambda: 102.0,
        ),
        WeatherAlertNotificationController(
            ledger,
            now=lambda: NOW,
        ),
        scheduler,
        interval_s=30.0,
        refresh_on_start=False,
        executor_factory=ImmediateExecutor,
        audio_player=audio,
    )

    polling.start()

    assert scheduler.poll is not None
    scheduler.poll.callback()

    batch = polling.latest_notification_batch

    assert batch.sequence == 1
    assert batch.audio_error == "test audio device failed"
    assert audio.cues == [
        WeatherAlertAudioCue.URGENT
    ]

    # Claim-before-play deliberately prevents a sound storm.
    scheduler.poll.callback()

    assert audio.cues == [
        WeatherAlertAudioCue.URGENT
    ]
    assert polling.latest_notification_batch.sequence == 1

    polling.stop()
