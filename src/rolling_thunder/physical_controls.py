"""Transport-independent physical-control primitives and deterministic mocks."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from typing import Protocol


class ControlAction(StrEnum):
    """Application actions that may be requested by a physical control."""

    VOICE = "voice"
    COMMIT = "commit"
    DISCARD = "discard"
    SELECT_POTA = "select_pota"
    SELECT_DX = "select_dx"
    SELECT_REPEATERS = "select_repeaters"
    SELECT_AI = "select_ai"
    SELECT_SETTINGS = "select_settings"


@dataclass(frozen=True)
class ControlInputEvent:
    """One immutable input event reported by a control transport."""

    input_id: str
    event_id: str
    occurred_at_s: float

    def __post_init__(self) -> None:
        if not self.input_id.strip():
            raise ValueError("Control input_id must not be blank.")
        if not self.event_id.strip():
            raise ValueError("Control event_id must not be blank.")
        if self.occurred_at_s < 0:
            raise ValueError("Control occurred_at_s must not be negative.")


class ControlSource(Protocol):
    """Nonblocking source of transport-independent control input events."""

    def drain(self) -> tuple[ControlInputEvent, ...]:
        """Return all currently available events without blocking."""


class ControlMappingError(ValueError):
    """Raised when physical-control mappings are malformed or ambiguous."""


class ControlActionMapper:
    """Resolve configured input identifiers to typed application actions."""

    def __init__(self, mappings: Mapping[str, ControlAction]) -> None:
        normalized: dict[str, ControlAction] = {}
        for raw_input_id, action in mappings.items():
            input_id = raw_input_id.strip()
            if not input_id:
                raise ControlMappingError(
                    "Control mapping input identifiers must not be blank."
                )
            if input_id in normalized:
                raise ControlMappingError(
                    f"Duplicate control mapping for input identifier {input_id!r}."
                )
            normalized[input_id] = action
        self._mappings = normalized

    def resolve(self, event: ControlInputEvent) -> ControlAction | None:
        """Return the configured action, or None for an unknown input."""
        return self._mappings.get(event.input_id.strip())


class ControlEventGate:
    """Reject duplicate, stale, and rapidly repeated physical-control events."""

    def __init__(self, repeat_suppression_s: float) -> None:
        if repeat_suppression_s < 0:
            raise ValueError("Control repeat_suppression_s must not be negative.")
        self._repeat_suppression_s = repeat_suppression_s
        self._seen_event_ids: set[str] = set()
        self._last_accepted_at_by_input: dict[str, float] = {}
        self._lock = Lock()

    def accept(self, event: ControlInputEvent) -> bool:
        """Return true only when an event is safe to dispatch once."""
        input_id = event.input_id.strip()
        event_id = event.event_id.strip()

        with self._lock:
            if event_id in self._seen_event_ids:
                return False
            self._seen_event_ids.add(event_id)

            last_accepted_at = self._last_accepted_at_by_input.get(input_id)
            if last_accepted_at is not None:
                elapsed_s = event.occurred_at_s - last_accepted_at
                if elapsed_s < 0 or elapsed_s < self._repeat_suppression_s:
                    return False

            self._last_accepted_at_by_input[input_id] = event.occurred_at_s
            return True


class MockControlSource:
    """Deterministic inert control source for tests and development."""

    def __init__(self, events: tuple[ControlInputEvent, ...] = ()) -> None:
        self._events = deque(events)
        self._lock = Lock()

    def emit(self, event: ControlInputEvent) -> None:
        """Explicitly queue one event; no event is generated automatically."""
        with self._lock:
            self._events.append(event)

    def drain(self) -> tuple[ControlInputEvent, ...]:
        """Return queued events in FIFO order without waiting for hardware."""
        with self._lock:
            events = tuple(self._events)
            self._events.clear()
        return events
