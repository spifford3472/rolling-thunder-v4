"""Tests for typed physical-control YAML configuration."""

from pathlib import Path

import pytest

from rolling_thunder.config import (
    ApplicationConfig,
    ConfigurationValidationError,
    OperatorConfig,
    PhysicalControlsConfig,
    load_config,
)
from rolling_thunder.physical_controls import ControlAction


def write_config(tmp_path: Path, physical_controls: str = "") -> Path:
    """Write one minimal configuration with optional physical-control YAML."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(
        "operator:\n"
        "  callsign: KI5VNB\n"
        "  home_grid: EM79xm\n"
        f"{physical_controls}",
        encoding="utf-8",
    )
    return path


def test_physical_controls_have_safe_disabled_defaults() -> None:
    """Application configuration should not enable controls implicitly."""
    config = ApplicationConfig(
        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")
    )

    assert isinstance(config.physical_controls, PhysicalControlsConfig)
    assert config.physical_controls.enabled is False
    assert config.physical_controls.repeat_suppression_s == 0.25
    assert config.physical_controls.mappings == {}


def test_yaml_loads_typed_control_mappings(tmp_path: Path) -> None:
    """Opaque input identifiers should load as typed approved actions."""
    path = write_config(
        tmp_path,
        "physical_controls:\n"
        "  enabled: true\n"
        "  repeat_suppression_s: 0.4\n"
        "  mappings:\n"
        "    voice-button: voice\n"
        "    commit-button: commit\n"
        "    context-pota-button: select_pota\n",
    )

    config = load_config(path)

    assert config.physical_controls.enabled is True
    assert config.physical_controls.repeat_suppression_s == 0.4
    assert config.physical_controls.mappings == {
        "voice-button": ControlAction.VOICE,
        "commit-button": ControlAction.COMMIT,
        "context-pota-button": ControlAction.SELECT_POTA,
    }


def test_mapping_identifiers_are_trimmed(tmp_path: Path) -> None:
    """Configuration should normalize harmless surrounding whitespace."""
    path = write_config(
        tmp_path,
        "physical_controls:\n"
        "  mappings:\n"
        "    ' voice-button ': voice\n",
    )

    config = load_config(path)

    assert config.physical_controls.mappings == {
        "voice-button": ControlAction.VOICE,
    }


@pytest.mark.parametrize("value", [-0.1, 5.1])
def test_repeat_suppression_range_is_actionable(
    tmp_path: Path,
    value: float,
) -> None:
    """Unsafe suppression settings should identify their configuration path."""
    path = write_config(
        tmp_path,
        "physical_controls:\n"
        f"  repeat_suppression_s: {value}\n",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"physical_controls\.repeat_suppression_s",
    ):
        load_config(path)


def test_unknown_control_action_is_rejected(tmp_path: Path) -> None:
    """Configuration must not invent radio or tuning authority."""
    path = write_config(
        tmp_path,
        "physical_controls:\n"
        "  mappings:\n"
        "    dangerous-button: ptt\n",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"physical_controls\.mappings\.dangerous-button",
    ):
        load_config(path)


def test_blank_mapping_identifier_is_rejected(tmp_path: Path) -> None:
    """Blank hardware identifiers should fail safely."""
    path = write_config(
        tmp_path,
        "physical_controls:\n"
        "  mappings:\n"
        "    ' ': discard\n",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"physical_controls\.mappings",
    ):
        load_config(path)


def test_normalized_duplicate_mapping_is_rejected(tmp_path: Path) -> None:
    """Two keys resolving to one input identifier should be ambiguous."""
    path = write_config(
        tmp_path,
        "physical_controls:\n"
        "  mappings:\n"
        "    voice-button: voice\n"
        "    ' voice-button ': commit\n",
    )

    with pytest.raises(
        ConfigurationValidationError,
        match=r"physical_controls\.mappings",
    ):
        load_config(path)
