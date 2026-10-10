"""Tests for the experimental FT8 configuration boundary."""

from pathlib import Path

import pytest

from rolling_thunder.config import ConfigurationValidationError, load_config


def _write(tmp_path: Path, extra: str = "") -> Path:
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(
        "operator:\n"
        "  callsign: KI5VNB\n"
        "  home_grid: EM79xm\n"
        f"{extra}",
        encoding="utf-8",
    )
    return path


def test_ft8_defaults_disabled_when_section_is_absent(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path))

    assert config.ft8.enabled is False
    assert config.ft8.receive.audio_device == "plughw:CARD=Device,DEV=0"
    assert config.ft8.receive.decoder_executable is None
    assert config.ft8.receive.diagnostic_session_end_local is None
    assert config.ft8.receive.saved_pcm_periods == 0
    assert config.ft8.qso.attempts_per_state == 6


def test_explicit_ft8_disabled_parses(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, "ft8:\n  enabled: false\n"))

    assert config.ft8.enabled is False


def test_ft8_enabled_requires_decoder_executable(tmp_path: Path) -> None:
    path = _write(tmp_path, "ft8:\n  enabled: true\n")

    with pytest.raises(ConfigurationValidationError, match="decoder_executable"):
        load_config(path)


def test_ft8_enabled_parses_receive_settings(tmp_path: Path) -> None:
    config = load_config(
        _write(
            tmp_path,
            "ft8:\n"
            "  enabled: true\n"
            "  receive:\n"
            "    audio_device: plughw:CARD=Device,DEV=0\n"
            "    decoder_executable: /opt/rolling-thunder/decode_ft8\n"
            "    decoder_timeout_s: 10\n"
            "    reconnect_delay_s: 1\n"
            "  qso:\n"
            "    attempts_per_state: 6\n",
        )
    )

    assert config.ft8.enabled is True
    assert config.ft8.receive.audio_device == "plughw:CARD=Device,DEV=0"
    assert config.ft8.receive.decoder_executable == Path("/opt/rolling-thunder/decode_ft8")
    assert config.ft8.receive.decoder_timeout_s == 10
    assert config.ft8.receive.reconnect_delay_s == 1
    assert config.ft8.qso.attempts_per_state == 6


@pytest.mark.parametrize("attempts", [0, -1, 21])
def test_ft8_retry_count_is_validated(tmp_path: Path, attempts: int) -> None:
    path = _write(
        tmp_path,
        "ft8:\n"
        "  enabled: true\n"
        "  qso:\n"
        f"    attempts_per_state: {attempts}\n",
    )

    with pytest.raises(ConfigurationValidationError, match="ft8.qso.attempts_per_state"):
        load_config(path)


def test_ft8_receive_audio_device_must_not_be_blank(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ft8:\n"
        "  receive:\n"
        "    audio_device: '   '\n",
    )

    with pytest.raises(ConfigurationValidationError, match="ft8.receive.audio_device"):
        load_config(path)


def test_bounded_same_pcm_decoder_comparison_configuration_parses(
    tmp_path: Path,
) -> None:
    config = load_config(
        _write(
            tmp_path,
            "ft8:\n"
            "  enabled: true\n"
            "  receive:\n"
            "    decoder_backend: ft8_lib\n"
            "    decoder_executable: /opt/ft8_lib/decode_ft8\n"
            "    comparison_backend: ft8mon\n"
            "    comparison_decoder_executable: /opt/ft8mon/ft8mon\n"
            "    diagnostic_session_end_local: '05:15'\n"
            "    diagnostic_snapshot_path: /tmp/ft8-diagnostics.json\n"
            "    saved_pcm_directory: /tmp/ft8-pcm\n"
            "    saved_pcm_periods: 3\n",
        )
    )

    assert str(config.ft8.receive.diagnostic_session_end_local) == "05:15:00"
    assert config.ft8.receive.saved_pcm_periods == 3


def test_comparison_decoder_requires_bounded_session_end(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "ft8:\n"
        "  receive:\n"
        "    comparison_backend: ft8mon\n"
        "    comparison_decoder_executable: /opt/ft8mon/ft8mon\n",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match="diagnostic_session_end_local",
    ):
        load_config(path)
