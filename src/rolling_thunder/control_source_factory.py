"""Application composition for configured physical-control sources."""

from collections.abc import Callable

from rolling_thunder.config import (
    PhysicalControlsConfig,
    PhysicalControlTransport,
)
from rolling_thunder.physical_controls import ControlSource, MockControlSource
from rolling_thunder.serial_control_source import SerialControlSource

SerialSourceFactory = Callable[[PhysicalControlsConfig], SerialControlSource]


def _build_serial_source(config: PhysicalControlsConfig) -> SerialControlSource:
    """Construct one serial source from validated physical-control settings."""
    device = config.device
    if device is None:
        raise ValueError(
            "physical_controls.device must be configured for the serial transport"
        )
    return SerialControlSource(
        device,
        baud_rate=config.baud_rate,
        maximum_line_bytes=config.maximum_line_bytes,
        maximum_read_bytes=config.maximum_read_bytes,
        maximum_events_per_drain=config.maximum_events_per_drain,
    )


def build_control_source(
    config: PhysicalControlsConfig,
    *,
    serial_source_factory: SerialSourceFactory = _build_serial_source,
) -> ControlSource:
    """Build the configured transport without performing device I/O."""
    if config.transport is PhysicalControlTransport.MOCK:
        return MockControlSource()
    if config.transport is PhysicalControlTransport.SERIAL:
        return serial_source_factory(config)
    raise ValueError(f"Unsupported physical-control transport {config.transport!r}.")
