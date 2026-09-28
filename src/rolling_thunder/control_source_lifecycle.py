"""Lifecycle helpers for optional physical-control transports."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from rolling_thunder.physical_controls import ControlSource
from rolling_thunder.serial_control_source import SerialControlError


@runtime_checkable
class LifecycleControlSource(Protocol):
    """Control source with explicit transport startup and shutdown."""

    def open(self) -> None:
        """Open the underlying transport."""

    def close(self) -> None:
        """Close the underlying transport."""


def open_control_source(source: ControlSource) -> str | None:
    """Open a lifecycle-managed source and return an actionable error if unavailable."""
    if not isinstance(source, LifecycleControlSource):
        return None
    try:
        source.open()
    except SerialControlError as error:
        return str(error)
    return None


def close_control_source(source: ControlSource | None) -> str | None:
    """Close a lifecycle-managed source and return an actionable error if needed."""
    if source is None or not isinstance(source, LifecycleControlSource):
        return None
    try:
        source.close()
    except SerialControlError as error:
        return str(error)
    return None
