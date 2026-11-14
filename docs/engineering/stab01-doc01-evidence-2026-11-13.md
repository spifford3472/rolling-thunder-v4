# STAB-01 / DOC-01 — combined shutdown and documentation evidence baseline

Status: **partial read-only source and production inspection**, 2026-11-13. This is an evidence register, **not** a release certificate or approval to stop the dashboard. Update findings as additional source/tests and privileged live evidence become available. No RF, service restart, wrapper change, or database mutation was performed for this baseline.

## Architectural decision

Reliability through simplification. Before introducing a watchdog, another lifecycle manager, parallel CAT path, queue, GPS reader, or log pipeline, identify the already responsible owner and prove why its existing interface cannot meet the requirement. Prefer a smaller bounded correction, measured recovery, and explicit failure reporting. Distinguish demonstrated failures from hypothesis.

## Verified read-only production snapshot

- AnvilMobile production checkout: `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`; clean working tree at inspection.
- System-manager `rolling-thunder.service`: `LoadState=loaded`, `ActiveState=active`, `SubState=running`, `MainPID=60400`, `NRestarts=0`, `ControlGroup=/system.slice/rolling-thunder.service`.
- One matching `rolling-thunder-ui` process observed, PID 60400 with PPID 1. This proves a process and service membership, **not** interactive UI readiness or hardware safety.
- Installed unit readable section uses `deploy/rolling-thunder-autostart`, `Restart=on-failure`, `RestartSec=10`, `TimeoutStopSec=20`, `KillSignal=SIGTERM`, and 180 seconds minimum system uptime. At least one protected FT8 drop-in was unreadable without additional permission; do not infer its contents.
- The inspected Forge Codex workspace was at `1062bfbb87c5023e037832982ec91592037d95d2`, not the production SHA. It is **not** a current-source testing baseline until updated through an approved isolated workflow. No tests were run in it for this inspection.

## Shutdown dependency and blocking map — source observed

`src/rolling_thunder/ui_main.py` registers a SIGTERM handler that sets an `Event`. The Tk refresh loop handles the request and begins a single `rt-orderly-close` daemon worker. The worker runs `_run_cleanup_steps` **sequentially**, logs step-start and step-end evidence, signals completion, and the Tk thread destroys the root. A callback that never returns blocks later callbacks, regardless of logging. Systemd can force-terminate after its stop deadline.

UI-level order (source): physical controls -> callsign capture audio -> Tron microphone -> OHGO panel -> DMR -> antenna reference -> log panel -> status monitor -> operator preference flush -> power worker -> `application_runtime.stop`. This means even entry into runtime radio cleanup depends on earlier callbacks returning.

`src/rolling_thunder/application_runtime.py::stop` invokes sequential `attempt()` callbacks, catching ordinary exceptions but not timing out indefinitely blocked work. The normal started-path order is:

1. FT8 browser ranking, FT8 QSO, FT8 hardware transmit, FT8 receive
2. POTA enrichment/polling, weather/Forge polling and network keepalive
3. completed-QSO and FT8 attempt delivery, FT8 performance sync, contact sync, QRZ enrichment
4. platform health, radar/maps, callsign services, preferences, location publishing and clock sync
5. GPS polling, MeshCore GPS, **radio polling**, FT8 band restore, GPS disconnect, **radio disconnect**

Optional components are conditional; the exact callbacks invoked depend on initialized services. The not-started path is different: it closes FT8 QSO and FT8 hardware transmit and returns the current radio state without the normal disconnect sequence. This is a **review target** for partial-startup failure semantics, not yet a confirmed defect.

`src/rolling_thunder/ft891_radio.py` uses a shared `RLock` for CAT operations. `_release_cp6_cat_ptt` acquires that lock, then issues `TX0;` when its local asserted flag is true. Instrumentation reports separately `lock_wait_ms` and `cat_ms`, with `ok`, `error`, or `noop`. Failed CAT TX0 retains uncertain/asserted state so a subsequent release can retry; no evidence from a software flag alone proves physical de-keying. An unrelated blocking CAT operation can delay lock acquisition. **Do not add a second CAT command channel to bypass this lock.**

`tests/test_shutdown_contention.py` currently exercises PTT close waiting for a held CAT lock, verifies eventual `TX0;`, and documents that canceling a scheduled polling callback need not mean the callback finished. `tests/test_ft891_ptt_release_timing.py` tests successful and failed TX0 diagnostics and retryability. These are useful existing tests but do not establish bounded failure handling if the lock holder or CAT I/O never returns.

### Timeline evidence

The separately authorized 2026-11-13 parked shutdown with the FT-891 powered off logged `RT_RUNTIME_SHUTDOWN phase=end duration_ms=1412.5 errors=0`. FT8 transmit cleanup took 1154.0 ms; GPS polling cleanup took 236.9 ms. UI-level cleanup logged approximately 1415.5 ms. Radio disconnect was reached and reported approximately 0.2 ms. There was no `RT_PTT_RELEASE` event. This confirms **one successful hardware-off case** only. Earlier >20-second shutdown and forced termination remain relevant historical evidence; the precise stall step was not conclusively isolated.

