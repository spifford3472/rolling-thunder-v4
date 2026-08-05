"""Tests for pure full-screen dashboard presentation helpers."""

import pytest

from rolling_thunder.status_messages import StatusPresentation
from rolling_thunder.ui_main import (
    _BRIGHT,
    _FAILURE,
    _MUTED,
    _SUCCESS,
    _WARNING,
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
