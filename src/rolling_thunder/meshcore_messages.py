"""Thread-safe MeshCore channel-message overlay state."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from textwrap import wrap
from threading import Lock
from time import monotonic


@dataclass(frozen=True)
class MeshCoreMessageOverlay:
    """Immutable current MeshCore notification rendered by the map UI."""

    channel: str
    message: str
    sequence: int
    expires_at: float


class MeshCoreMessageOverlayService:
    """Filter and coalesce live messages without hardware or UI dependencies."""

    def __init__(
        self,
        channels: Iterable[str],
        *,
        display_seconds: float = 20.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if display_seconds <= 0:
            raise ValueError("MeshCore overlay duration must be positive.")
        self._channels = frozenset(channel.casefold() for channel in channels)
        self._display_seconds = display_seconds
        self._clock = clock
        self._lock = Lock()
        self._sequence = 0
        self._current: MeshCoreMessageOverlay | None = None

    def publish(
        self,
        channel: str,
        message: str,
        *,
        historical: bool = False,
    ) -> bool:
        """Publish one newly received configured-channel message, newest wins."""
        normalized_channel = channel.strip()
        normalized_message = message.strip()
        if (
            historical
            or normalized_channel.casefold() not in self._channels
            or not normalized_message
        ):
            return False

        with self._lock:
            self._sequence += 1
            self._current = MeshCoreMessageOverlay(
                channel=normalized_channel,
                message=normalized_message,
                sequence=self._sequence,
                expires_at=self._clock() + self._display_seconds,
            )
        return True

    @property
    def latest_state(self) -> MeshCoreMessageOverlay | None:
        """Return the active immutable overlay, expiring it without blocking."""
        now = self._clock()
        with self._lock:
            current = self._current
            if current is not None and now >= current.expires_at:
                self._current = None
                return None
            return current


def bounded_message_lines(
    message: str,
    *,
    width: int,
    maximum_lines: int = 5,
) -> tuple[str, ...]:
    """Wrap and safely ellipsize a message within a fixed overlay viewport."""
    if width <= 0:
        raise ValueError("Message wrap width must be positive.")
    if maximum_lines <= 0:
        raise ValueError("Maximum message lines must be positive.")

    lines: list[str] = []
    paragraphs = message.splitlines() or [""]
    for paragraph in paragraphs:
        lines.extend(
            wrap(
                paragraph,
                width=width,
                replace_whitespace=True,
                drop_whitespace=True,
                break_long_words=True,
                break_on_hyphens=False,
            )
            or [""]
        )

    if len(lines) <= maximum_lines:
        return tuple(lines)

    visible = lines[:maximum_lines]
    final = visible[-1]
    visible[-1] = f"{final[: max(0, width - 1)].rstrip()}…"
    return tuple(visible)
