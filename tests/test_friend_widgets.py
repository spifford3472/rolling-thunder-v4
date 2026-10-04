"""Headless gold-star rendering independent of selection/outcome colors."""

from datetime import UTC, datetime
from types import SimpleNamespace

from rolling_thunder.domain import SynchronizationState
from rolling_thunder.friend_presentation import FRIEND_COLOR
from rolling_thunder.ft8.attempt_history import FT8AttemptVisualState
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period
from rolling_thunder.ft8_ui import build_ft8_browser_viewport
from rolling_thunder.ft8_widgets import FT8Widgets
from rolling_thunder.log_panel import LogPanelRow, LogPanelSnapshot
from rolling_thunder.log_ui import LogWidgets


class Variable:
    def __init__(self, *, value=""):
        self.value = value

    def set(self, value):
        self.value = value


class Widget:
    def __init__(self, parent=None, **options):
        self.options = options
        self.children = []
        if parent:
            parent.children.append(self)

    def grid(self, **kwargs):
        pass

    def grid_remove(self):
        pass

    def grid_columnconfigure(self, *args, **kwargs):
        pass

    def grid_rowconfigure(self, *args, **kwargs):
        pass

    def configure(self, **kwargs):
        self.options.update(kwargs)


def test_ft8_star_is_gold_and_failed_selected_cq_semantics_remain(monkeypatch) -> None:
    import rolling_thunder.ft8_widgets as module

    monkeypatch.setattr(
        module, "tk", SimpleNamespace(Frame=Widget, Label=Widget, StringVar=Variable)
    )
    widgets = FT8Widgets(Widget())
    activity = (
        FT8CQActivity(
            callsign="W1ABC",
            last_period=FT8Period(100),
            snr_db=-5,
            dt_seconds=0,
            audio_frequency_hz=1500,
        ),
    )
    viewport = build_ft8_browser_viewport(
        activity,
        selected_callsign="W1ABC",
        attempt_states={"W1ABC": FT8AttemptVisualState.FAILED},
        friends=frozenset({"W1ABC"}),
    )
    widgets.update(viewport, transmit_enabled=False)
    assert widgets._friend_labels[0].options["text"] == "★"
    assert widgets._friend_labels[0].options["fg"] == FRIEND_COLOR
    assert widgets._row_labels[0][0].options["text"] == "! W1ABC"
    assert widgets._row_labels[0][0].options["fg"] == "#ff3b3b"
    assert widgets._row_frames[0].options["bg"] == "#315f73"
    widgets.update(
        build_ft8_browser_viewport(activity, selected_callsign="W1ABC"), transmit_enabled=False
    )
    assert widgets._friend_labels[0].options["text"] == ""


def test_log_star_never_changes_callsign_or_sync_semantics(monkeypatch) -> None:
    import sys

    monkeypatch.setitem(
        sys.modules, "tkinter", SimpleNamespace(Frame=Widget, Label=Widget, StringVar=Variable)
    )
    widgets = LogWidgets(Widget())
    snapshot = LogPanelSnapshot(
        rows=(
            LogPanelRow(
                datetime(2026, 10, 4, tzinfo=UTC), "W1ABC", "20m", "US", SynchronizationState.FAILED
            ),
        )
    )
    widgets.update(snapshot, friends=frozenset({"W1ABC"}))
    assert widgets._friend_labels[0].options["text"] == "★"
    assert widgets._friend_labels[0].options["fg"] == FRIEND_COLOR
    assert widgets._row_vars[0][1].value == "W1ABC"
    assert widgets._row_labels[0].options["fg"] == "#ff7070"
    widgets.update(snapshot)
    assert widgets._friend_labels[0].options["text"] == ""
