"""Tests for mobile FT8 CQ browser presentation."""

from rolling_thunder.ft8.attempt_history import FT8AttemptVisualState
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period
from rolling_thunder.ft8_ui import (
    FT8_BROWSER_HEADERS,
    FT8_POTA_TREE_GLYPH,
    FT8CallPresentation,
    build_ft8_browser_viewport,
)


def _activity(
    callsign: str,
    *,
    cq_count: int = 1,
    active_non_cq: bool = False,
    pota: bool = False,
) -> FT8CQActivity:
    return FT8CQActivity(
        callsign=callsign,
        last_period=FT8Period(100),
        last_any_decode=FT8Period(101) if active_non_cq else FT8Period(100),
        cq_count=cq_count,
        snr_db=-8,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        grid="FN31",
        pota_cq=pota,
        active_non_cq=active_non_cq,
    )


def test_headers_are_explicit_and_mobile_columns_are_stable() -> None:
    viewport = build_ft8_browser_viewport(
        (_activity("K1ABC"),),
        selected_callsign=None,
    )

    assert viewport.headers == FT8_BROWSER_HEADERS
    assert viewport.headers == ("CALL", "SNR", "AUDIO", "GRID")


def test_cq_lifecycle_maps_white_gray_yellow() -> None:
    viewport = build_ft8_browser_viewport(
        (
            _activity("K1AAA", cq_count=1),
            _activity("K2BBB", cq_count=2),
            _activity("K3CCC", cq_count=3),
            _activity("K4DDD", cq_count=7, active_non_cq=True),
        ),
        selected_callsign=None,
    )

    assert [row.call_presentation for row in viewport.rows] == [
        FT8CallPresentation.YELLOW,
        FT8CallPresentation.YELLOW,
        FT8CallPresentation.WHITE,
        FT8CallPresentation.GRAY,
    ]


def test_pota_metadata_adds_tree_glyph_without_callsign_inference() -> None:
    viewport = build_ft8_browser_viewport(
        (
            _activity("K1POTA", pota=True),
            _activity("K2POTA", pota=False),
        ),
        selected_callsign=None,
    )

    assert FT8_POTA_TREE_GLYPH == "🌲"
    assert viewport.rows[0].call_text == "K1POTA"
    assert viewport.rows[0].pota_cq is True
    assert viewport.rows[1].call_text == "K2POTA"
    assert viewport.rows[1].pota_cq is False


def test_selected_station_remains_in_view_without_reordering_source() -> None:
    activity = tuple(_activity(f"K{index}ABC") for index in range(1, 9))

    viewport = build_ft8_browser_viewport(
        activity,
        selected_callsign="K7ABC",
        visible_rows=4,
    )

    assert [row.callsign for row in viewport.rows] == [
        "K4ABC",
        "K5ABC",
        "K6ABC",
        "K7ABC",
    ]
    assert viewport.rows[-1].selected is True
    assert viewport.hidden_above == 3
    assert viewport.hidden_below == 1
    assert [item.callsign for item in activity] == [
        "K1ABC",
        "K2ABC",
        "K3ABC",
        "K4ABC",
        "K5ABC",
        "K6ABC",
        "K7ABC",
        "K8ABC",
    ]


def test_failed_and_aborted_attempt_history_overrides_cq_lifecycle_color() -> None:
    viewport = build_ft8_browser_viewport(
        (
            _activity("K1FAIL", cq_count=1),
            _activity("K2ABRT", cq_count=7, active_non_cq=True),
        ),
        selected_callsign=None,
        attempt_states={
            "K1FAIL": FT8AttemptVisualState.FAILED,
            "K2ABRT": FT8AttemptVisualState.ABORTED,
        },
    )

    failed, aborted = viewport.rows
    assert failed.call_presentation is FT8CallPresentation.RED
    assert failed.call_text == "! K1FAIL"
    assert aborted.call_presentation is FT8CallPresentation.BLUE
    assert aborted.call_text == "■ K2ABRT"


def test_attempt_history_does_not_add_non_cq_rows() -> None:
    viewport = build_ft8_browser_viewport(
        (_activity("K1ABC"),),
        selected_callsign=None,
        attempt_states={
            "K1ABC": FT8AttemptVisualState.FAILED,
            "K9NOTCQ": FT8AttemptVisualState.ABORTED,
        },
    )

    assert [row.callsign for row in viewport.rows] == ["K1ABC"]
