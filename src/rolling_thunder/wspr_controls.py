"""Accept a WSPR Run or Stop only from a validated physical button event."""

from collections.abc import Callable

from rolling_thunder.physical_controls import ControlAction, ControlInputEvent
from rolling_thunder.wspr_receive import WsprReceive


class WsprControlInterceptor:
    """Apply manual WSPR controls at the normal physical dispatch boundary."""

    def __init__(
        self,
        receive: WsprReceive,
        *,
        selected: Callable[[], bool],
        allowed: Callable[[], bool],
        radio_idle: Callable[[], bool],
    ) -> None:
        self._receive = receive
        self._selected = selected
        self._allowed = allowed
        self._radio_idle = radio_idle

    def intercept(self, event: ControlInputEvent, action: ControlAction) -> bool | None:
        if not self._selected():
            return None
        if action is ControlAction.PANEL_SECONDARY:
            return self._receive.stop()
        if action is ControlAction.PANEL_TERTIARY:
            if not self._allowed():
                return False
            if not self._radio_idle():
                self._receive.start_inhibited("Another radio operation is active")
                return False
            return self._receive.start()
        return None
