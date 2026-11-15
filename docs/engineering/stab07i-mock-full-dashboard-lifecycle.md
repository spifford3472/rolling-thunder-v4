# STAB-07I — Actual dashboard composition with fake hardware on isolated ARM64

**Status:** Offline review candidate, November 14, 2026. **Production NO GO.**

STAB-07I extends the STAB-07H Tk-helper tests by executing the actual installed `rolling_thunder.ui_main.run_dashboard()` on the emulated ARM64 Python 3.13.5 runtime, with the genuine `ApplicationRuntime`, widget construction, refresh loop, SQLite initialization, worker lifecycle, Tk readiness, SIGTERM and shutdown.

This is intentionally **not** an all-feature test: the test config disables physical radio/GPS, FT8, PTT, speech/Tron, physical controls, Forge/network clients, DMR, maps/radar and MeshCore. Their live behavior, including physical RX/de-key, remains unverified.

## Safe execution environment

- Forge, via Desktop Commander, using STAB-07G's verified AArch64 QEMU, private Python venv with 26 hashed ARM64 dependencies, and STAB-07H's rootless user/PID/**network**-isolated Xvfb.
- `deploy/rolling-thunder-arm64-dashboard-probe.py` constructs a Pydantic-validated mock radio/GPS configuration. A private test-only hook substitutes `load_config` and empty `ApplicationSecrets`, records a real Tk heartbeat, sends SIGTERM and observes complete shutdown. It refuses real serial devices or inherited station credentials.
- `deploy/rolling-thunder-arm64-dashboard-runner.py` checks the QEMU/Xvfb identities and byte-for-byte reviewed probe, permits only `normal` and `startup-failure`, refuses existing display sockets/DB, launches a fresh authenticated private Xvfb, bounds the guest's lifetime, and cleans its own process group/socket. It rejects missing phases, false production readiness and normal-shutdown errors.
- Every test database is synthetic under private `/test/scratch-dashboard.sqlite3`. No production SQLite, QSO, systemd, CAT/PTT, host package, network setting or radio device was accessed.

## A real shutdown bug found and corrected

The first real dashboard run on the STAB-07G installed wheel reached Tk readiness and exited with code 0, but logged:
`Rolling Thunder shutdown error: operator preferences: queued operator preferences did not drain`.

Cause: `ApplicationRuntime.stop()` had already stopped its owned `OperatorPreferenceService` executor. Then `ui_main.close_worker()` tried to flush that stopped service, which returned false even when no queued writes were pending.

Smallest correction: the **runtime owner** now performs one bounded 3-second preference flush **after the existing radio/FT8 cleanup path** and **before** stopping the preference executor. A failure is recorded explicitly, remaining cleanup still runs. The duplicate post-stop UI flush is removed. Radio/CAT/PTT authority and cleanup priority are unchanged.

`tests/test_stab07i_preference_shutdown_order.py` asserts mock radio disconnect precedes drain and stop, single ownership and explicit failed-drain reporting. `tests/test_stab07i_full_dashboard_probe.py` checks required real-dashboard evidence, failure/refusal, no false RF acceptance, and startup rollback.

## ARM64 acceptance observed

A new locally built noneditable application wheel was installed **only** into the disposable Forge ARM64 venv using `--no-index --no-deps --require-hashes --force-reinstall`. Test-only wheel SHA256: `7d794ff65ba259b0aad4d9fa56ddbc397cda16cc965d0d38e9a2515ce5bbae02`. This is not an approved signed deployment artifact.

| Mode | Observed result | Interpretation |
| --- | --- | --- |
| `normal` | `run_dashboard` code 0; real Tk root, heartbeat, SIGTERM; mock runtime and UI cleanup complete; **no shutdown errors** | PASS for this disabled-hardware configuration |
| `startup-failure` | Injected exception after mock radio polling start; code 3; mock radio disconnected and runtime stopped; no Tk root created | PASS expected safe refusal |

The same normal configuration before the source fix exposed the preference-drain bug, providing an independent before/after regression observation. No full-feature or real-device test is claimed.

Forge scratch paths:
- Existing QEMU/venv: `/home/rt-remote/workspaces/rt-stab07g-sandbox`
- Initial dashboard test: `/home/rt-remote/workspaces/rt-stab07i-display`
- Failure rollback: `/home/rt-remote/workspaces/rt-stab07i-failure-display`
- Updated normal: `/home/rt-remote/workspaces/rt-stab07i-normal-final`
- Test wheel and offline installation log: `/home/rt-remote/workspaces/rt-stab07i-artifacts`

Use the runner only with a fully reviewed, privately reconstructed scratch sandbox; it intentionally refuses reuse of a prior database or X server. The emulated Debian Python package remains `deb13u5` versus the Pi's observed `deb13u4`.

## Validation and remaining NO GO gates

Normal CI exercises the deterministic safety/failure tests; actual ARM64/Xvfb trials are additional Forge-local evidence. The STAB-07F immutable candidate was independently verified previously, but no actual protected production rollback was attempted.

Still outstanding: independently matching exact Pi interpreter/OS/native library bytes, full real hardware adapter and FT8 lifecycle, physical receive/PTT proof after abnormal release, sound/Tk screen responsiveness on the real monitor, SQLite/WAL QSO preservation, approved signed immutable root-owned release, trusted running code attestation and parked systemd stop/rollback acceptance. None may be inferred from a mock-radio dashboard shutdown.

**Rollback:** Abandon the unmerged draft branch and remove only reviewed disposable Forge scratch artifacts. There is no AnvilMobile change to undo. Any future changes affecting 192.168.9.0/24, 192.168.10.0/24 or OPNsense require committed documentation in private `spifford3472/ki5vnb-qth-infrastructure` listing configuration paths, integrations, jobs, validation, rollback and change history.

**Change history — 2026-11-14:** First actual ARM64 mock-dashboard composition; exposed and corrected double preference drain, added startup failure/rollback and strict harness regressions. **Production NO GO.**
