"""Tests for severe-weather audible eligibility and durable dedupe."""

from datetime import UTC, datetime, timedelta

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
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertState,
    PiForgeWeatherAlertStateKind,
)
from rolling_thunder.weather_alert_notification_policy import (
    WeatherAlertAudioCue,
    WeatherAlertNotificationController,
    audio_cue_for_alert,
)

NOW = datetime(2026, 8, 9, 6, 30, tzinfo=UTC)


def alert(
    event: str,
    *,
    alert_id: str | None = None,
    expires_delta: timedelta = timedelta(minutes=30),
) -> WeatherAlertRecord:
    return WeatherAlertRecord(
        alert_id=alert_id or f"urn:test:{event.casefold().replace(' ', '-')}",
        event=event,
        severity=WeatherAlertSeverity.SEVERE,
        urgency=WeatherAlertUrgency.IMMEDIATE,
        certainty=WeatherAlertCertainty.LIKELY,
        headline=f"{event} issued for test area",
        area_description="Test Area",
        sent_at=NOW - timedelta(minutes=5),
        effective_at=NOW - timedelta(minutes=5),
        onset_at=NOW - timedelta(minutes=5),
        ends_at=NOW + expires_delta,
        expires_at=NOW + expires_delta,
    )


def state(
    *alerts: WeatherAlertRecord,
    applicability: WeatherAlertApplicability = (
        WeatherAlertApplicability.VERIFIED_CURRENT
    ),
    kind: PiForgeWeatherAlertStateKind = (
        PiForgeWeatherAlertStateKind.LIVE
    ),
) -> PiForgeWeatherAlertState:
    snapshot = WeatherAlertSnapshot(
        latitude=39.5245,
        longitude=-84.0625,
        fetched_at=NOW,
        alerts=alerts,
        source=WeatherAlertSourceMetadata(
            provider_id="nws",
            provider_name="National Weather Service",
            attribution_text="National Weather Service alerts",
            attribution_url="https://www.weather.gov/",
        ),
    )

    return PiForgeWeatherAlertState(
        kind=kind,
        snapshot_revision=8,
        snapshot=snapshot,
        health=ForgeRemoteWeatherAlertHealth(
            status=WeatherAlertProviderStatus.HEALTHY,
            applicability=applicability,
            revision=8,
        ),
        applicability=applicability,
        last_attempt_at=NOW,
        last_success_at=NOW,
    )


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


def test_audio_policy_maps_required_events() -> None:
    assert (
        audio_cue_for_alert(alert("Tornado Warning"))
        is WeatherAlertAudioCue.URGENT
    )
    assert (
        audio_cue_for_alert(alert("Severe Thunderstorm Warning"))
        is WeatherAlertAudioCue.URGENT
    )
    assert (
        audio_cue_for_alert(alert("Flash Flood Warning"))
        is WeatherAlertAudioCue.URGENT
    )
    assert (
        audio_cue_for_alert(alert("Tornado Watch"))
        is WeatherAlertAudioCue.ATTENTION
    )
    assert (
        audio_cue_for_alert(alert("Severe Thunderstorm Watch"))
        is WeatherAlertAudioCue.ATTENTION
    )
    assert (
        audio_cue_for_alert(alert("Winter Storm Warning"))
        is WeatherAlertAudioCue.WARNING
    )
    assert (
        audio_cue_for_alert(alert("Wind Advisory"))
        is WeatherAlertAudioCue.SILENT
    )


def test_verified_new_warning_is_claimed_once() -> None:
    ledger = MemoryLedger()
    controller = WeatherAlertNotificationController(
        ledger,
        now=lambda: NOW,
    )
    warning = alert("Tornado Warning")

    first = controller.evaluate(state(warning))
    second = controller.evaluate(state(warning))

    assert len(first.decisions) == 1
    assert first.decisions[0].cue is WeatherAlertAudioCue.URGENT
    assert second.decisions == ()


def test_retained_or_unverified_state_cannot_create_sound_claim() -> None:
    ledger = MemoryLedger()
    controller = WeatherAlertNotificationController(
        ledger,
        now=lambda: NOW,
    )
    warning = alert("Tornado Warning")

    retained = state(
        warning,
        applicability=WeatherAlertApplicability.RETAINED_UNVERIFIED,
        kind=PiForgeWeatherAlertStateKind.RETAINED,
    )

    evaluation = controller.evaluate(retained)

    assert evaluation.decisions == ()
    assert ledger.claimed == set()


def test_advisory_is_visible_but_never_claimed_for_audio() -> None:
    ledger = MemoryLedger()
    controller = WeatherAlertNotificationController(
        ledger,
        now=lambda: NOW,
    )
    advisory = alert("Wind Advisory")

    evaluation = controller.evaluate(state(advisory))

    assert evaluation.decisions == ()
    assert ledger.claimed == set()


def test_expired_alert_is_not_claimed() -> None:
    ledger = MemoryLedger()
    controller = WeatherAlertNotificationController(
        ledger,
        now=lambda: NOW,
    )

    expired = alert(
        "Flash Flood Warning",
        expires_delta=timedelta(seconds=-1),
    )

    evaluation = controller.evaluate(state(expired))

    assert evaluation.decisions == ()
    assert ledger.claimed == set()


def test_entering_existing_alert_area_claims_when_first_relevant() -> None:
    ledger = MemoryLedger()
    controller = WeatherAlertNotificationController(
        ledger,
        now=lambda: NOW,
    )
    warning = alert(
        "Severe Thunderstorm Warning",
        alert_id="urn:test:existing-warning",
    )

    # Outside the affected point: Forge returns a verified empty set.
    outside = controller.evaluate(state())

    # Entering the alert point: same active provider alert now appears.
    entered = controller.evaluate(state(warning))

    assert outside.decisions == ()
    assert len(entered.decisions) == 1

    # Polling it again cannot replay it.
    repeated = controller.evaluate(state(warning))
    assert repeated.decisions == ()
