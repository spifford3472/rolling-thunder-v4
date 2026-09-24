"""Tests for pure full-screen dashboard presentation helpers."""

import pytest

from rolling_thunder.status_messages import StatusPresentation
from rolling_thunder.ui_main import (
    _BRIGHT,
    _CONTEXT_SELECTED,
    _FAILURE,
    _MUTED,
    _PANEL_BACKGROUND,
    _POTA_WORKED_BACKGROUND,
    _POTA_WORKED_FOREGROUND,
    _SUCCESS,
    _WARNING,
    _pota_card_colors,
    _status_foreground,
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
