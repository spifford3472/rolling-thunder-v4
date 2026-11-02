"""Tron navigation stays within approved, non-RF UI contexts."""
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.tron_commands import TronIntent
from rolling_thunder.tron_dispatch import dispatch_tron_intent


def test_approved_navigation_notifies_existing_panel_controller() -> None:
    nav = ContextNavigationController()
    notified = []
    result = dispatch_tron_intent(TronIntent("navigate", "ft8"), nav, on_context_changed=notified.append)
    assert result == "Showing FT8."
    assert nav.state.selected is ContextId.FT8
    assert notified == [ContextId.FT8]


def test_unavailable_destinations_fail_closed() -> None:
    nav = ContextNavigationController()
    notified = []
    for destination in ("map", "unknown", None):
        assert dispatch_tron_intent(TronIntent("navigate", destination), nav, on_context_changed=notified.append) is None
    assert nav.state.selected is ContextId.POTA
    assert notified == []


def test_read_only_commands_do_not_navigate() -> None:
    nav = ContextNavigationController()
    assert "Tron" in dispatch_tron_intent(TronIntent("help"), nav)
    assert "POTA" in dispatch_tron_intent(TronIntent("status"), nav)
    assert dispatch_tron_intent(TronIntent("current_screen"), nav) == "POTA"
    assert nav.state.selected is ContextId.POTA
