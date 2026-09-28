"""Tests for bounded local weather-alert audio cues."""

import wave
from io import BytesIO

import pytest

from rolling_thunder.weather_alert_audio import (
    AplayWeatherAlertAudioPlayer,
    AudioCommandResult,
    WeatherAlertAudioError,
)
from rolling_thunder.weather_alert_notification_policy import (
    WeatherAlertAudioCue,
)


class RecordingRunner:
    def __init__(
        self,
        result: AudioCommandResult | None = None,
    ) -> None:
        self.result = result or AudioCommandResult(
            return_code=0
        )
        self.calls: list[
            tuple[tuple[str, ...], bytes, float]
        ] = []

    def __call__(
        self,
        command: tuple[str, ...],
        payload: bytes,
        timeout_s: float,
    ) -> AudioCommandResult:
        self.calls.append(
            (command, payload, timeout_s)
        )
        return self.result


def test_aplay_player_generates_valid_wav_without_filesystem() -> None:
    runner = RecordingRunner()
    player = AplayWeatherAlertAudioPlayer(
        audio_device="hw:1,0",
        runner=runner,
    )

    player.play(WeatherAlertAudioCue.URGENT)

    assert len(runner.calls) == 1

    command, payload, timeout_s = runner.calls[0]

    assert command == (
        "aplay",
        "-q",
        "-D",
        "hw:1,0",
        "-t",
        "wav",
        "-",
    )
    assert timeout_s == 5.0
    assert payload.startswith(b"RIFF")

    with wave.open(
        BytesIO(payload),
        "rb",
    ) as wav:
        assert wav.getnchannels() == 1
        assert wav.getsampwidth() == 2
        assert wav.getframerate() == 16_000
        assert wav.getnframes() > 0


def test_required_audio_cues_are_distinct() -> None:
    runner = RecordingRunner()
    player = AplayWeatherAlertAudioPlayer(
        runner=runner,
    )

    player.play(WeatherAlertAudioCue.URGENT)
    player.play(WeatherAlertAudioCue.ATTENTION)
    player.play(WeatherAlertAudioCue.WARNING)

    payloads = [
        payload
        for _command, payload, _timeout_s in runner.calls
    ]

    assert len(payloads) == 3
    assert len(set(payloads)) == 3


def test_silent_cue_does_not_invoke_audio_command() -> None:
    runner = RecordingRunner()
    player = AplayWeatherAlertAudioPlayer(
        runner=runner,
    )

    player.play(WeatherAlertAudioCue.SILENT)

    assert runner.calls == []


def test_aplay_failure_becomes_typed_audio_error() -> None:
    runner = RecordingRunner(
        AudioCommandResult(
            return_code=1,
            stderr="ALSA device unavailable",
        )
    )

    player = AplayWeatherAlertAudioPlayer(
        runner=runner,
    )

    with pytest.raises(
        WeatherAlertAudioError,
        match="ALSA device unavailable",
    ):
        player.play(WeatherAlertAudioCue.WARNING)


def test_blank_audio_device_is_rejected() -> None:
    with pytest.raises(
        ValueError,
        match="must not be blank",
    ):
        AplayWeatherAlertAudioPlayer(
            audio_device="   "
        )
