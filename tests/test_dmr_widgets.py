"""Headless tests for the compact Tk DMR widget adapter."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import Any

from rolling_thunder.dmr_ui import DmrAudioCard, DmrHistoryCard, DmrViewport
from rolling_thunder.dmr_widgets import DmrWidgets


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
        self.visible = False
        self.children: list[FakeWidget] = []
        if isinstance(parent, FakeWidget):
            parent.children.append(self)

    def grid(self, **kwargs: Any) -> None:
        self.visible = True
        self.options.update({f"grid_{key}": value for key, value in kwargs.items()})

    def grid_remove(self) -> None:
        self.visible = False

    def grid_columnconfigure(self, _column: int, **_kwargs: Any) -> None:
        return None

    def configure(self, **kwargs: Any) -> None:
        self.options.update(kwargs)

    def winfo_children(self) -> list[FakeWidget]:
        return list(self.children)


def _install_fake_tk(monkeypatch: Any) -> None:
    fake_tk = SimpleNamespace(
        Frame=FakeWidget,
        Label=FakeWidget,
        StringVar=FakeStringVar,
    )
    monkeypatch.setitem(sys.modules, "tkinter", fake_tk)


def _viewport(
    *,
    health_line: str = "HEALTHY  LIVE OK  HISTORY OK  RF OK",
    error_line: str = "",
    audio: tuple[DmrAudioCard, ...] = (),
    history: tuple[DmrHistoryCard, ...] = (),
    hidden_above: int = 0,
    hidden_below: int = 0,
    stage_line: str = "BTN1 STAGE CURRENT",
    commit_line: str = "",
) -> DmrViewport:
    return DmrViewport(
        title="DMR HOTSPOT",
        health_line=health_line,
        error_line=error_line,
        rf_line="RX 434.5375 MHz  TX 439.5375 MHz  DUPLEX",
        current_audio_cards=audio,
        history_cards=history,
        hidden_above_count=hidden_above,
        hidden_below_count=hidden_below,
        stage_line=stage_line,
        commit_line=commit_line,
    )


def test_constructor_starts_hidden(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)

    widgets = DmrWidgets(FakeWidget())

    assert not widgets._frame.visible
    widgets.show()
    assert widgets._frame.visible
    widgets.hide()
    assert not widgets._frame.visible


def test_idle_view_shows_rf_health_and_idle_state(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)
    widgets = DmrWidgets(FakeWidget())

    widgets.update(_viewport())

    assert widgets._health.get() == "HEALTHY  LIVE OK  HISTORY OK  RF OK"
    assert widgets._rf.get() == "RX 434.5375 MHz  TX 439.5375 MHz  DUPLEX"
    assert widgets._audio_idle_label.visible
    assert not widgets._error_label.visible
    assert all(not frame.visible for frame in widgets._audio_frames)
    assert all(not frame.visible for frame in widgets._history_frames)


def test_active_audio_and_history_cards_render_selection_and_stage(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)
    widgets = DmrWidgets(FakeWidget())
    audio = (
        DmrAudioCard(
            callsign_line="KC9KPJ",
            detail_line="TS1  TG 3100  NETWORK",
            alias_line="KC9KPJ Michael",
            staged=True,
        ),
    )
    history = (
        DmrHistoryCard(
            callsign_line="W3GSI - Raymond",
            detail_line="00:07:00Z  TS1 TG3100  8.8s  NETWORK",
            selected=True,
            staged=False,
        ),
        DmrHistoryCard(
            callsign_line="KR4MFP - James",
            detail_line="00:06:05Z  TS1 TG3100  1.6s  NETWORK",
            selected=False,
            staged=True,
        ),
    )

    widgets.update(
        _viewport(
            audio=audio,
            history=history,
            hidden_above=2,
            hidden_below=14,
            stage_line="STAGED KR4MFP TS1 TG3100 • BTN2 COMMIT • BACK CANCEL",
            commit_line="COMMITTING STAGED DMR QSO",
        )
    )

    assert not widgets._audio_idle_label.visible
    assert widgets._audio_frames[0].visible
    assert widgets._audio_vars[0][0].get() == "KC9KPJ"
    assert widgets._audio_frames[0].options["highlightbackground"] == "#42ff72"
    assert widgets._history_frames[0].visible
    assert widgets._history_frames[0].options["bg"] == "#2a3f4b"
    assert widgets._history_frames[0].options["highlightbackground"] == "#ffffff"
    assert widgets._history_frames[1].options["highlightbackground"] == "#42ff72"
    assert widgets._more.get() == "▲ 2 NEWER     ▼ 14 OLDER"
    assert widgets._stage.get().startswith("STAGED KR4MFP")
    assert widgets._commit.get() == "COMMITTING STAGED DMR QSO"
    assert widgets._commit_label.options["fg"] == "#ffd24a"


def test_error_and_commit_outcomes_have_visible_status_colors(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)
    widgets = DmrWidgets(FakeWidget())

    widgets.update(
        _viewport(
            health_line="DEGRADED  LIVE DOWN  HISTORY OK  RF OK",
            error_line="LIVE: ssh disconnected",
            commit_line="COMMIT FAILED: database busy",
        )
    )

    assert widgets._error_label.visible
    assert widgets._error.get() == "LIVE: ssh disconnected"
    assert widgets._health_label.options["fg"] == "#ffd24a"
    assert widgets._commit_label.options["fg"] == "#ff7070"

    widgets.update(_viewport(commit_line="LOGGED KC9KPJ"))

    assert widgets._commit_label.options["fg"] == "#42ff72"


def test_widget_adapter_limits_preallocated_card_slots(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)

    widgets = DmrWidgets(FakeWidget())

    assert len(widgets._audio_frames) == 2
    assert len(widgets._history_frames) == 4
