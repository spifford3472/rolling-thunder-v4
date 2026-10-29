"""Application composition for configured physical-control sources."""

from collections.abc import Callable

from rolling_thunder.config import (
    PhysicalControlsConfig,
    PhysicalControlTransport,
)
from rolling_thunder.control_recovery_gate import RecoveryControlEventGate
from rolling_thunder.physical_controls import (
    ControlEventFilter,
    ControlEventGate,
    ControlSource,
    MockControlSource,
)
from rolling_thunder.recovering_control_source import RecoveringControlSource
from rolling_thunder.serial_control_source import SerialControlSource

SerialSourceFactory = Callable[[PhysicalControlsConfig], SerialControlSource]


def _build_serial_source(config: PhysicalControlsConfig) -> SerialControlSource:
    """Construct one serial source from validated physical-control settings."""
    device = config.device
    if device is None:
        raise ValueError("physical_controls.device must be configured for the serial transport")
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
    if config.transport is PhysicalControlTransport.SERIAL_V2:
        if config.device is None:
            raise ValueError("physical_controls.device is required for serial_v2")
        return RecoveringControlSource(
            config.device,
            frozenset(config.mappings),
            baud_rate=config.baud_rate,
            capacity=config.maximum_events_per_drain,
            settle_s=config.recovery_settle_s,
        )
    raise ValueError(f"Unsupported physical-control transport {config.transport!r}.")


def build_control_gate(config: PhysicalControlsConfig, source: ControlSource) -> ControlEventFilter:
    """Keep legacy semantics; v2 uses only bounded current-session gating."""
    if isinstance(source, RecoveringControlSource):
        return RecoveryControlEventGate(
            frozenset(config.mappings),
            lambda: source.snapshot.session_nonce,
            config.repeat_suppression_s,
        )
    return ControlEventGate(config.repeat_suppression_s)
