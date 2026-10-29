"""Fresh-session validation for the opt-in controller recovery transport."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from rolling_thunder.control_protocol_v2 import Event, Pong, Ready
from rolling_thunder.physical_controls import ControlInputEvent


class ControlSessionError(ValueError):
    """A connection must be discarded rather than dispatching uncertain input."""


@dataclass(frozen=True)
class SessionResult:
    """A validated health observation or expiring physical input."""

    health: bool = False
    event: ControlInputEvent | None = None
    expires_at: float = 0.0


class ControlSessionV2:
    """Single-owner nonce, watermark and conservative event-age validation.

    A host challenge send time is a lower bound for the corresponding firmware
    observation. Use that bound, never the later receive time, to reject delayed
    data. Firmware and host clocks must progress monotonically within a session.
    """

    def __init__(
        self, nonce: str, now: float, inputs: frozenset[str], *, max_age_s: float = 0.5
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{32}", nonce) is None:
            raise ValueError("Session nonce must be 32 lowercase hex characters.")
        if (
            isinstance(now, bool)
            or isinstance(max_age_s, bool)
            or not math.isfinite(now)
            or now < 0
            or not math.isfinite(max_age_s)
            or max_age_s <= 0
        ):
            raise ValueError("Invalid session clock/age bound.")
        self.nonce = nonce
        self.firmware: str | None = None
        self._inputs = inputs
        self._max_age = max_age_s
        self._sent = now
        self._last_time = now
        self._boot: str | None = None
        self._sequence = 0
        self._uptime = 0
        self._anchor_uptime = 0
        self._anchor_sent = now
        self._request_id = 0
        self._pending: tuple[int, float] | None = None

    @property
    def can_ping(self) -> bool:
        """Whether a new challenge can be issued without overlap."""
        return self._boot is not None and self._pending is None

    @property
    def hello(self) -> bytes:
        """Return the sole initial freshness challenge."""
        return f"RTCTRL/2 HELLO {self.nonce}\n".encode("ascii")

    def ping(self, now: float) -> bytes:
        """Issue one bounded health challenge; never overlap requests."""
        self._time(now)
        if self._boot is None or self._pending is not None:
            raise ControlSessionError("Health challenge is not ready")
        if self._request_id == 2**64 - 1:
            raise ControlSessionError("Health sequence exhausted")
        self._request_id += 1
        self._pending = self._request_id, now
        return f"RTCTRL/2 PING {self.nonce} {self._request_id}\n".encode("ascii")

    def check_deadline(self, now: float) -> None:
        """Reject late synchronization or health replies even without new data."""
        self._time(now)
        sent = self._sent if self._boot is None else (self._pending[1] if self._pending else None)
        if sent is not None and now - sent >= self._max_age:
            raise ControlSessionError("Controller challenge timed out")

    def accept(self, frame: Ready | Pong | Event, now: float) -> SessionResult:
        """Validate current-session observations; no application command execution."""
        self.check_deadline(now)
        if frame.nonce != self.nonce:
            return SessionResult()
        if isinstance(frame, Ready):
            if self._boot is not None or frame.sequence != 0 or frame.firmware != "2.0.0":
                raise ControlSessionError("Unexpected controller session/version")
            self._boot = frame.boot
            self.firmware = frame.firmware
            self._anchor_sent = self._sent
            self._anchor_uptime = frame.uptime_ms
            self._uptime = frame.uptime_ms
            return SessionResult(health=True)
        if self._boot is None:
            return SessionResult()
        if frame.boot != self._boot:
            raise ControlSessionError("Controller rebooted")
        if isinstance(frame, Pong):
            if self._pending is None or frame.request_id != self._pending[0]:
                raise ControlSessionError("Unexpected health reply")
            if frame.sequence < self._sequence or frame.uptime_ms < self._uptime:
                raise ControlSessionError("Controller health regressed")
            self._anchor_sent = self._pending[1]
            self._anchor_uptime = frame.uptime_ms
            self._pending = None
            self._sequence = frame.sequence
            self._uptime = frame.uptime_ms
            return SessionResult(health=True)
        if frame.sequence <= self._sequence:
            return SessionResult()
        lower_bound = self._anchor_sent + (frame.uptime_ms - self._anchor_uptime) / 1000
        age = now - lower_bound
        if frame.uptime_ms < self._uptime or age < -0.01 or age >= self._max_age:
            raise ControlSessionError("Stale or inconsistent controller input")
        self._sequence = frame.sequence
        self._uptime = frame.uptime_ms
        if frame.input_id not in self._inputs:
            return SessionResult()
        return SessionResult(
            event=ControlInputEvent(
                frame.input_id, f"{self.nonce}:{frame.sequence}", frame.uptime_ms / 1000
            ),
            expires_at=lower_bound + self._max_age,
        )

    def _time(self, now: float) -> None:
        if isinstance(now, bool) or not math.isfinite(now) or now < self._last_time:
            raise ControlSessionError("Invalid session clock")
        self._last_time = now
