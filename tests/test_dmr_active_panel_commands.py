"""Tests for DMR-aware active-panel command routing."""

import pytest

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.dmr_active_panel_commands import DmrAwareActivePanelCommands


class RecordingDelegate:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.contexts: list[ContextId] = []

    def activate_context(self, context_id: ContextId) -> None:
        self.contexts.append(context_id)

    def primary(self) -> bool:
        self.calls.append("primary")
        return True

    def secondary(self) -> bool:
        self.calls.append("secondary")
        return True

    def tertiary(self) -> bool:
        self.calls.append("tertiary")
        return True

    def tertiary_long(self) -> bool:
        self.calls.append("tertiary_long")
        return True

    def move_previous(self) -> bool:
        self.calls.append("move_previous")
        return True

    def move_next(self) -> bool:
        self.calls.append("move_next")
        return True

    def activate_selection(self) -> bool:
        self.calls.append("activate_selection")
        return True

    def back(self) -> bool:
        self.calls.append("back")
        return True


class RecordingDmrPanel:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.refresh_count = 0

    def refresh(self) -> object:
        self.refresh_count += 1
        return object()

    def primary(self) -> bool:
        self.calls.append("primary")
        return True

    def secondary(self) -> bool:
        self.calls.append("secondary")
        return True

    def tertiary(self) -> bool:
        self.calls.append("tertiary")
        return True

    def tertiary_long(self) -> bool:
        self.calls.append("tertiary_long")
        return True

    def move_previous(self) -> bool:
        self.calls.append("move_previous")
        return True

    def move_next(self) -> bool:
        self.calls.append("move_next")
        return True

    def activate_selection(self) -> bool:
        self.calls.append("activate_selection")
        return True

    def back(self) -> bool:
        self.calls.append("back")
        return True


def _controller(
    context: ContextId,
) -> tuple[
    ContextNavigationController,
    RecordingDelegate,
    RecordingDmrPanel,
    DmrAwareActivePanelCommands,
]:
    navigation = ContextNavigationController(context)
    delegate = RecordingDelegate()
    dmr = RecordingDmrPanel()
    wrapper = DmrAwareActivePanelCommands(navigation, delegate, dmr)
    return navigation, delegate, dmr, wrapper


def test_activating_dmr_refreshes_dmr_snapshot_and_delegates_context_activation() -> None:
    _, delegate, dmr, wrapper = _controller(ContextId.POTA)

    wrapper.activate_context(ContextId.DMR)

    assert delegate.contexts == [ContextId.DMR]
    assert dmr.refresh_count == 1


def test_activating_non_dmr_context_does_not_refresh_dmr() -> None:
    _, delegate, dmr, wrapper = _controller(ContextId.POTA)

    wrapper.activate_context(ContextId.LOG)

    assert delegate.contexts == [ContextId.LOG]
    assert dmr.refresh_count == 0


@pytest.mark.parametrize(
    "method_name",
    [
        "primary",
        "secondary",
        "tertiary",
        "tertiary_long",
        "move_previous",
        "move_next",
        "activate_selection",
        "back",
    ],
)
def test_dmr_context_routes_every_panel_action_only_to_dmr(method_name: str) -> None:
    _, delegate, dmr, wrapper = _controller(ContextId.DMR)

    method = getattr(wrapper, method_name)
    assert method()

    assert dmr.calls == [method_name]
    assert delegate.calls == []


@pytest.mark.parametrize(
    "method_name",
    [
        "primary",
        "secondary",
        "tertiary",
        "tertiary_long",
        "move_previous",
        "move_next",
        "activate_selection",
        "back",
    ],
)
def test_non_dmr_context_preserves_existing_delegate_behavior(method_name: str) -> None:
    _, delegate, dmr, wrapper = _controller(ContextId.LOG)

    method = getattr(wrapper, method_name)
    assert method()

    assert delegate.calls == [method_name]
    assert dmr.calls == []


def test_runtime_context_change_switches_routing_without_rebuilding_wrapper() -> None:
    navigation, delegate, dmr, wrapper = _controller(ContextId.POTA)

    assert wrapper.primary()
    navigation.select(ContextId.DMR)
    wrapper.activate_context(ContextId.DMR)
    assert wrapper.primary()
    navigation.select(ContextId.LOG)
    wrapper.activate_context(ContextId.LOG)
    assert wrapper.primary()

    assert delegate.calls == ["primary", "primary"]
    assert delegate.contexts == [ContextId.DMR, ContextId.LOG]
    assert dmr.calls == ["primary"]
    assert dmr.refresh_count == 1
