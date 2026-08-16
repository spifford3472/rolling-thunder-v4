"""Apply Checkpoint 192 DMR readability adjustments deterministically.

This patch is intentionally local-first: it updates only the DMR presentation,
its bounded history window, the DMR-only left-column layout, and associated tests.
It performs no network, database, or logging operations.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path} but found {count}: {old[:80]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED   {path}")


def main() -> None:
    dmr_ui = Path("src/rolling_thunder/dmr_ui.py")
    widgets = Path("src/rolling_thunder/dmr_widgets.py")
    ui_main = Path("src/rolling_thunder/ui_main.py")
    widget_tests = Path("tests/test_dmr_widgets.py")
    viewport_tests = Path("tests/test_dmr_ui.py")
    wiring_tests = Path("tests/test_dmr_dashboard_wiring.py")

    replace_once(
        dmr_ui,
        "_DEFAULT_MAX_HISTORY_ROWS = 4",
        "_DEFAULT_MAX_HISTORY_ROWS = 2",
    )

    replace_once(widgets, "_MAX_HISTORY_CARDS = 4", "_MAX_HISTORY_CARDS = 2")

    replacements = (
        ('font=("DejaVu Sans", 15, "bold"),\n            anchor="w",\n        )\n        self._health_label',
         'font=("DejaVu Sans", 24, "bold"),\n            anchor="w",\n        )\n        self._health_label'),
        ('textvariable=self._rf,\n            bg=_BACKGROUND,\n            fg=_BRIGHT,\n            font=("DejaVu Sans", 15, "bold"),',
         'textvariable=self._rf,\n            bg=_BACKGROUND,\n            fg=_BRIGHT,\n            font=("DejaVu Sans", 26, "bold"),'),
        ('textvariable=self._error,\n            bg=_BACKGROUND,\n            fg=_FAILURE,\n            font=("DejaVu Sans", 12, "bold"),',
         'textvariable=self._error,\n            bg=_BACKGROUND,\n            fg=_FAILURE,\n            font=("DejaVu Sans", 18, "bold"),'),
        ('text="CURRENT AUDIO",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 13, "bold"),',
         'text="CURRENT AUDIO",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 22, "bold"),'),
        ('textvariable=self._audio_idle,\n            bg=_CARD_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 16, "bold"),\n            anchor="center",\n            pady=5,',
         'textvariable=self._audio_idle,\n            bg=_FAILURE,\n            fg=_CARD_BACKGROUND,\n            font=("DejaVu Sans", 30, "bold"),\n            anchor="center",\n            pady=3,'),
        ('frame.grid(row=4 + card_index, column=0, sticky="ew", padx=4, pady=1)',
         'frame.grid(row=5 + card_index, column=0, sticky="ew", padx=4, pady=1)'),
        ('textvariable=callsign,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 22, "bold"),',
         'textvariable=callsign,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 44, "bold"),'),
        ('textvariable=detail,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 13, "bold"),',
         'textvariable=detail,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 22, "bold"),'),
        ('textvariable=alias,\n                bg=_CARD_BACKGROUND,\n                fg=_MUTED,\n                font=("DejaVu Sans", 12),',
         'textvariable=alias,\n                bg=_CARD_BACKGROUND,\n                fg=_MUTED,\n                font=("DejaVu Sans", 20),'),
        ('text="RECENT CALLERS",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 13, "bold"),',
         'text="RECENT CALLERS",\n            bg=_BACKGROUND,\n            fg=_MUTED,\n            font=("DejaVu Sans", 22, "bold"),'),
        (').grid(row=6, column=0, sticky="ew", padx=6, pady=(3, 1))',
         ').grid(row=7, column=0, sticky="ew", padx=6, pady=(3, 1))'),
        ('frame.grid(row=7 + card_index, column=0, sticky="ew", padx=4, pady=1)',
         'frame.grid(row=8 + card_index, column=0, sticky="ew", padx=4, pady=1)'),
        ('textvariable=callsign,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 16, "bold"),',
         'textvariable=callsign,\n                bg=_CARD_BACKGROUND,\n                fg=_BRIGHT,\n                font=("DejaVu Sans", 32, "bold"),'),
        ('textvariable=detail,\n                bg=_CARD_BACKGROUND,\n                fg=_MUTED,\n                font=("DejaVu Sans Mono", 11, "bold"),',
         'textvariable=detail,\n                bg=_CARD_BACKGROUND,\n                fg=_MUTED,\n                font=("DejaVu Sans Mono", 18, "bold"),'),
        ('font=("DejaVu Sans", 11, "bold"),\n            anchor="center",\n        ).grid(row=11,',
         'font=("DejaVu Sans", 16, "bold"),\n            anchor="center",\n        ).grid(row=10,'),
        ('font=("DejaVu Sans", 12, "bold"),\n            anchor="w",\n            justify="left",\n            wraplength=500,\n        ).grid(row=12,',
         'font=("DejaVu Sans", 18, "bold"),\n            anchor="w",\n            justify="left",\n            wraplength=500,\n        ).grid(row=11,'),
        ('font=("DejaVu Sans", 12, "bold"),\n            anchor="w",\n            justify="left",\n            wraplength=500,\n        )\n        self._commit_label.grid(row=13,',
         'font=("DejaVu Sans", 18, "bold"),\n            anchor="w",\n            justify="left",\n            wraplength=500,\n        )\n        self._commit_label.grid(row=12,'),
    )
    for old, new in replacements:
        replace_once(widgets, old, new)

    replace_once(
        widgets,
        """        self._audio_idle_label.grid_remove()\n        for index, frame in enumerate(self._audio_frames):\n""",
        """        receiving = not viewport.current_audio_idle\n        self._audio_idle.set(\n            \"RECEIVING DMR AUDIO\"\n            if receiving\n            else \"IDLE — NO ACTIVE DMR AUDIO\"\n        )\n        self._audio_idle_label.configure(\n            bg=_SUCCESS if receiving else _FAILURE,\n            fg=_CARD_BACKGROUND,\n        )\n        for index, frame in enumerate(self._audio_frames):\n""",
    )
    replace_once(
        widgets,
        """        if viewport.current_audio_idle:\n            self._audio_idle_label.grid()\n\n        for index, frame in enumerate(self._history_frames):\n""",
        """        for index, frame in enumerate(self._history_frames):\n""",
    )

    replace_once(
        ui_main,
        """    ticker.grid(row=1, column=0, columnspan=2, sticky=\"ew\")\n\n    def show_standard_context_body() -> None:\n""",
        """    ticker.grid(row=1, column=0, columnspan=2, sticky=\"ew\")\n\n    dmr_expanded_layout = False\n\n    def set_dmr_expanded_layout(enabled: bool) -> None:\n        \"\"\"Give DMR the full left-column height without disturbing other contexts.\"\"\"\n        nonlocal dmr_expanded_layout\n        if enabled == dmr_expanded_layout:\n            return\n        dmr_expanded_layout = enabled\n        if enabled:\n            logger.grid_remove()\n            context.grid_configure(row=0, rowspan=2, pady=(8, 12))\n            return\n        context.grid_configure(row=1, rowspan=1, pady=(4, 12))\n        logger.grid()\n\n    def show_standard_context_body() -> None:\n""",
    )
    replace_once(
        ui_main,
        """        selected_context = context_navigation.state\n\n        if selected_context.selected in {ContextId.POTA, ContextId.DX}:\n""",
        """        selected_context = context_navigation.state\n        set_dmr_expanded_layout(\n            selected_context.selected is ContextId.DMR\n            and dmr_panel_runtime is not None\n        )\n\n        if selected_context.selected in {ContextId.POTA, ContextId.DX}:\n""",
    )

    replace_once(
        viewport_tests,
        'assert len(viewport.history_cards) == 4\n    assert viewport.hidden_above_count == 0\n    assert viewport.hidden_below_count == 16',
        'assert len(viewport.history_cards) == 2\n    assert viewport.hidden_above_count == 0\n    assert viewport.hidden_below_count == 18',
    )
    replace_once(
        viewport_tests,
        'def test_selected_history_is_kept_inside_four_row_window() -> None:',
        'def test_selected_history_is_kept_inside_two_row_window() -> None:',
    )
    replace_once(
        viewport_tests,
        'assert len(viewport.history_cards) == 4\n    assert viewport.hidden_above_count == 4\n    assert viewport.hidden_below_count == 2',
        'assert len(viewport.history_cards) == 2\n    assert viewport.hidden_above_count == 6\n    assert viewport.hidden_below_count == 2',
    )

    replace_once(
        widget_tests,
        """    assert widgets._audio_idle_label.visible\n    assert not widgets._error_label.visible\n""",
        """    assert widgets._audio_idle_label.visible\n    assert widgets._audio_idle.get() == \"IDLE — NO ACTIVE DMR AUDIO\"\n    assert widgets._audio_idle_label.options[\"bg\"] == \"#ff7070\"\n    assert widgets._audio_idle_label.options[\"font\"] == (\n        \"DejaVu Sans\",\n        30,\n        \"bold\",\n    )\n    assert not widgets._error_label.visible\n""",
    )
    replace_once(
        widget_tests,
        """    assert not widgets._audio_idle_label.visible\n    assert widgets._audio_frames[0].visible\n""",
        """    assert widgets._audio_idle_label.visible\n    assert widgets._audio_idle.get() == \"RECEIVING DMR AUDIO\"\n    assert widgets._audio_idle_label.options[\"bg\"] == \"#42ff72\"\n    assert widgets._audio_frames[0].visible\n""",
    )
    replace_once(
        widget_tests,
        "assert len(widgets._history_frames) == 4",
        "assert len(widgets._history_frames) == 2",
    )

    replace_once(
        wiring_tests,
        '        "dmr_panel_runtime.stop()",\n',
        '        "dmr_panel_runtime.stop()",\n        "set_dmr_expanded_layout(",\n        "rowspan=2",\n',
    )

    print("PASS: Checkpoint 192 DMR readability patch applied.")


if __name__ == "__main__":
    main()
