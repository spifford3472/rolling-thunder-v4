"""Tests for typed offline speech configuration."""

from pathlib import Path

import pytest

from rolling_thunder.config import (
    ApplicationConfig,
    ConfigurationValidationError,
    OperatorConfig,
    SpeechConfig,
    load_config,
)


def write_config(tmp_path: Path, content: str) -> Path:
    """Write a temporary YAML configuration file."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_speech_defaults_are_disabled_and_typed() -> None:
    config = ApplicationConfig(operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm"))

    assert isinstance(config.speech, SpeechConfig)
    assert config.speech.enabled is False
    assert config.speech.audio_device == "default"
    assert config.speech.model_path is None
    assert config.speech.capture_duration_seconds == 8
    assert config.speech.sample_rate == 16_000
    assert config.speech.channels == 1


def test_enabled_speech_loads_and_resolves_relative_model_path(tmp_path: Path) -> None:
    config_dir = tmp_path / "machine"
    config_dir.mkdir()
    path = write_config(
        config_dir,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
speech:
  enabled: true
  audio_device: "  plughw:CARD=J50,DEV=0  "
  model_path: ../models/vosk-small
  capture_duration_seconds: 10
  sample_rate: 16000
  channels: 2
""",
    )

    config = load_config(path)

    assert config.speech.enabled is True
    assert config.speech.audio_device == "plughw:CARD=J50,DEV=0"
    assert config.speech.model_path == (tmp_path / "models/vosk-small").resolve()
    assert config.speech.capture_duration_seconds == 10
    assert config.speech.sample_rate == 16_000
    assert config.speech.channels == 2


def test_absolute_speech_model_path_is_preserved(tmp_path: Path) -> None:
    model_path = tmp_path / "models" / "vosk-small"
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
speech:
  enabled: true
  audio_device: plughw:CARD=J50,DEV=0
  model_path: {model_path}
""",
    )

    config = load_config(path)

    assert config.speech.model_path == model_path


def test_enabled_speech_requires_model_path(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
speech:
  enabled: true
  audio_device: plughw:CARD=J50,DEV=0
""",
    )

    with pytest.raises(ConfigurationValidationError) as error_info:
        load_config(path)

    assert "speech.model_path" in str(error_info.value)
    assert "speech.enabled is true" in str(error_info.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("audio_device", "''"),
        ("model_path", "''"),
        ("model_path", "'.'"),
        ("capture_duration_seconds", "0"),
        ("capture_duration_seconds", "31"),
        ("sample_rate", "7999"),
        ("sample_rate", "48001"),
        ("channels", "0"),
        ("channels", "9"),
    ],
)
def test_invalid_speech_settings_are_actionable(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
speech:
  enabled: false
  {field}: {value}
""",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=rf"speech\.{field}",
    ):
        load_config(path)
