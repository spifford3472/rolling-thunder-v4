"""Contrast and redraw coverage for the shared target clock."""

from unittest.mock import Mock, call

from rolling_thunder.callsign_info_ui import CallsignInfoOverlayWidgets


def widgets() -> tuple[CallsignInfoOverlayWidgets, Mock]:
    overlay = CallsignInfoOverlayWidgets.__new__(CallsignInfoOverlayWidgets)
    canvas = Mock()
    canvas.winfo_width.return_value = 800
    canvas.winfo_height.return_value = 400
    canvas.create_text.return_value = 10
    canvas.create_rectangle.return_value = 11
    canvas.bbox.return_value = (550, 10, 788, 42)
    canvas.find_all.return_value = (10,)
    overlay._map = canvas
    overlay._map_photos = {}
    overlay._map_photo_cache = {}
    return overlay, canvas


def draw(overlay: CallsignInfoOverlayWidgets, text: str) -> None:
    overlay._draw_map(None, None, pin_visible=False, location_note=None, local_time_text=text)


def test_clock_has_fitted_white_backing_above_map_and_below_text() -> None:
    overlay, canvas = widgets()
    draw(overlay, "LOCAL 23:50")
    canvas.create_text.assert_called_once_with(
        788,
        10,
        text="LOCAL 23:50",
        fill="#000000",
        font=("DejaVu Sans", 48, "bold"),
        anchor="ne",
    )
    canvas.bbox.assert_called_once_with(10)
    canvas.create_rectangle.assert_called_once_with(
        544,
        7,
        794,
        45,
        fill="#ffffff",
        outline="",
    )
    canvas.tag_lower.assert_called_once_with(11, 10)
    assert canvas.method_calls.index(call.delete("all")) < (
        canvas.method_calls.index(call.tag_lower(11, 10))
    )


def test_unknown_time_draws_no_clock_or_background() -> None:
    overlay, canvas = widgets()
    draw(overlay, "")
    canvas.create_text.assert_not_called()
    canvas.create_rectangle.assert_not_called()
    canvas.tag_lower.assert_not_called()


def test_redraw_removes_previous_clock_when_time_disappears() -> None:
    overlay, canvas = widgets()
    draw(overlay, "LOCAL 23:50")
    canvas.reset_mock()
    draw(overlay, "")
    canvas.delete.assert_called_once_with("all")
    canvas.create_text.assert_not_called()
    canvas.create_rectangle.assert_not_called()
