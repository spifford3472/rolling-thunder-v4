"""Fail-closed Settings power confirmation and narrow Linux adapter."""

from __future__ import annotations

import math
import subprocess
from collections.abc import Callable
from concurrent.futures import Executor, ThreadPoolExecutor
from dataclasses import dataclass
from enum import StrEnum
from threading import Lock
from time import monotonic
from typing import Protocol

from rolling_thunder.context_navigation import ContextId
from rolling_thunder.control_transport_health import TransportHealthState
from rolling_thunder.domain import RadioConnectionState, RadioState
from rolling_thunder.physical_controls import ControlAction, ControlInputEvent
from rolling_thunder.settings_selection import SettingId


class PowerAction(StrEnum):
    """The only operating-system power actions exposed by Settings."""

    REBOOT = "reboot"
    SHUTDOWN = "poweroff"


@dataclass(frozen=True, slots=True)
class PowerInputProof:
    """Fresh serial-v2 input identity retained through confirmation."""

    event_id: str
    session_nonce: str
    generation: int
    received_at: float
    expires_at: float

    @property
    def sequence(self) -> int | None:
        prefix, separator, raw_sequence = self.event_id.partition(":")
        if separator != ":" or prefix != self.session_nonce or not raw_sequence.isdigit():
            return None
        if raw_sequence != str(int(raw_sequence)):
            return None
        sequence = int(raw_sequence)
        return sequence if 0 < sequence < 2**64 else None


@dataclass(frozen=True, slots=True)
class PowerGuardState:
    """Published safety facts checked without probing hardware."""

    ft8_context_attached: bool = False
    ft8_busy: bool = False
    hardware_transmitting: bool = False
    ptt_alarm_or_inhibited: bool = False
    radio_transmitting: bool | None = False
    contact_commit_active: bool = False
    dmr_commit_active: bool = False

    @property
    def safe(self) -> bool:
        return not any(
            (
                self.ft8_context_attached,
                self.ft8_busy,
                self.hardware_transmitting,
                self.ptt_alarm_or_inhibited,
                self.radio_transmitting is not False,
                self.contact_commit_active,
                self.dmr_commit_active,
            )
        )


def radio_power_guard(state: RadioState) -> bool | None:
    """Keep TX evidence; allow an explicitly disconnected, non-transmitting radio.

    This does not bypass the independent FT8/hardware/PTT/commit guards. Connecting
    and error states remain unknown; disconnect never clears a retained TX flag.
    """
    if state.transmitting:
        return True
    if state.connection_state in (
        RadioConnectionState.CONNECTED, RadioConnectionState.DISCONNECTED,
    ):
        return False
    return None


class PowerOperatingSystem(Protocol):
    def request(self, action: PowerAction) -> None:
        """Request one fixed OS transition or raise a truthful failure."""


class PreferenceBarrier(Protocol):
    def flush(self, timeout_s: float) -> bool:
        """Wait boundedly for earlier queued preferences without stopping the service."""


