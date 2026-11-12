"""Rotary isolation and scroll viewport behavior without physical radio or GUI."""

from __future__ import annotations

from dataclasses import dataclass

from rolling_thunder.context_navigation import ContextId
from rolling_thunder.meshcore_ohgo_ui import (
    _OHGO_BODY_FONT,
    MeshcoreOhgoScrollInterceptor,
    MeshcoreOhgoWidgets,
)
from rolling_thunder.physical_controls import ControlAction, ControlInputEvent


def _event() -> ControlInputEvent:
    return ControlInputEvent("rotary-cw", "event-1", 1.0)


def test_ohgo_rotary_intercepts_only_on_ohgo_context() -> None:
    selected = [ContextId.POTA]
    received: list[ControlAction] = []
    adapter = MeshcoreOhgoScrollInterceptor(
        selected_context=lambda: selected[0],
        scroll=lambda a: received.append(a) or True,
    )
    assert adapter.intercept(_event(), ControlAction.MOVE_NEXT) is None
    selected[0] = ContextId.MESHCORE_OHGO
    assert adapter.intercept(_event(), ControlAction.MOVE_NEXT) is True
    assert adapter.intercept(_event(), ControlAction.MOVE_PREVIOUS) is True
    assert adapter.intercept(_event(), ControlAction.ACTIVATE_SELECTION) is None
    assert received == [ControlAction.MOVE_NEXT, ControlAction.MOVE_PREVIOUS]


def test_scroll_respects_existing_safety_gate() -> None:
    actions: list[ControlAction] = []
    adapter = MeshcoreOhgoScrollInterceptor(
        selected_context=lambda: ContextId.MESHCORE_OHGO,
        scroll=lambda a: actions.append(a) or True,
        allowed=lambda: False,
    )
    assert adapter.intercept(_event(), ControlAction.MOVE_NEXT) is False
    assert actions == []


@dataclass
class FakeText:
    content: str = ""
    state: str = "disabled"
    offset: float = 0
    replace_count: int = 0
    movements: list[tuple[int, str]] | None = None

    def __post_init__(self) -> None:
        self.movements = []

    def configure(self, *, state: str) -> None:
        self.state = state

    def delete(self, _from: str, _to: str) -> None:
        self.content = ""

    def insert(self, _at: str, text: str) -> None:
        self.content = text
        self.replace_count += 1

    def yview_moveto(self, value: float) -> None:
        self.offset = value

    def yview_scroll(self, offset: int, units: str) -> None:
        assert self.movements is not None
        self.movements.append((offset, units))


@dataclass
class FakeMore:
    content: str = ""

    def set(self, value: str) -> None:
        self.content = value


def test_scrollable_text_preserves_operator_position_across_refreshes() -> None:
    widget = object.__new__(MeshcoreOhgoWidgets)
    body = FakeText()
    more = FakeMore()
    widget._body = body  # type: ignore[assignment]
    widget._more = more  # type: ignore[assignment]
    widget._last_content = None
    widget.update("first incident")
    body.offset = 0.6
    widget.update("first incident")
    assert body.replace_count == 1
    assert body.offset == 0.6
    widget.update("new incident list")
    assert body.replace_count == 2
    assert body.offset == 0
    assert body.content == "new incident list"
    assert body.state == "disabled"


def test_more_indicator_reflects_actual_scrollable_geometry() -> None:
    widget = object.__new__(MeshcoreOhgoWidgets)
    indicator = FakeMore()
    widget._more = indicator  # type: ignore[assignment]
    widget._last_more = ""
    widget._on_scroll(0.0, 0.45)
    assert indicator.content == "MORE"
    widget._on_scroll(0.55, 1.0)
    assert indicator.content == ""
    widget._on_scroll(0.0, 1.0)
    assert indicator.content == ""
    assert _OHGO_BODY_FONT[1] == 42


def test_rotary_scroll_does_not_activate_any_selection() -> None:
    widget = object.__new__(MeshcoreOhgoWidgets)
    body = FakeText()
    widget._body = body  # type: ignore[assignment]
    assert widget.scroll(ControlAction.MOVE_NEXT)
    assert widget.scroll(ControlAction.MOVE_PREVIOUS)
    assert not widget.scroll(ControlAction.COMMIT)
    assert body.movements == [(1, "units"), (-1, "units")]


@dataclass
class FakeFrame:
    """Count geometry changes that would trigger a visible redraw."""

    mapped: bool = False
    grid_calls: int = 0
    remove_calls: int = 0

    def grid(self) -> None:
        self.mapped = True
        self.grid_calls += 1

    def grid_remove(self) -> None:
        self.mapped = False
        self.remove_calls += 1


def test_repeated_ohgo_refresh_never_unmaps_or_remaps_visible_text() -> None:
    """Regression for the blank/flash every UI refresh on the OHGO page."""

    widget = object.__new__(MeshcoreOhgoWidgets)
    frame = FakeFrame()
    widget.frame = frame  # type: ignore[assignment]
    widget._visible = False

    # First entry: one mapping, then many normal render cycles.
    for _ in range(100):
        if not widget.visible:
            widget.show()
    assert widget.visible
    assert frame.grid_calls == 1
    assert frame.remove_calls == 0

    # Context exit and reentry each cause exactly one geometry transition.
    for _ in range(50):
        widget.hide()
    assert frame.remove_calls == 1
    widget.show()
    assert frame.grid_calls == 2


def test_more_indicator_not_rewritten_when_overflow_state_is_unchanged() -> None:
    """Avoid unnecessary white footer repaints while text is steady."""

    class TrackedMore(FakeMore):
        changes = 0

        def set(self, value: str) -> None:
            self.changes += 1
            super().set(value)

    widget = object.__new__(MeshcoreOhgoWidgets)
    indicator = TrackedMore()
    widget._more = indicator  # type: ignore[assignment]
    widget._last_more = ""
    for _ in range(100):
        widget._on_scroll(0.0, 0.5)
    assert indicator.content == "MORE"
    assert indicator.changes == 1
    widget._on_scroll(0.5, 1.0)
    assert indicator.content == ""
    assert indicator.changes == 2
