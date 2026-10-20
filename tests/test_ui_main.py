"""Tests for pure full-screen dashboard presentation helpers."""

from types import SimpleNamespace

import pytest

from rolling_thunder.context_navigation import ContextId
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period, FT8QsoState
from rolling_thunder.ft8.panel import FT8PanelMode, FT8PanelSnapshot
from rolling_thunder.ft8.start_control import FT8QsoStartState, FT8QsoStartStatus
from rolling_thunder.status_messages import StatusPresentation
from rolling_thunder.ui_main import (
    _BRIGHT,
    _CONTEXT_HEADER_FONT,
    _CONTEXT_SELECTED,
    _FAILURE,
    _MUTED,
    _PANEL_BACKGROUND,
    _POTA_WORKED_BACKGROUND,
    _POTA_WORKED_FOREGROUND,
    _SUCCESS,
    _WARNING,
    _callsign_info_presentation_boundary,
    _callsign_info_target,
    _context_decode_header_text,
    _pota_card_colors,
    _status_foreground,
)


def _activity(callsign: str = "W1AW", grid: str | None = "FN31") -> FT8CQActivity:
    return FT8CQActivity(
        callsign=callsign,
        last_period=FT8Period(100),
        snr_db=-8,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        grid=grid,
    )


@pytest.mark.parametrize(
    ("presentation", "expected"),
    [
        (StatusPresentation.NORMAL, _BRIGHT),
        (StatusPresentation.AMBER, _WARNING),
        (StatusPresentation.SUCCESS, _SUCCESS),
        (StatusPresentation.ERROR, _FAILURE),
        (StatusPresentation.MUTED, _MUTED),
    ],
)
def test_status_presentation_maps_to_dashboard_foreground(
    presentation: StatusPresentation,
    expected: str,
) -> None:
    assert _status_foreground(presentation) == expected


@pytest.mark.parametrize(
    ("selected", "worked", "expected"),
    [
        (False, False, (_PANEL_BACKGROUND, _BRIGHT)),
        (True, False, (_CONTEXT_SELECTED, _BRIGHT)),
        (False, True, (_POTA_WORKED_BACKGROUND, _POTA_WORKED_FOREGROUND)),
        (True, True, (_POTA_WORKED_BACKGROUND, _POTA_WORKED_FOREGROUND)),
    ],
)
def test_pota_card_colors_preserve_worked_background(
    selected: bool,
    worked: bool,
    expected: tuple[str, str],
) -> None:
    assert _pota_card_colors(selected=selected, worked=worked) == expected


def test_ft8_decode_header_text_is_optional_and_uses_reviewed_copy() -> None:
    assert _context_decode_header_text(ContextId.FT8, 17) == "DECODE 17"
    assert _context_decode_header_text(ContextId.FT8, None) == ""
    assert _context_decode_header_text(ContextId.POTA, 17) == ""
    assert _context_decode_header_text(ContextId.BROWSE, 17) == ""
    assert _CONTEXT_HEADER_FONT == ("DejaVu Sans", 48, "bold")


def test_callsign_info_target_follows_active_terminal_and_browse_lifecycle() -> None:
    activity = _activity()
    browse = FT8PanelSnapshot(
        mode=FT8PanelMode.BROWSE,
        cq_activity=(activity,),
        qso_state=FT8QsoState.IDLE,
    )
    selected = _callsign_info_target(
        ContextId.FT8,
        pending_callsign="STALE",
        ft8_snapshot=browse,
        selected_ft8_callsign="W1AW",
    )
    assert (selected.callsign, selected.grid) == ("W1AW", "FN31")

    active_context = SimpleNamespace(remote_callsign="K2ABC", remote_grid="EM79xm")
    active = FT8PanelSnapshot(
        mode=FT8PanelMode.ACTIVE,
        cq_activity=(),
        qso_state=FT8QsoState.WAIT_REPORT,
        active_context=active_context,
    )
    target = _callsign_info_target(
        ContextId.FT8,
        pending_callsign=None,
        ft8_snapshot=active,
    )
    assert (target.callsign, target.grid) == ("K2ABC", "EM79xm")

    terminal = FT8PanelSnapshot(
        mode=FT8PanelMode.TERMINAL,
        cq_activity=(),
        qso_state=FT8QsoState.COMPLETED,
        active_context=active_context,
    )
    target = _callsign_info_target(
        ContextId.FT8,
        pending_callsign=None,
        ft8_snapshot=terminal,
    )
    assert target.callsign is None


def test_callsign_info_target_uses_only_live_ft8_preparation_status() -> None:
    activity = _activity("K1ABC", "EM10")
    browse = FT8PanelSnapshot(
        mode=FT8PanelMode.BROWSE,
        cq_activity=(),
        qso_state=FT8QsoState.IDLE,
    )
    preparing = _callsign_info_target(
        ContextId.FT8,
        pending_callsign=None,
        ft8_snapshot=browse,
        ft8_start_status=FT8QsoStartStatus(
            state=FT8QsoStartState.PREPARING,
            activity=activity,
        ),
    )
    assert (preparing.callsign, preparing.grid) == ("K1ABC", "EM10")

    for stale_state in (
        FT8QsoStartState.STARTED,
        FT8QsoStartState.FAILED,
        FT8QsoStartState.RESTORED,
    ):
        stale = _callsign_info_target(
            ContextId.FT8,
            pending_callsign=None,
            ft8_snapshot=browse,
            ft8_start_status=FT8QsoStartStatus(
                state=stale_state,
                activity=activity,
            ),
        )
        assert stale.callsign is None


def test_callsign_info_target_preserves_non_ft8_pending_workflows() -> None:
    target = _callsign_info_target(
        ContextId.POTA,
        pending_callsign="W1AW",
    )

    assert target.callsign == "W1AW"
    assert target.grid is None


def test_callsign_info_presentation_error_is_isolated_and_hidden() -> None:
    hidden: list[bool] = []

    with _callsign_info_presentation_boundary(lambda: hidden.append(True)):
        raise RuntimeError("private provider detail")

    assert hidden == [True]
