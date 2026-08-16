"""Repair the two non-functional hygiene failures exposed by Checkpoint 192 #10F5.

This script is intentionally narrow. It removes one unused local variable from
the deterministic #10F5 patcher and normalizes the appended DMR monitor test to
exactly one trailing newline. It does not change production DMR behavior.
"""

from __future__ import annotations

from pathlib import Path


def main() -> None:
    patcher = Path("scripts/apply_checkpoint192_dmr_panel_polling_twenty_rows.py")
    monitor_tests = Path("tests/test_dmr_monitor.py")

    patcher_text = patcher.read_text(encoding="utf-8")
    stale = "    old_block = text[start:end]\n"
    count = patcher_text.count(stale)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one unused old_block assignment, found {count}."
        )
    patcher.write_text(patcher_text.replace(stale, "", 1), encoding="utf-8")
    print(f"PATCHED   {patcher}: removed unused old_block assignment")

    monitor_text = monitor_tests.read_text(encoding="utf-8")
    monitor_tests.write_text(monitor_text.rstrip() + "\n", encoding="utf-8")
    print(f"PATCHED   {monitor_tests}: normalized trailing newline")

    print("PASS: Checkpoint 192 #10F5 hygiene repair applied.")


if __name__ == "__main__":
    main()
