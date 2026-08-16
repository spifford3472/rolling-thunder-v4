"""Apply Checkpoint 192 ten-caller DMR history layout adjustments.

This deterministic patch is intended to run after
apply_checkpoint192_dmr_readability.py. It keeps the full-height DMR layout and
steady red/green audio banner, expands the visible recent-call window to ten,
places history cards in a two-column by five-row grid, and nudges primary DMR
text sizes upward. It performs no network, database, or logging work.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path} but found {count}: {old[:90]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED   {path}")


def main() -> None:
    dmr_ui = Path("src/rolling_thunder/dmr_ui.py")
    widgets = Path("src/rolling_thunder/dmr_widgets.py")
    widget_tests = Path("tests/test_dmr_widgets.py")
    viewport_tests = Path("tests/test_dmr_ui.py")

    replace_once(
        dmr_ui,
        "_DEFAULT_MAX_HISTORY_ROWS = 2",
        "_DEFAULT_MAX_HISTORY_ROWS = 10",
    )
    replace_once(widgets, "_MAX_HISTORY_CARDS = 2", "_MAX_HISTORY_CARDS = 10")

    # Give the DMR frame two equal history columns. All non-history rows span both.
    replace_once(
        widgets,
        """        self._frame.grid_columnconfigure(0, weight=1)\n\n        self._health = tk.StringVar(value=\"STARTING\")\n""",
        """        self._frame.grid_columnconfigure(0, weight=1, uniform=\"dmr-history\")\n        self._frame.grid_columnconfigure(1, weight=1, uniform=\"dmr-history\")\n\n        self._health = tk.StringVar(value=\"STARTING\")\n""",
    )

    span_replacements = (
        ('self._health_label.grid(row=0, column=0, sticky="ew", padx=6, pady=(0, 1))',
         'self._health_label.grid(row=0, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 1))'),
        (').grid(row=1, column=0, sticky="ew", padx=6, pady=(0, 1))',
         ').grid(row=1, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 1))'),
        ('self._error_label.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 2))',
         'self._error_label.grid(row=2, column=0, columnspan=2, sticky="ew", padx=6, pady=(0, 2))'),
        (').grid(row=3, column=0, sticky="ew", padx=6, pady=(1, 1))',
         ').grid(row=3, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 1))'),
        ('self._audio_idle_label.grid(row=4, column=0, sticky="ew", padx=4, pady=1)',
         'self._audio_idle_label.grid(row=4, column=0, columnspan=2, sticky="ew", padx=4, pady=1)'),
        ('frame.grid(row=5 + card_index, column=0, sticky="ew", padx=4, pady=1)',
         'frame.grid(row=5 + card_index, column=0, columnspan=2, sticky="ew", padx=4, pady=1)'),
        (').grid(row=7, column=0, sticky="ew", padx=6, pady=(3, 1))',
         ').grid(row=7, column=0, columnspan=2, sticky="ew", padx=6, pady=(3, 1))'),
    )
    for old, new in span_replacements:
        replace_once(widgets, old, new)

    replace_once(
        widgets,
        'frame.grid(row=8 + card_index, column=0, sticky="ew", padx=4, pady=1)',
        'frame.grid(\n                row=8 + (card_index // 2),\n                column=card_index % 2,\n                sticky="ew",\n                padx=3,\n                pady=1,\n            )',
    )

    # Rows 8-12 are now the five history rows; move the footer beneath them.
    replace_once(
        widgets,
        ').grid(row=10, column=0, sticky="ew", padx=6, pady=(1, 0))',
        ').grid(row=13, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0))',
    )
    replace_once(
        widgets,
        ').grid(row=11, column=0, sticky="ew", padx=6, pady=(2, 0))',
        ').grid(row=14, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 0))',
    )
    replace_once(
        widgets,
        'self._commit_label.grid(row=12, column=0, sticky="ew", padx=6, pady=(1, 0))',
        'self._commit_label.grid(\n            row=15, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0)\n        )',
    )

    # Slightly enlarge primary readability while retaining ten visible callers.
    font_replacements = (
        ('font=("DejaVu Sans", 24, "bold"),\n            anchor="w",\n        )\n        self._health_label',
         'font=("DejaVu Sans", 26, "bold"),\n            anchor="w",\n        )\n        self._health_label'),
        ('textvariable=self._rf,\n            bg=_BACKGROUND,\n            fg=_BRIGHT,\n            font=("DejaVu Sans", 26, "bold"),',
         'textvariable=self._rf,\n            bg=_BACKGROUND,\n            fg=_BRIGHT,\n            font=("DejaVu Sans", 28, "bold"),'),
        ('text="CURRENT AUDIO",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 22, "bold"),',
         'text="CURRENT AUDIO",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 24, "bold"),'),
        ('textvariable=self._audio_idle,\n            bg=_FAILURE,\n            fg=_CARD_BACKGROUND,\n            font=("DejaVu Sans", 30, "bold"),',
         'textvariable=self._audio_idle,\n            bg=_FAILURE,\n            fg=_CARD_BACKGROUND,\n            font=("DejaVu Sans", 34, "bold"),'),
        ('textvariable=callsign,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 44, "bold"),',
         'textvariable=callsign,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 48, "bold"),'),
        ('textvariable=detail,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 22, "bold"),',
         'textvariable=detail,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 24, "bold"),'),
        ('textvariable=alias,\n                bg=_CARD_BACKGROUND,\n                fg=_MUTED,\n                font=("DejaVu Sans", 20),',
         'textvariable=alias,\n                bg=_CARD_BACKGROUND,\n                fg=_MUTED,\n                font=("DejaVu Sans", 22),'),
        ('text="RECENT CALLERS",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 22, "bold"),',
         'text="RECENT CALLERS",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 24, "bold"),'),
    )
    for old, new in font_replacements:
        replace_once(widgets, old, new)

    # Viewport tests now expect ten visible records before rotary scrolling.
    replace_once(
        viewport_tests,
        'assert len(viewport.history_cards) == 2\n    assert viewport.hidden_above_count == 0\n    assert viewport.hidden_below_count == 18',
        'assert len(viewport.history_cards) == 10\n    assert viewport.hidden_above_count == 0\n    assert viewport.hidden_below_count == 10',
    )
    replace_once(
        viewport_tests,
        'def test_selected_history_is_kept_inside_two_row_window() -> None:',
        'def test_selected_history_is_kept_inside_ten_row_window() -> None:',
    )
    replace_once(
        viewport_tests,
        'assert len(viewport.history_cards) == 2\n    assert viewport.hidden_above_count == 6\n    assert viewport.hidden_below_count == 2\n    assert viewport.history_cards[-1].selected',
        'assert len(viewport.history_cards) == 10\n    assert viewport.hidden_above_count == 0\n    assert viewport.hidden_below_count == 0\n    assert viewport.history_cards[7].selected',
    )

    replace_once(
        widget_tests,
        'assert len(widgets._history_frames) == 2',
        'assert len(widgets._history_frames) == 10\n    assert widgets._history_frames[0].options["grid_row"] == 8\n    assert widgets._history_frames[0].options["grid_column"] == 0\n    assert widgets._history_frames[9].options["grid_row"] == 12\n    assert widgets._history_frames[9].options["grid_column"] == 1',
    )
    replace_once(
        widget_tests,
        '        30,\n        "bold",\n    )',
        '        34,\n        "bold",\n    )',
    )

    print("PASS: Checkpoint 192 ten-caller DMR layout patch applied.")


if __name__ == "__main__":
    main()
