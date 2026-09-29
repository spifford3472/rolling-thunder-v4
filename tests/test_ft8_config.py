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
    assert config.ft8.qso.attempts_per_state == 6


def test_explicit_ft8_disabled_parses(tmp_path: Path) -> None:
    config = load_config(_write(tmp_path, "ft8:\n  enabled: false\n"))

    assert config.ft8.enabled is False


def test_ft8_enabled_parses_without_hardware_settings(tmp_path: Path) -> None:
    config = load_config(
        _write(
            tmp_path,
            "ft8:\n"
            "  enabled: true\n"
            "  qso:\n"
            "    attempts_per_state: 6\n",
        )
    )

    assert config.ft8.enabled is True
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
