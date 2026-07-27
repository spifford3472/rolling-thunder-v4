"""Tests for typed physical-control transport configuration."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.config import (
    PhysicalControlsConfig,
    PhysicalControlTransport,
)


def test_physical_controls_default_to_inert_mock_transport() -> None:
    config = PhysicalControlsConfig()

    assert config.enabled is False
    assert config.transport is PhysicalControlTransport.MOCK
    assert config.device is None
    assert config.baud_rate == 115_200
    assert config.maximum_line_bytes == 256
    assert config.maximum_read_bytes == 4_096
    assert config.maximum_events_per_drain == 32


def test_enabled_mock_transport_does_not_require_device() -> None:
    config = PhysicalControlsConfig(enabled=True)

    assert config.transport is PhysicalControlTransport.MOCK
    assert config.device is None


def test_enabled_serial_transport_requires_device() -> None:
    with pytest.raises(
        ValidationError,
        match="physical_controls.device must be configured",
    ):
        PhysicalControlsConfig(
            enabled=True,
            transport=PhysicalControlTransport.SERIAL,
        )


def test_enabled_serial_transport_accepts_absolute_device() -> None:
    config = PhysicalControlsConfig(
        enabled=True,
        transport=PhysicalControlTransport.SERIAL,
        device=Path("/dev/ttyACM0"),
        baud_rate=230_400,
        maximum_line_bytes=512,
        maximum_read_bytes=8_192,
        maximum_events_per_drain=64,
    )

    assert config.device == Path("/dev/ttyACM0")
    assert config.baud_rate == 230_400
    assert config.maximum_line_bytes == 512
    assert config.maximum_read_bytes == 8_192
    assert config.maximum_events_per_drain == 64


def test_disabled_serial_transport_may_omit_device() -> None:
    config = PhysicalControlsConfig(
        enabled=False,
        transport=PhysicalControlTransport.SERIAL,
    )

    assert config.device is None


@pytest.mark.parametrize("device", ["", "   ", "ttyACM0", Path("ttyUSB0")])
def test_invalid_serial_device_path_is_rejected(device: str | Path) -> None:
    with pytest.raises(ValidationError):
        PhysicalControlsConfig(device=device)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("baud_rate", 0),
        ("maximum_line_bytes", 31),
        ("maximum_read_bytes", 0),
        ("maximum_events_per_drain", 0),
    ],
)
def test_invalid_serial_limits_are_rejected(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        PhysicalControlsConfig(**{field: value})
