"""Tests for physical-control source application composition."""

from pathlib import Path

import pytest

from rolling_thunder.config import (
    PhysicalControlsConfig,
    PhysicalControlTransport,
)
from rolling_thunder.control_source_factory import build_control_source
from rolling_thunder.physical_controls import MockControlSource
from rolling_thunder.serial_control_source import SerialControlSource


def test_mock_transport_builds_inert_mock_source() -> None:
    source = build_control_source(PhysicalControlsConfig())

    assert isinstance(source, MockControlSource)
    assert source.drain() == ()


def test_serial_transport_delegates_validated_configuration() -> None:
    config = PhysicalControlsConfig(
        enabled=True,
        transport=PhysicalControlTransport.SERIAL,
        device=Path("/dev/ttyACM7"),
        baud_rate=230_400,
        maximum_line_bytes=512,
        maximum_read_bytes=8_192,
        maximum_events_per_drain=64,
    )
    received: list[PhysicalControlsConfig] = []
    expected = SerialControlSource(Path("/dev/ttyACM9"))

    source = build_control_source(
        config,
        serial_source_factory=lambda supplied: received.append(supplied) or expected,
    )

    assert source is expected
    assert received == [config]
    assert expected.is_connected is False


def test_factory_does_not_open_serial_source() -> None:
    config = PhysicalControlsConfig(
        enabled=True,
        transport=PhysicalControlTransport.SERIAL,
        device=Path("/dev/ttyACM0"),
    )
    source = build_control_source(config)

    assert isinstance(source, SerialControlSource)
    assert source.is_connected is False


def test_missing_serial_device_is_defensively_rejected() -> None:
    config = PhysicalControlsConfig(
        enabled=False,
        transport=PhysicalControlTransport.SERIAL,
    )

    with pytest.raises(ValueError, match="device must be configured"):
        build_control_source(config)
