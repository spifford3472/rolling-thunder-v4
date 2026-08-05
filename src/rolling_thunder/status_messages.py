"""Thread-safe arbitration for operator status messages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from threading import RLock
from time import monotonic

MonotonicClock = Callable[[], float]


class StatusPresentation(StrEnum):
    """Presentation tokens understood by status-message renderers."""

    NORMAL = "normal"
    AMBER = "amber"
    SUCCESS = "success"
    ERROR = "error"
    MUTED = "muted"


@dataclass(frozen=True, slots=True)
class StatusMessage:
    """One immutable status message retained by replacement key."""

    replacement_key: str
    text: str
    presentation: StatusPresentation
    priority: int
    sequence: int
    created_at_monotonic: float
    expires_at_monotonic: float | None

    def is_expired(self, now_monotonic: float) -> bool:
        """Return whether this message has reached its expiration deadline."""
        deadline = self.expires_at_monotonic
        return deadline is not None and now_monotonic >= deadline


@dataclass(frozen=True, slots=True)
class StatusMessageSnapshot:
    """Immutable, deterministically ordered status state for renderers."""

    observed_at_monotonic: float
    current: StatusMessage | None
    active_messages: tuple[StatusMessage, ...]


class StatusMessageService:
    """Publish and arbitrate status messages across application threads."""

    def __init__(self, clock: MonotonicClock = monotonic) -> None:
        self._clock = clock
        self._lock = RLock()
        self._messages: dict[str, StatusMessage] = {}
        self._sequence = 0

    def publish(
        self,
        *,
        replacement_key: str,
        text: str,
        presentation: StatusPresentation = StatusPresentation.NORMAL,
        priority: int = 0,
        duration_s: float | None = None,
    ) -> StatusMessage:
        """Publish or replace one message and return the immutable result."""
        normalized_key = replacement_key.strip()
        normalized_text = text.strip()
        if not normalized_key:
            raise ValueError("Status replacement key must not be blank.")
        if not normalized_text:
            raise ValueError("Status message text must not be blank.")
        if duration_s is not None and duration_s <= 0:
            raise ValueError("Status message duration must be greater than zero.")

        with self._lock:
            now = self._clock()
            self._prune_expired_locked(now)
            self._sequence += 1
            message = StatusMessage(
                replacement_key=normalized_key,
                text=normalized_text,
                presentation=presentation,
                priority=priority,
                sequence=self._sequence,
                created_at_monotonic=now,
                expires_at_monotonic=(None if duration_s is None else now + duration_s),
            )
            self._messages[normalized_key] = message
            return message

    def clear(self, replacement_key: str) -> bool:
        """Clear one publisher's message without disturbing other messages."""
        normalized_key = replacement_key.strip()
        if not normalized_key:
            raise ValueError("Status replacement key must not be blank.")

        with self._lock:
            self._prune_expired_locked(self._clock())
            return self._messages.pop(normalized_key, None) is not None

    def snapshot(self) -> StatusMessageSnapshot:
        """Return the current immutable arbitration result."""
        with self._lock:
            now = self._clock()
            self._prune_expired_locked(now)
            active_messages = tuple(
                sorted(
                    self._messages.values(),
                    key=lambda message: (message.priority, message.sequence),
                    reverse=True,
                )
            )
            return StatusMessageSnapshot(
                observed_at_monotonic=now,
                current=active_messages[0] if active_messages else None,
                active_messages=active_messages,
            )

    def _prune_expired_locked(self, now_monotonic: float) -> None:
        expired_keys = tuple(
            key for key, message in self._messages.items() if message.is_expired(now_monotonic)
        )
        for key in expired_keys:
            del self._messages[key]
