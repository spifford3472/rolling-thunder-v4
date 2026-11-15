# STAB-07I — Actual dashboard composition with fake hardware on isolated ARM64

**Status:** Offline engineering candidate, November 15, 2026. **Production NO GO.**

STAB-07I executes the actual `rolling_thunder.ui_main.run_dashboard()` composition on the emulated ARM64 Debian 13 CPython 3.13.5 runtime. It exercises the genuine `ApplicationRuntime`, controller composition, Tk widgets, refresh loop, SQLite initialization, mock polling, readiness heartbeat, signal handling and shutdown.

## Isolation and safety boundary

- Forge development workspace: `/home/rt-remote/workspaces/rt-stab07`. The exact PR #461 head branch was fetched; its tree was verified identical to the local STAB-07H tree before STAB-07I was based directly on that head.
- QEMU sandbox: `/home/rt-remote/workspaces/rt-stab07g-sandbox`; private disposable STAB-07I trial copies: `/home/rt-remote/workspaces/rt-stab07i-run2/attempt*`. Each trial uses a new display and scratch directory; the runner refuses to overwrite a prior database or share an X server.
- Runner and guest probe: `deploy/rolling-thunder-arm64-dashboard-runner.py` and `deploy/rolling-thunder-arm64-dashboard-probe.py`. The runner compares the guest probe byte-for-byte with reviewed source and mounts the current application package read-only.
- The QEMU process uses the established unprivileged user/PID/network namespace, private Debian ARM64 sysroot and Python venv, minimal device tree, no station home/secrets/database mounts, and private Xvfb/Xauthority. Only loopback was visible inside the guest. No host package, service, firewall, Docker permission, or privileged setting changed.
- The validated test config explicitly selects MockRadio and MockGPS; disables FT8/PTT, speech, Tron, physical controls, Forge/home/network integrations, maps, radar, DMR, antenna reference and MeshCore. The status monitor uses its real lifecycle with fixed unavailable probes, not Internet probes.
- The dashboard creates only a deterministic synthetic `K1TEST` contact in `/test/scratch-dashboard.sqlite3`. The harness checks SQLite integrity and quick-check, preserves the fixture through orderly shutdown, creates a separate SQLite online backup and verifies it. It never imports station contacts or automatically restores any database.

## Full-dashboard ARM64 results

| Trial | Dashboard result | Verified evidence |
| --- | --- | --- |
| `normal` | Pass; application return code 0 | Five Tk widgets, fresh PID-bound heartbeat, two refresh callbacks, mock radio/GPS, SIGTERM, two close requests but one close worker, blocked DISCARD mutation rejected with pending callsign preserved, runtime closed, synthetic contact and online backup preserved, SQLite checks `ok`, radio polling stopped before disconnect and preference drain completed before executor stop. |
| `startup-failure` | Expected safe failure; application return code 3 | Injected after mock runtime startup and before Tk construction; no root created; runtime stopped and mock radio disconnected. |
| `cleanup-failure` | Expected refusal; application return code 4 | Injected background worker cleanup exception was reported; runtime closed; synthetic contact and SQLite integrity remained intact. |
| `missing-heartbeat` | Readiness refused; orderly application return code 0 | A deliberately stale heartbeat was rejected (`tk_ready=false`, `readiness_refused=true`); dashboard then received SIGTERM and completed mock shutdown. |
| `blocked-worker` | Expected refusal; harness return status 75 | A test-only mock cleanup callback stayed blocked. A bounded watchdog ended only the isolated QEMU test process before worker-end/UI-destroy markers; no successful shutdown report was emitted. This is not a claim that a blocked production worker can be safely killed. |

Generic unexpected guest exits, missing/duplicate evidence, wrong status codes, false readiness, false production/RF claims, missing fixtures, SQLite errors and misordered runtime shutdown markers are rejected by the runner. All final trials completed; a Forge process check found no surviving QEMU dashboard, Xvfb or bwrap test process.

The normal lifecycle takes about 7 seconds after guest startup; the emulated process startup dominates trial time. The environment is Debian package `deb13u5`, while AnvilMobile was observed on `deb13u4`; matching Python version strings are not exact runtime parity.

## Implementation corrections

The first full-dashboard run exposed duplicate preference draining: `ApplicationRuntime.stop()` had already stopped its owned executor before `ui_main.close_worker()` attempted another flush. The runtime now owns one bounded preference drain after the radio-release attempt and before stopping that executor; UI does not flush a stopped service.

The run also established that UI cleanup exceptions could be logged while `run_dashboard()` returned success. It now returns status 4 when orderly shutdown recorded an error. This is an error-reporting correction only; it does not claim physical radio receive or PTT release.

Relevant regression coverage:
- `tests/test_stab07i_preference_shutdown_order.py` — radio release, preference drain and executor stop ownership/order.
- `tests/test_stab07i_full_dashboard_probe.py` — readiness, widget/refresh, shutdown, mutation inhibition, database/backup preservation, startup/cleanup/stale-heartbeat/blocked-worker refusal, invalid evidence rejection.
- `tests/test_ui_main.py` — nonzero return on shutdown error.

## Regression results

- Full Forge pytest: **4,311 passed, 7 skipped**.
- Strict MyPy: **401 source files passed**.
- Scoped Ruff for all changed Python files: **passed**.
- Whole-repository `ruff check .`: four pre-existing findings remain in unchanged `deploy/diagnostics/rt-usb-observer.py` (EXE001, I001, UP017, BLE001). No unrelated USB observer change was made.
- `git diff --check HEAD`: **passed**, including staged and unstaged changes.
- GitHub exact-SHA CI and draft PR publication remain pending.

## Remaining gates

STAB-07I is offline composition evidence, not production acceptance. Outstanding gates include independent exact AnvilMobile interpreter/stdlib/native-library provenance; protected immutable root-owned release and trusted loaded-code attestation; deployment transaction/recovery acceptance; SQLite/WAL durability and interrupted recovery against disposable fixtures; production systemd identity; CAT/PTT/FT8 shutdown serialization; and owner-approved parked physical receive/de-key testing. No actual production database, radio, network service or AnvilMobile process was accessed.

**Rollback:** discard the unmerged STAB-07I draft branch and remove only the reviewed private trial directories. No production state changed. Any later change affecting 192.168.9.0/24, 192.168.10.0/24 or OPNsense still requires committed documentation in private `spifford3472/ki5vnb-qth-infrastructure`.

**Change history — 2026-11-15:** Hardened full-dashboard evidence, added shutdown error status, synthetic SQLite backup/integrity checks, post-shutdown mutation rejection and expected cleanup/readiness/blocked-worker refusals. Production remains NO GO.