## Initial DOC-01 discrepancy register

| ID | Documents | Evidence and classification | Action |
|---|---|---|---|
| DOC01-A | `issue-410-supervision-reconciliation.md` versus `system-architecture.md` and current `deploy/rolling-thunder-autostart` | **Historical / misleading if read as current**: earlier report calls the two `pgrep` checks a non-atomic singleton mechanism. Current source obtains an inherited, nonblocking `flock` before its uptime wait, and keeps `pgrep` as secondary unmanaged-process detection. | Keep historical incident intact; add a current-status/supersession pointer in the authoritative guide. Confirm installed launcher matches the source before claiming live atomic safety. |
| DOC01-B | `production-inventory-2026-11-13.md` versus `issue-410-wrapper-review-2026-11-13.md` | **Historical time-bound observation**: initial inventory says wrapper unreadable/uninspected, later operator-supplied wrapper snapshot and parked deployment evidence clarify behavior. | Cross-reference later review; do not erase dated original evidence or claim a cryptographic wrapper verification. |
| DOC01-C | `system-architecture.md` | **Formatting defect**: launcher paragraph includes literal `\\n\\n` rather than paragraph breaks. | Correct in separately scoped DOC-02 editing; no architectural change. |
| DOC01-D | `shared-component-contracts.md` | **Possible editorial duplication**, with adjacent descriptions of the Forge propagation inbox (one says undeployed, another disabled). | Verify exact current feature gate and installed status; consolidate contradictory current-state wording rather than guessing. |
| DOC01-E | `docs/FT8_ENGINEERING_GUIDE.md` | **Status potentially stale**: heading still describes an earlier CP9.1 engineering-guide source and future printable guide; subsystem has evolved. | Reconcile version/status against current source and tests, avoiding a broad rewrite. |
| DOC01-F | `production-inventory-2026-11-13.md` | **Operational follow-up**: observed Forge PSK autoqueue oneshot failure with a scheduled timer, impact and cause unknown. | Keep separate from shutdown fixes; read-only queue/job investigation before any change. |

Draft PR #414 contains an initial architecture evidence ledger and CI inventory scope. Review it before implementing CI or sweeping documentation changes; do not merge or close it as part of this task.

## Complexity ledger (initial)

| Existing mechanism | Evidence | Action |
|---|---|---|
| System-level systemd supervisor | Installed unit and running MainPID | Retain; original user-vs-system manager confusion is resolved |
| Inherited launcher flock | Current source | Retain; validate installed identity and collision tests before another singleton solution |
| Secondary launcher pgrep | Current source | Retain pending review; distinguish unmanaged instance detection from lock ownership |
| Sequential UI/runtime cleanup | Current source | Investigate blocking behavior and safety-critical ordering; no speculative supervisor |
| Shared FT-891 CAT RLock | Current source | Retain a single command authority; design offline bounded-contention tests |
| Structured shutdown and PTT logs | Current source and parked journal | Extend existing evidence only when a concrete missing field is demonstrated |

**New production mechanisms introduced: zero.**

## Prioritized next offline acceptance

1. **Safety-critical:** Test shutdown with a permanently held CAT lock, CAT TX0 hang/failure, and uncertain PTT state. Specify the observable fail-closed outcome, not a false guarantee of radio de-keying.
2. **Safety-critical:** Test a callback that never returns before `application_runtime.stop`, and partial-startup shutdown; determine whether safety-essential cleanup can be reached within the service deadline without parallel unauthorized CAT access.
3. **Reliability:** Verify GPS cancellation and worker joins under blocked callbacks, and repeated concurrent shutdown requests.
4. **Supervision:** Test concurrent launcher lock owners, unmanaged UI, early uptime, system-level MainPID/cgroup, and readiness distinctions. Do not install a watchdog yet.
5. **Documentation:** Reconcile the dated historical records with one authoritative current guide and align PR #414's remaining CI scope.

Acceptance requires deterministic hardware-free tests, preservation of current FT8 and CAT/PTT authority, honest failure state, no duplicate dashboard, and the repository-standard Ruff/MyPy/pytest/diff checks on the exact tested source. A parked FT-891-on acceptance is a **separate operator-approved boundary**. Do not shorten `TimeoutStopSec=20` merely because one parked stop was fast.

## Change log and rollback

2026-11-13: Added a documentation-only baseline based on read-only live service/process inspection, current source paths, existing tests, and prior dated evidence. No infrastructure or application change. Revert this commit to roll back the documentation; no production restart is involved. If a future host configuration change affects the defined QTH subnets or OPNsense, commit the required separate private infrastructure change record.