class LinuxSystemctlPowerAdapter:
    """Execute one allowlisted, noninteractive power request through sudo."""

    _SUDO = "/usr/bin/sudo"
    _SYSTEMCTL = "/usr/bin/systemctl"

    def __init__(
        self,
        *,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self._runner = runner

    def request(self, action: PowerAction) -> None:
        if not isinstance(action, PowerAction):
            raise TypeError("Power action must be a PowerAction.")
        completed = self._runner(
            [self._SUDO, "-n", self._SYSTEMCTL, "--no-ask-password", action.value],
            shell=False,
            capture_output=True,
            text=True,
            timeout=5.0,
            check=False,
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "systemctl request failed").strip()
            raise RuntimeError(detail[:256])


@dataclass(frozen=True, slots=True)
class PowerConfirmationState:
    action: PowerAction | None = None
    expires_at: float | None = None
    pending: bool = False
    last_error: str | None = None
    available: bool = False
    health: TransportHealthState | None = None


class PowerConfirmationController:
    """Own a fresh two-press confirmation and at-most-once background submission."""

    def __init__(
        self,
        operating_system: PowerOperatingSystem,
        preferences: PreferenceBarrier,
        guard: Callable[[], PowerGuardState],
        *,
        clock: Callable[[], float] = monotonic,
        executor: Executor | None = None,
        confirmation_s: float = 10.0,
        deliberate_s: float = 0.15,
    ) -> None:
        self._os = operating_system
        self._preferences = preferences
        self._guard = guard
        self._clock = clock
        self._owns_executor = executor is None
        self._executor = executor or ThreadPoolExecutor(max_workers=1, thread_name_prefix="rt-power")
        self._confirmation_s = confirmation_s
        self._deliberate_s = deliberate_s
        self._lock = Lock()
        self._state = PowerConfirmationState()
        self._proof: PowerInputProof | None = None
        self._stopped = False

    @property
    def state(self) -> PowerConfirmationState:
        with self._lock:
            state = self._state
        if (
            state.action is not None
            and state.expires_at is not None
            and not state.pending
            and self._clock() >= state.expires_at
        ):
            self.cancel()
            with self._lock:
                return self._state
        return state

    def request_or_confirm(self, action: PowerAction, proof: PowerInputProof) -> bool:
        """Stage on the first proven press; submit only a distinct deliberate second press."""
        now = self._clock()
        with self._lock:
            if self._stopped or self._state.pending:
                return False
        if not self._valid(proof, now):
            self.cancel()
            return False
        if not self._guard().safe:
            with self._lock:
                self._state = PowerConfirmationState(
                    action=action,
                    last_error="Power request blocked by active radio or durable work.",
                    available=self._state.available,
                    health=self._state.health,
                )
                self._proof = None
            return False
        with self._lock:
            if self._state.pending:
                return False
            first = self._proof
            if self._state.action is not action or first is None or now >= (self._state.expires_at or 0):
                self._proof = proof
                self._state = PowerConfirmationState(
                    action,
                    now + self._confirmation_s,
                    available=self._state.available,
                    health=self._state.health,
                )
                return True
            if (
                proof.session_nonce != first.session_nonce
                or proof.generation != first.generation
                or proof.event_id == first.event_id
                or proof.sequence is None
                or first.sequence is None
                or proof.sequence <= first.sequence
                or proof.received_at - first.received_at < self._deliberate_s
            ):
                self._state = PowerConfirmationState()
                self._proof = None
                return False
            self._state = PowerConfirmationState(
                action,
                self._state.expires_at,
                pending=True,
                available=self._state.available,
                health=self._state.health,
            )
            self._proof = proof
        try:
            self._executor.submit(self._submit, action)
        except RuntimeError as failure:
            with self._lock:
                self._state = PowerConfirmationState(
                    action=action,
                    last_error=f"Power request worker unavailable: {failure}"[:256],
                    available=self._state.available,
                    health=self._state.health,
                )
                self._proof = None
            return False
        return True

    def cancel(self) -> bool:
        with self._lock:
            if self._state.pending:
                return False
            changed = self._state.action is not None
            self._state = PowerConfirmationState(
                available=self._state.available,
                health=self._state.health,
            )
            self._proof = None
            return changed

    def invalidate_session(self) -> None:
        """Cancel confirmation after controller loss or generation replacement."""
        self.cancel()

    def stop(self) -> None:
        """Release the owned worker during application cleanup."""
        with self._lock:
            self._stopped = True
        if self._owns_executor and isinstance(self._executor, ThreadPoolExecutor):
            self._executor.shutdown(wait=False, cancel_futures=True)

    def retain_session(
        self,
        nonce: str | None,
        generation: int | None,
        health: TransportHealthState | None,
    ) -> None:
        """Cancel a staged confirmation when its proven controller session is lost."""
        available = (
            health is TransportHealthState.HEALTHY
            and isinstance(nonce, str)
            and bool(nonce)
            and type(generation) is int
            and generation > 0
        )
        with self._lock:
            proof = self._proof
            pending = self._state.pending
            self._state = PowerConfirmationState(
                self._state.action,
                self._state.expires_at,
                self._state.pending,
                self._state.last_error,
                available,
                health,
            )
        if (
            proof is not None
            and not pending
            and (
                not available
                or nonce != proof.session_nonce
                or generation != proof.generation
            )
        ):
            self.cancel()

    def _valid(self, proof: PowerInputProof, now: float) -> bool:
        return (
            proof.sequence is not None
            and type(proof.generation) is int
            and proof.generation > 0
            and math.isfinite(proof.received_at)
            and math.isfinite(proof.expires_at)
            and proof.received_at >= 0
            and proof.received_at <= now < proof.expires_at
        )

    def _require_running(self) -> None:
        with self._lock:
            if self._stopped:
                raise RuntimeError("Power request canceled during application cleanup.")

    def _submit(self, action: PowerAction) -> None:
        error: str | None = None
        try:
            self._require_running()
            if not self._guard().safe:
                raise RuntimeError("Power request blocked by active radio or durable work.")
            if not self._preferences.flush(3.0):
                raise RuntimeError("Queued operator preferences could not be flushed.")
            if not self._guard().safe:
                raise RuntimeError("Power request guard changed before OS submission.")
            self._require_running()
            self._os.request(action)
        except (OSError, RuntimeError, subprocess.SubprocessError) as failure:
            error = str(failure)[:256]
        if error is not None:
            with self._lock:
                self._state = PowerConfirmationState(
                    action=action,
                    last_error=error,
                    available=self._state.available,
                    health=self._state.health,
                )
                self._proof = None
            return
        with self._lock:
            self._state = PowerConfirmationState(
                action=action,
                pending=True,
                available=self._state.available,
                health=self._state.health,
            )


class SettingsPowerEventInterceptor:
    """Consume only Settings power buttons while retaining serial-v2 proof."""

    def __init__(
        self,
        confirmation: PowerConfirmationController,
        *,
        context: Callable[[], ContextId],
        selection: Callable[[], SettingId],
        recovery_snapshot: Callable[[], object],
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._confirmation = confirmation
        self._context = context
        self._selection = selection
        self._snapshot = recovery_snapshot
        self._clock = clock

    def intercept(self, event: ControlInputEvent, action: ControlAction) -> bool | None:
        if self._context() is not ContextId.SETTINGS:
            self._confirmation.cancel()
            return None
        selected = self._selection()
        power_action = {
            SettingId.REBOOT: PowerAction.REBOOT,
            SettingId.SHUTDOWN: PowerAction.SHUTDOWN,
        }.get(selected)
        if power_action is None:
            return None
        if self._confirmation.state.pending:
            return False
        if action is ControlAction.PANEL_SECONDARY:
            return self._confirmation.cancel()
        if action is not ControlAction.PANEL_TERTIARY:
            return None
        snapshot = self._snapshot()
        health = getattr(snapshot, "health", None)
        nonce = getattr(snapshot, "session_nonce", None)
        generation = getattr(health, "generation", None)
        if (
            getattr(health, "state", None) is not TransportHealthState.HEALTHY
            or not isinstance(nonce, str)
            or type(generation) is not int
            or generation <= 0
            or event.expires_at_s is None
        ):
            self._confirmation.cancel()
            return False
        return self._confirmation.request_or_confirm(
            power_action,
            PowerInputProof(
                event.event_id,
                nonce,
                generation,
                event.occurred_at_s,
                event.expires_at_s,
            ),
        )
