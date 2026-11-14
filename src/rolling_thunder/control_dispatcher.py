"""Dispatch validated physical-control events through shared operator commands."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Protocol

from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlEventFilter,
    ControlInputEvent,
    ControlSource,
)


class OperatorCommands(Protocol):
    """Approved application command boundary used by physical controls."""

    def execute(self, action: ControlAction) -> bool:
        """Execute one approved action and report whether it was accepted."""


class EventAwareInterceptor(Protocol):
    """Narrow consumer for commands that require validated event identity."""

    def intercept(self, event: ControlInputEvent, action: ControlAction) -> bool | None:
        """Return None for default dispatch, otherwise consume with this result."""


class CompositeEventInterceptor:
    """Run ordered interceptors until one consumes a physical input."""

    def __init__(self, *interceptors: EventAwareInterceptor | None) -> None:
        self._interceptors = tuple(
            interceptor for interceptor in interceptors if interceptor is not None
        )

    def intercept(self, event: ControlInputEvent, action: ControlAction) -> bool | None:
        for interceptor in self._interceptors:
            result = interceptor.intercept(event, action)
            if result is not None:
                return result
        return None


@dataclass(frozen=True)
class ControlDispatchResult:
    """Summary of one nonblocking physical-control drain cycle."""

    drained: int = 0
    accepted: int = 0
    rejected: int = 0
    unknown: int = 0


class ControlDispatcher:
    """Map and safely dispatch currently available physical-control events."""

    def __init__(
        self,
        source: ControlSource,
        mapper: ControlActionMapper,
        gate: ControlEventFilter,
        commands: OperatorCommands,
        *,
        action_observer: Callable[[str, float], None] | None = None,
        clock: Callable[[], float] = monotonic,
        event_interceptor: EventAwareInterceptor | None = None,
        dispatch_blocked: Callable[[], bool] | None = None,
    ) -> None:
        self._source = source
        self._mapper = mapper
        self._gate = gate
        self._commands = commands
        self._action_observer = action_observer
        self._clock = clock
        self._event_interceptor = event_interceptor
        self._dispatch_blocked = dispatch_blocked or (lambda: False)

    def dispatch_available(self) -> ControlDispatchResult:
        """Drain available events without blocking and dispatch safe actions."""
        events = self._source.drain()
        if self._dispatch_blocked():
            # Drain stale controller input without invoking any interceptor or
            # command after shutdown has revoked application authority.
            return ControlDispatchResult(
                drained=len(events), accepted=0, rejected=len(events), unknown=0,
            )
        accepted = 0
        rejected = 0
        unknown = 0

        for event in events:
            if not self._gate.accept(event):
                rejected += 1
                continue

            action = self._mapper.resolve(event)
            if action is None:
                unknown += 1
                continue

            started = self._clock() if self._action_observer is not None else 0.0
            intercepted = (
                None
                if self._event_interceptor is None
                else self._event_interceptor.intercept(event, action)
            )
            command_accepted = (
                self._commands.execute(action) if intercepted is None else intercepted
            )
            if command_accepted:
                accepted += 1
                if self._action_observer is not None:
                    self._action_observer(
                        action.value,
                        max(0.0, (self._clock() - started) * 1000.0),
                    )
            else:
                rejected += 1

        return ControlDispatchResult(
            drained=len(events),
            accepted=accepted,
            rejected=rejected,
            unknown=unknown,
        )
