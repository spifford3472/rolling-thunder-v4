"""Headless tests for the graphical vehicle status bar widget adapter."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from rolling_thunder.status_bar_ui import (
    STATUS_BAR_HEIGHT_PX,
    STATUS_ICON_CANVAS_PX,
    STATUS_ICON_CELL_WIDTH_PX,
    STATUS_ICON_ORDER,
    StatusBarWidgets,
)
from rolling_thunder.status_monitor import StatusState
from rolling_thunder.status_strip import (
    STATUS_ITEM_ORDER,
    StatusStripItem,
    StatusStripSnapshot,
)


class FakeStringVar:
    def __init__(self, *, value: str = "") -> None:
        self.value = value

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class FakeWidget:
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        self.parent = parent
        self.options = dict(kwargs)
        self.children: list[FakeWidget] = []
        self.column_configs: dict[int, dict[str, Any]] = {}
        self.row_configs: dict[int, dict[str, Any]] = {}
        self.visible = False
        if isinstance(parent, FakeWidget):
            parent.children.append(self)

    def grid(self, **kwargs: Any) -> None:
        self.visible = True
        self.options.update({f"grid_{key}": value for key, value in kwargs.items()})

    def place(self, **kwargs: Any) -> None:
        self.visible = True
        self.options.update({f"place_{key}": value for key, value in kwargs.items()})

    def grid_propagate(self, value: bool) -> None:
        self.options["grid_propagate"] = value

    def grid_columnconfigure(self, column: int, **kwargs: Any) -> None:
        self.column_configs[column] = dict(kwargs)

    def grid_rowconfigure(self, row: int, **kwargs: Any) -> None:
        self.row_configs[row] = dict(kwargs)

    def configure(self, **kwargs: Any) -> None:
        self.options.update(kwargs)


class FakeCanvas(FakeWidget):
    def __init__(self, parent: Any = None, **kwargs: Any) -> None:
        super().__init__(parent, **kwargs)
        self.draw_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def delete(self, *args: Any) -> None:
        self.draw_calls.append(("delete", args, {}))

    def _record(self, name: str, *args: Any, **kwargs: Any) -> None:
        self.draw_calls.append((name, args, kwargs))

    def create_line(self, *args: Any, **kwargs: Any) -> None:
        self._record("line", *args, **kwargs)

    def create_rectangle(self, *args: Any, **kwargs: Any) -> None:
        self._record("rectangle", *args, **kwargs)

    def create_oval(self, *args: Any, **kwargs: Any) -> None:
        self._record("oval", *args, **kwargs)

    def create_arc(self, *args: Any, **kwargs: Any) -> None:
        self._record("arc", *args, **kwargs)

    def create_polygon(self, *args: Any, **kwargs: Any) -> None:
        self._record("polygon", *args, **kwargs)


def _install_fake_tk(monkeypatch: Any) -> None:
    fake_tk = SimpleNamespace(
        Frame=FakeWidget,
        Label=FakeWidget,
        Canvas=FakeCanvas,
        StringVar=FakeStringVar,
    )
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)


def _snapshot() -> StatusStripSnapshot:
    return StatusStripSnapshot(
        items=tuple(
            StatusStripItem(item_id, state)
            for item_id, state in zip(
                STATUS_ITEM_ORDER,
                (
                    StatusState.HEALTHY,
                    StatusState.UNAVAILABLE,
                    StatusState.STARTING,
                    StatusState.HEALTHY,
                ),
                strict=True,
            )
        )
    )


def test_status_bar_builds_six_equal_square_icon_cells(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)

    widgets = StatusBarWidgets(FakeWidget())

    assert widgets.frame.options["height"] == STATUS_BAR_HEIGHT_PX
    assert widgets.frame.options["grid_propagate"] is False
    assert tuple(widgets._canvases) == STATUS_ICON_ORDER

    icon_frame = widgets.frame.children[0]
    assert icon_frame.options["width"] == STATUS_ICON_CELL_WIDTH_PX * 6
    assert icon_frame.options["height"] == STATUS_BAR_HEIGHT_PX
    for column in range(6):
        assert icon_frame.column_configs[column] == {
            "weight": 1,
            "uniform": "vehicle-status-icon",
            "minsize": STATUS_ICON_CELL_WIDTH_PX,
        }

    for canvas in widgets._canvases.values():
        assert canvas.options["width"] == STATUS_ICON_CANVAS_PX
        assert canvas.options["height"] == STATUS_ICON_CANVAS_PX
        assert canvas.parent.options["width"] == STATUS_ICON_CELL_WIDTH_PX
        assert canvas.parent.options["height"] == STATUS_BAR_HEIGHT_PX


def test_status_bar_renders_health_aux_icons_and_only_visible_date_text(
    monkeypatch: Any,
) -> None:
    _install_fake_tk(monkeypatch)
    widgets = StatusBarWidgets(FakeWidget())

    widgets.update_statuses(_snapshot())
    widgets.set_message(
        "[[VOICE=READY]][[GPS=NO FIX]]"
        "Local Date: 2026-Aug-19 | UTC Date: 2026-Aug-20",
        foreground="#ffffff",
    )

    rendered = [repr(widgets._canvases[item_id].draw_calls) for item_id in STATUS_ICON_ORDER]
    assert "#42ff72" in rendered[0]
    assert "#ff3b3b" in rendered[1]
    assert "#8a8a8a" in rendered[2]
    assert "#42ff72" in rendered[3]
    assert "#42ff72" in rendered[4]
    assert "#ff3b3b" in rendered[5]
    assert widgets._ticker_text.get() == (
        "Local Date: 2026-Aug-19 | UTC Date: 2026-Aug-20"
    )
    assert widgets._ticker.options["anchor"] == "e"
    assert widgets._ticker.options["fg"] == "#ffffff"
