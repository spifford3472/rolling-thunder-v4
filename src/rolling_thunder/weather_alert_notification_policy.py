"""Pure weather-alert audible policy plus durable claim controller."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol

from pydantic import Field, field_validator

from rolling_thunder.domain import DomainModel
from rolling_thunder.forge_weather_alerts import (
    WeatherAlertRecord,
)
from rolling_thunder.pi_forge_weather_alert_service import (
    PiForgeWeatherAlertState,
)
from rolling_thunder.storage import StorageError

Clock = Callable[[], datetime]
_MAX_ERROR_LENGTH = 500


class WeatherAlertAudioCue(StrEnum):
    """Provider-neutral sound priority requested from the future audio layer."""

    URGENT = "urgent"
    ATTENTION = "attention"
    WARNING = "warning"
    SILENT = "silent"


class WeatherAlertNotificationDecision(DomainModel):
    """One durably claimed alert eligible for future audio playback."""

    alert_id: str = Field(min_length=1, max_length=512)
    event: str = Field(min_length=1, max_length=160)
    cue: WeatherAlertAudioCue


class WeatherAlertNotificationEvaluation(DomainModel):
    """Result of evaluating one immutable Pi alert state."""

    decisions: tuple[WeatherAlertNotificationDecision, ...] = ()
    persistence_error: str | None = Field(
        default=None,
        max_length=_MAX_ERROR_LENGTH,
    )

    @field_validator("persistence_error")
    @classmethod
    def normalize_error(
        cls,
        value: str | None,
    ) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        return normalized[:_MAX_ERROR_LENGTH] or None


class WeatherAlertNotificationLedger(Protocol):
    """Durable once-per-provider-ID claim boundary."""

    def claim(
        self,
        alert_id: str,
        event: str,
        *,
        claimed_at: datetime,
    ) -> bool:
        """Return True only for the first durable claim."""
        ...


def audio_cue_for_alert(
    alert: WeatherAlertRecord,
) -> WeatherAlertAudioCue:
    """Map a normalized weather event to Rolling Thunder audio policy."""
    event = " ".join(alert.event.split()).casefold()

    if event in {
        "tornado warning",
        "severe thunderstorm warning",
        "flash flood warning",
    }:
        return WeatherAlertAudioCue.URGENT

    if event in {
        "tornado watch",
        "severe thunderstorm watch",
    }:
        return WeatherAlertAudioCue.ATTENTION

    if event.endswith(" warning"):
        return WeatherAlertAudioCue.WARNING

    # Advisories, statements, outlooks, and other informational
    # products remain visible but silent by default.
    return WeatherAlertAudioCue.SILENT


class WeatherAlertNotificationController:
    """Claim new verified-current audible alerts exactly once."""

    def __init__(
        self,
        ledger: WeatherAlertNotificationLedger,
        *,
        now: Clock | None = None,
    ) -> None:
        self._ledger = ledger
        self._now = now or (lambda: datetime.now(UTC))

    def evaluate(
        self,
        state: PiForgeWeatherAlertState,
    ) -> WeatherAlertNotificationEvaluation:
        """Return newly claimed audible decisions for one published state."""
        if not state.is_verified_current or state.snapshot is None:
            return WeatherAlertNotificationEvaluation()

        now = self._aware_now()
        decisions: list[WeatherAlertNotificationDecision] = []

        for alert in state.snapshot.alerts:
            if not self._is_active(alert, now):
                continue

            cue = audio_cue_for_alert(alert)

            if cue is WeatherAlertAudioCue.SILENT:
                continue

            try:
                claimed = self._ledger.claim(
                    alert.alert_id,
                    alert.event,
                    claimed_at=now,
                )
            except StorageError as error:
                return WeatherAlertNotificationEvaluation(
                    decisions=tuple(decisions),
                    persistence_error=self._bounded_error(error),
                )

            if not claimed:
                continue

            decisions.append(
                WeatherAlertNotificationDecision(
                    alert_id=alert.alert_id,
                    event=alert.event,
                    cue=cue,
                )
            )

        return WeatherAlertNotificationEvaluation(
            decisions=tuple(decisions),
        )

    @staticmethod
    def _is_active(
        alert: WeatherAlertRecord,
        now: datetime,
    ) -> bool:
        if alert.effective_at > now:
            return False

        if alert.expires_at <= now:
            return False

        return alert.ends_at is None or alert.ends_at > now

    def _aware_now(self) -> datetime:
        value = self._now()

        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError(
                "Weather-alert notification clock must be timezone-aware"
            )

        return value.astimezone(UTC)

    @staticmethod
    def _bounded_error(error: BaseException) -> str:
        text = str(error).strip() or error.__class__.__name__
        return text[:_MAX_ERROR_LENGTH]
