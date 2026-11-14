# USB diagnostic observer — source-controlled installation reference

## Ownership and safety

The standalone read-only observer was first installed as a temporary user service on anvilmobile. Its production source was inspected before repository integration on 2026-11-13. This repository version preserves the same sampling protocol, record names, command timeouts, five-second poll, 60-second heartbeat, and 10 MB × 6 total JSONL files. The only implementation adjustment is deferring logger creation until `main()` so importing the module in offline tests creates no files. It does not open USB endpoints, claim serial devices, send RF, or modify Rolling Thunder.

Source: `deploy/diagnostics/rt-usb-observer.py`; unit template: `deploy/diagnostics/rt-usb-observer.user.service`; tests: `tests/test_usb_observer.py`.

## Existing installed paths (not changed by this PR)

- Script: `/home/geoff/.local/bin/rt-usb-observer.py`
- User unit: `/home/geoff/.config/systemd/user/rt-usb-observer.service`
- Output: `/home/geoff/.local/state/rolling-thunder-diagnostics/usb-events.jsonl`

The unit template deliberately references the existing installed path, **not** a source checkout. Merging this PR does not deploy or restart the observer. Future install/upgrade must be a separately approved, parked, backed-up, atomic file replacement with SHA comparison, user-service restart and verified log continuity. Do not overwrite collected logs.

## Validation

Offline: `pytest -q tests/test_usb_observer.py`, `ruff check .`, `mypy src/rolling_thunder`, `pytest`, `git diff --check`. Verify on a parked Pi only after separate approval: compare running process and script checksums, inspect `systemctl --user status rt-usb-observer.service`, and confirm JSONL rotation and timestamps without touching hardware endpoints.

## Rollback

For any future install, preserve copies of both existing installed script and unit before replacing. Restore exact prior script and unit atomically, run `systemctl --user daemon-reload`, restart only `rt-usb-observer.service` after operator approval, verify observer heartbeat, and retain JSONL history. No dashboard or radio restart is required. If checks fail, stop only the observer and retain evidence.

## Change history

2026-11-13: Version-controlled observer and matching user unit added; **no production installation or restart**. QTH infrastructure change record is required for any subsequent actual host installation or modification.
