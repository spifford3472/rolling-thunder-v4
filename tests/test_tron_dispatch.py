"""Tron UI dispatch stays within navigation and selection-only controls."""
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.tron_commands import TronIntent
from rolling_thunder.tron_dispatch import dispatch_tron_intent


class PanelCommands:
    def __init__(self, selected: bool = False, moves: int = 0) -> None:
        self.selected = selected
        self.moves = moves
        self.calls: list[str] = []
        self.authorizations = 0

    def move_previous(self) -> bool:
        self.calls.append("previous")
        if self.moves <= 0:
            return False
        self.moves -= 1
        return True

    def move_next(self) -> bool:
        self.calls.append("next")
        if self.moves <= 0:
            return False
        self.moves -= 1
        self.selected = True
        return True

    def has_station_selection(self) -> bool:
        return self.selected

    def select_station(self) -> bool:
        self.calls.append("select_station")
        if not self.selected and self.moves > 0:
            self.move_next()
        return self.selected


def test_approved_navigation_notifies_existing_panel_controller() -> None:
    nav = ContextNavigationController()
    notified = []
    result = dispatch_tron_intent(
        TronIntent("navigate", "ft8"), nav, on_context_changed=notified.append
    )
    assert result == "Showing FT8."
    assert nav.state.selected is ContextId.FT8
    assert notified == [ContextId.FT8]


def test_all_existing_destinations_are_available_through_navigation() -> None:
    nav = ContextNavigationController()
    for target, context in (
        ("browse", ContextId.BROWSE), ("weather", ContextId.WEATHER),
        ("repeaters", ContextId.REPEATERS), ("dmr", ContextId.DMR),
    ):
        assert dispatch_tron_intent(TronIntent("navigate", target), nav) is not None
        assert nav.state.selected is context


def test_unavailable_destinations_fail_closed() -> None:
    nav = ContextNavigationController()
    notified = []
    for destination in ("map", "unknown", None):
        assert dispatch_tron_intent(
            TronIntent("navigate", destination), nav, on_context_changed=notified.append
        ) is None
    assert nav.state.selected is ContextId.POTA
    assert notified == []


def test_read_only_commands_do_not_navigate() -> None:
    nav = ContextNavigationController()
    assert "Tron" in dispatch_tron_intent(TronIntent("help"), nav)
    assert "physical controls" in dispatch_tron_intent(TronIntent("help"), nav)
    assert "POTA" in dispatch_tron_intent(TronIntent("status"), nav)
    assert dispatch_tron_intent(TronIntent("current_screen"), nav) == "POTA"
    assert nav.state.selected is ContextId.POTA


def test_next_previous_and_first_last_move_only_within_station_lists() -> None:
    nav = ContextNavigationController(initial=ContextId.FT8)
    panel = PanelCommands(selected=True, moves=3)
    assert dispatch_tron_intent(TronIntent("next"), nav, panel_commands=panel)
    assert panel.calls == ["next"]
    assert dispatch_tron_intent(TronIntent("first"), nav, panel_commands=panel)
    assert panel.calls[-3:] == ["previous"] * 3
    panel.moves = 3
    assert dispatch_tron_intent(TronIntent("last"), nav, panel_commands=panel)
    assert panel.calls[-3:] == ["next"] * 3


def test_station_selection_highlights_only_and_never_authorizes_qso() -> None:
    nav = ContextNavigationController(initial=ContextId.FT8)
    panel = PanelCommands(selected=False, moves=1)
    response = dispatch_tron_intent(
        TronIntent("select_station"), nav, panel_commands=panel
    )
    assert response is not None and "physical controls" in response
    assert panel.calls == ["select_station", "next"]
    assert panel.authorizations == 0


def test_station_selection_and_movement_are_rejected_outside_supported_lists() -> None:
    nav = ContextNavigationController(initial=ContextId.BROWSE)
    panel = PanelCommands(selected=False, moves=1)
    assert "unavailable" in dispatch_tron_intent(
        TronIntent("first"), nav, panel_commands=panel
    )
    assert "unavailable" in dispatch_tron_intent(
        TronIntent("select_station"), nav, panel_commands=panel
    )
    assert panel.calls == []


def test_first_last_stop_at_a_bounded_step_count() -> None:
    nav = ContextNavigationController(initial=ContextId.FT8)
    panel = PanelCommands(selected=True, moves=100)
    response = dispatch_tron_intent(TronIntent("first"), nav, panel_commands=panel)
    assert response is not None and "64-step safety limit" in response
    assert panel.calls == ["previous"] * 64
