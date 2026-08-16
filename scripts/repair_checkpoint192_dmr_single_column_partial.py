"""Repair the partially applied Checkpoint 192 one-column DMR layout.

This recovery is specifically for the local state left by failed test #10F4:
- the DMR presentation model has already been converted to callsign + compact detail,
- history frames have already been moved to one full-width column,
- history label/font/footer/test adjustments were not yet applied.

The script completes only those remaining presentation/test edits. It performs
no network, database, logging, or runtime operations.
"""

from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path} but found {count}: {old[:100]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED   {path}")


def require_once(path: Path, text: str) -> None:
    count = path.read_text(encoding="utf-8").count(text)
    if count != 1:
        raise RuntimeError(
            f"Expected repaired prerequisite exactly once in {path}, found {count}: {text[:100]!r}"
        )
    print(f"VERIFIED  {path}: {text.splitlines()[0][:72]}")


def main() -> None:
    dmr_ui = Path("src/rolling_thunder/dmr_ui.py")
    widgets = Path("src/rolling_thunder/dmr_widgets.py")
    viewport_tests = Path("tests/test_dmr_ui.py")
    widget_tests = Path("tests/test_dmr_widgets.py")

    # Verify the three edits #10F4 completed before it stopped.
    require_once(dmr_ui, "callsign_line=record.callsign,")
    require_once(dmr_ui, "def _history_detail_line(")
    require_once(
        widgets,
        """            frame.grid(
                row=8 + card_index,
                column=0,
                columnspan=2,
                sticky="ew",
                padx=4,
                pady=1,
            )
            frame.grid_columnconfigure(0, weight=2)
            frame.grid_columnconfigure(1, weight=3)
""",
    )

    # Keep the history callsign at the already enlarged 34 pt and place the
    # compact 19 pt detail on the same row at the right side of the card.
    replace_once(
        widgets,
        """                font=("DejaVu Sans", 34, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="ew", padx=8, pady=(1, 0))
""",
        """                font=("DejaVu Sans", 34, "bold"),
                anchor="w",
            ).grid(row=0, column=0, sticky="w", padx=(8, 4), pady=0)
""",
    )
    replace_once(
        widgets,
        """                font=("DejaVu Sans Mono", 19, "bold"),
                anchor="w",
            ).grid(row=1, column=0, sticky="ew", padx=8, pady=(0, 1))
""",
        """                font=("DejaVu Sans", 19, "bold"),
                anchor="e",
            ).grid(row=0, column=1, sticky="e", padx=(4, 8), pady=0)
""",
    )

    # Ten history cards now occupy rows 8 through 17. Put status/footer rows
    # beneath them rather than overlapping history rows 13-15.
    replace_once(
        widgets,
        ').grid(row=13, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0))',
        ').grid(row=18, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0))',
    )
    replace_once(
        widgets,
        ').grid(row=14, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 0))',
        ').grid(row=19, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 0))',
    )
    replace_once(
        widgets,
        """        self._commit_label.grid(
            row=15, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0)
        )
""",
        """        self._commit_label.grid(
            row=20, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0)
        )
""",
    )

    # Update tests to the new compact model and full-width rows. These are the
    # exact stale expectations shown by #10F3/#10F4 output.
    replace_once(
        viewport_tests,
        'assert viewport.history_cards[0].callsign_line == "K0DMR - Operator 0"',
        'assert viewport.history_cards[0].callsign_line == "K0DMR"\n    assert viewport.history_cards[0].detail_line == "Operator 0 · TG3100 · TS1 · 5s · NET"',
    )
    replace_once(
        viewport_tests,
        'assert viewport.history_cards[-1].callsign_line.startswith("K7DMR")',
        'assert viewport.history_cards[7].callsign_line == "K7DMR"',
    )
    replace_once(
        widget_tests,
        """    assert widgets._history_frames[0].options["grid_row"] == 8
    assert widgets._history_frames[0].options["grid_column"] == 0
    assert widgets._history_frames[9].options["grid_row"] == 12
    assert widgets._history_frames[9].options["grid_column"] == 1
""",
        """    assert widgets._history_frames[0].options["grid_row"] == 8
    assert widgets._history_frames[0].options["grid_column"] == 0
    assert widgets._history_frames[0].options["grid_columnspan"] == 2
    assert widgets._history_frames[9].options["grid_row"] == 17
    assert widgets._history_frames[9].options["grid_column"] == 0
    assert widgets._history_frames[9].options["grid_columnspan"] == 2
""",
    )

    print("PASS: partial #10F4 one-column DMR layout repaired.")


if __name__ == "__main__":
    main()
