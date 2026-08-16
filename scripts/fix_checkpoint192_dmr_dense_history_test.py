"""Fix the stale two-row DMR history assertion after the ten-row layout patch."""

from pathlib import Path


path = Path("tests/test_dmr_ui.py")
text = path.read_text(encoding="utf-8")
old = 'assert viewport.history_cards[-1].callsign_line.startswith("K7DMR")'
new = 'assert viewport.history_cards[7].callsign_line.startswith("K7DMR")'
count = text.count(old)
if count != 1:
    raise RuntimeError(f"Expected exactly one stale DMR assertion, found {count}.")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
print("PASS: corrected stale ten-row DMR history assertion.")
