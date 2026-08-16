"""Apply Checkpoint 192 DMR twenty-row and render-efficiency adjustments.

This patch is intended for the locally validated one-column ten-row DMR layout.
It expands the bounded history viewport to all twenty retained WPSD records,
slightly enlarges the right-side detail text, moves footer rows below the larger
history region, and avoids repeated Tk widget reconfiguration when the immutable
DMR viewport has not changed.

It does not change network transports, persistence, logging, or live-audio
semantics. The deployment polling interval remains a local YAML setting so it
can be tested on the installed Raspberry Pi before becoming a repository default.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path} but found {count}: {old[:110]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED   {path}")


def main() -> None:
    dmr_ui = Path("src/rolling_thunder/dmr_ui.py")
    widgets = Path("src/rolling_thunder/dmr_widgets.py")
    viewport_tests = Path("tests/test_dmr_ui.py")
    widget_tests = Path("tests/test_dmr_widgets.py")

    replace_once(
        dmr_ui,
        "_DEFAULT_MAX_HISTORY_ROWS = 10",
        "_DEFAULT_MAX_HISTORY_ROWS = 20",
    )
    replace_once(
        widgets,
        "_MAX_HISTORY_CARDS = 10",
        "_MAX_HISTORY_CARDS = 20",
    )

    replace_once(
        widgets,
        """                font=(\"DejaVu Sans\", 19, \"bold\"),
                anchor=\"e\",
            ).grid(row=0, column=1, sticky=\"e\", padx=(4, 8), pady=0)
""",
        """                font=(\"DejaVu Sans\", 21, \"bold\"),
                anchor=\"e\",
            ).grid(row=0, column=1, sticky=\"e\", padx=(4, 8), pady=0)
""",
    )

    # Twenty history cards occupy rows 8 through 27.
    replace_once(
        widgets,
        ').grid(row=18, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0))',
        ').grid(row=28, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0))',
    )
    replace_once(
        widgets,
        ').grid(row=19, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 0))',
        ').grid(row=29, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 0))',
    )
    replace_once(
        widgets,
        """        self._commit_label.grid(
            row=20, column=0, columnspan=2, sticky=\"ew\", padx=6, pady=(1, 0)
        )
        self.hide()
""",
        """        self._commit_label.grid(
            row=30, column=0, columnspan=2, sticky=\"ew\", padx=6, pady=(1, 0)
        )
        self._last_viewport: DmrViewport | None = None
        self.hide()
""",
    )

    replace_once(
        widgets,
        """    def update(self, viewport: DmrViewport) -> None:
        \"\"\"Render one immutable viewport snapshot using only local widget operations.\"\"\"
        self._health.set(viewport.health_line)
""",
        """    def update(self, viewport: DmrViewport) -> None:
        \"\"\"Render a changed immutable viewport using only local widget operations.\"\"\"
        if viewport == self._last_viewport:
            return
        self._last_viewport = viewport
        self._health.set(viewport.health_line)
""",
    )

    replace_once(
        viewport_tests,
        """    assert len(viewport.history_cards) == 10
    assert viewport.hidden_above_count == 0
    assert viewport.hidden_below_count == 10
""",
        """    assert len(viewport.history_cards) == 20
    assert viewport.hidden_above_count == 0
    assert viewport.hidden_below_count == 0
""",
    )
    replace_once(
        viewport_tests,
        "def test_selected_history_is_kept_inside_ten_row_window() -> None:",
        "def test_selected_history_is_kept_inside_twenty_row_window() -> None:",
    )

    replace_once(
        widget_tests,
        """    assert len(widgets._history_frames) == 10
    assert widgets._history_frames[0].options[\"grid_row\"] == 8
    assert widgets._history_frames[0].options[\"grid_column\"] == 0
    assert widgets._history_frames[0].options[\"grid_columnspan\"] == 2
    assert widgets._history_frames[9].options[\"grid_row\"] == 17
    assert widgets._history_frames[9].options[\"grid_column\"] == 0
    assert widgets._history_frames[9].options[\"grid_columnspan\"] == 2
""",
        """    assert len(widgets._history_frames) == 20
    assert widgets._history_frames[0].options[\"grid_row\"] == 8
    assert widgets._history_frames[0].options[\"grid_column\"] == 0
    assert widgets._history_frames[0].options[\"grid_columnspan\"] == 2
    assert widgets._history_frames[9].options[\"grid_row\"] == 17
    assert widgets._history_frames[9].options[\"grid_column\"] == 0
    assert widgets._history_frames[9].options[\"grid_columnspan\"] == 2
    assert widgets._history_frames[19].options[\"grid_row\"] == 27
    assert widgets._history_frames[19].options[\"grid_column\"] == 0
    assert widgets._history_frames[19].options[\"grid_columnspan\"] == 2
""",
    )

    # Verify that the right-side detail is now slightly larger and that the
    # immutable viewport cache was installed.
    test_text = widget_tests.read_text(encoding="utf-8")
    insertion_point = """    assert widgets._history_frames[19].options[\"grid_columnspan\"] == 2
"""
    if insertion_point not in test_text:
        raise RuntimeError("Could not find twenty-row widget assertion insertion point")
    replacement = insertion_point + """    assert widgets._history_frames[0].children[1].options[\"font\"] == (\n        \"DejaVu Sans\",\n        21,\n        \"bold\",\n    )\n"""
    widget_tests.write_text(test_text.replace(insertion_point, replacement, 1), encoding="utf-8")
    print(f"PATCHED   {widget_tests}")

    print("PASS: Checkpoint 192 twenty-row DMR performance patch applied.")


if __name__ == "__main__":
    main()
