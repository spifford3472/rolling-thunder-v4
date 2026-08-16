"""Apply the Checkpoint 192 full-width ten-row DMR history layout.

This patch is intended to run after the local #10F3 dense-history patch. It
keeps ten visible history records but uses one full-width row per caller,
compacts each caller to a single visual row, slightly enlarges the row text,
and fixes the stale viewport assertion exposed by #10F3.
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
    viewport_tests = Path("tests/test_dmr_ui.py")
    widget_tests = Path("tests/test_dmr_widgets.py")

    replace_once(
        dmr_ui,
        """            callsign_line=_history_callsign_line(record.callsign, record.name),\n            detail_line=(\n                f\"{record.occurred_at.strftime('%H:%M:%SZ')}  \"\n                f\"TS{record.slot} TG{record.talkgroup}  \"\n                f\"{record.duration_s:.1f}s  {record.source.value.upper()}\"\n            ),\n""",
        """            callsign_line=record.callsign,\n            detail_line=_history_detail_line(\n                record.name,\n                slot=record.slot,\n                talkgroup=record.talkgroup,\n                duration_s=record.duration_s,\n                source=record.source.value.upper(),\n            ),\n""",
    )
    replace_once(
        dmr_ui,
        """def _history_callsign_line(callsign: str, name: str | None) -> str:\n    if name is None or not name.strip():\n        return callsign\n    return f\"{callsign} - {name.strip()}\"\n""",
        """def _history_detail_line(\n    name: str | None,\n    *,\n    slot: int,\n    talkgroup: int,\n    duration_s: float,\n    source: str,\n) -> str:\n    \"\"\"Build a compact one-line history detail that fits the mobile panel.\"\"\"\n    source_label = \"NET\" if source == \"NETWORK\" else source\n    metadata = f\"TG{talkgroup} · TS{slot} · {duration_s:.0f}s · {source_label}\"\n    if name is None or not name.strip():\n        return metadata\n    return f\"{name.strip()} · {metadata}\"\n""",
    )

    replace_once(
        widgets,
        """            frame.grid(\n                row=8 + (card_index // 2),\n                column=card_index % 2,\n                sticky=\"ew\",\n                padx=3,\n                pady=1,\n            )\n            frame.grid_columnconfigure(0, weight=1)\n\n            callsign = tk.StringVar(value=\"\")\n""",
        """            frame.grid(\n                row=8 + card_index,\n                column=0,\n                columnspan=2,\n                sticky=\"ew\",\n                padx=4,\n                pady=1,\n            )\n            frame.grid_columnconfigure(0, weight=2)\n            frame.grid_columnconfigure(1, weight=3)\n\n            callsign = tk.StringVar(value=\"\")\n""",
    )
    replace_once(
        widgets,
        """                font=(\"DejaVu Sans\", 32, \"bold\"),\n                anchor=\"w\",\n            ).grid(row=0, column=0, sticky=\"ew\", padx=8, pady=(1, 0))\n""",
        """                font=(\"DejaVu Sans\", 34, \"bold\"),\n                anchor=\"w\",\n            ).grid(row=0, column=0, sticky=\"w\", padx=(8, 4), pady=0)\n""",
    )
    replace_once(
        widgets,
        """                font=(\"DejaVu Sans Mono\", 18, \"bold\"),\n                anchor=\"w\",\n            ).grid(row=1, column=0, sticky=\"ew\", padx=8, pady=(0, 1))\n""",
        """                font=(\"DejaVu Sans\", 20, \"bold\"),\n                anchor=\"e\",\n            ).grid(row=0, column=1, sticky=\"e\", padx=(4, 8), pady=0)\n""",
    )

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
        """        self._commit_label.grid(\n            row=15, column=0, columnspan=2, sticky=\"ew\", padx=6, pady=(1, 0)\n        )\n""",
        """        self._commit_label.grid(\n            row=20, column=0, columnspan=2, sticky=\"ew\", padx=6, pady=(1, 0)\n        )\n""",
    )

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
        """    assert widgets._history_frames[0].options[\"grid_row\"] == 8\n    assert widgets._history_frames[0].options[\"grid_column\"] == 0\n    assert widgets._history_frames[9].options[\"grid_row\"] == 12\n    assert widgets._history_frames[9].options[\"grid_column\"] == 1\n""",
        """    assert widgets._history_frames[0].options[\"grid_row\"] == 8\n    assert widgets._history_frames[0].options[\"grid_column\"] == 0\n    assert widgets._history_frames[0].options[\"grid_columnspan\"] == 2\n    assert widgets._history_frames[9].options[\"grid_row\"] == 17\n    assert widgets._history_frames[9].options[\"grid_column\"] == 0\n    assert widgets._history_frames[9].options[\"grid_columnspan\"] == 2\n""",
    )

    print("PASS: Checkpoint 192 one-column ten-row DMR layout patch applied.")


if __name__ == "__main__":
    main()
