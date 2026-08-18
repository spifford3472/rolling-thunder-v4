"""Tests for the isolated MeshCore canvas notification geometry."""

from rolling_thunder.live_map_ui import LiveMapWidgets
from rolling_thunder.meshcore_messages import MeshCoreMessageOverlay


class RecordingCanvas:
    def __init__(self) -> None:
        self.rectangles: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.text: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.raised: list[str] = []

    def create_rectangle(self, *args: object, **kwargs: object) -> int:
        self.rectangles.append((args, kwargs))
        return 1

    def create_text(self, *args: object, **kwargs: object) -> int:
        self.text.append((args, kwargs))
        return 2

    def tag_raise(self, tag: str) -> None:
        self.raised.append(tag)


def test_overlay_is_lower_left_bounded_and_separate_from_map_layers() -> None:
    canvas = RecordingCanvas()
    widgets = LiveMapWidgets.__new__(LiveMapWidgets)
    widgets._canvas = canvas
    overlay = MeshCoreMessageOverlay(
        channel="#skywarn",
        message="Severe weather message " * 30,
        sequence=1,
        expires_at=20.0,
    )

    widgets._draw_meshcore_overlay(overlay, width=1_600, height=900)

    rectangle_args, rectangle_options = canvas.rectangles[0]
    assert rectangle_args == (12, 626, 1500, 876)
    assert rectangle_options["fill"] == "#000000"
    assert rectangle_options["tags"] == "meshcore-overlay"

    header = canvas.text[0][1]
    message = canvas.text[1][1]
    assert header["text"] == "#skywarn"
    assert header["fill"] == "#42ff72"
    assert header["font"] == ("DejaVu Sans", 27, "bold")
    assert message["fill"] == "#ffffff"
    assert len(str(message["text"]).splitlines()) <= 5
    assert canvas.raised == ["meshcore-overlay"]
