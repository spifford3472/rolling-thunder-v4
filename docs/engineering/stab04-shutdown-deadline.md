# STAB-04 — shutdown deadline and safety critical-path evidence

Status: **unresolved safety gate; offline characterization only**. This document is
a current-code analysis after STAB-03; it does not authorize a deployment, RF
test, change in systemd stop timeout, or additional CAT command path.

## Verified code paths

- `src/rolling_thunder/ui_main.py`: the SIGTERM handler queues the normal
  Tk-triggered close worker. `close_worker()` executes `_run_cleanup_steps`
  synchronously and in order. Physical controls, callsign audio, Tron, OHGO,
  DMR, antenna, log panel, status, preferences and power worker all precede
  `runtime.stop()`. Its per-step markers are truthful but cannot progress
  after a callback stops returning.
- `src/rolling_thunder/application_runtime.py`: once entered, the existing
  `stop()` attempts FT8 QSO/transmit cleanup first, then multiple workers
  before radio polling, band restoration, GPS and finally radio disconnect.
  It accumulates ordinary exceptions but does **not** time-limit a callback.
- The recorded installed systemd unit had `TimeoutStopSec=20`. This is a
  maximum service stop opportunity, **not** a deadline guarantee from Python
  and **not** proof of radio PTT release. A forced termination may occur
  before any `radio disconnect` step is reached.
- `src/rolling_thunder/ft891_radio.py`: CAT operations share one `RLock`.
  Neither forced termination nor arbitrary concurrent CAT bypass is a
  validated safety strategy. STAB-05 owns the stuck lock/TX0 investigation.

## Deterministic offline matrix

| Scenario | Evidence | Result |
| --- | --- | --- |
| Peripheral UI callback never returns | `tests/test_stab04_shutdown_deadline_contract.py` | Strict xfail against desired 'runtime reached' contract |
| Stall logging | Same module | `step_start` without `step_end` or `cleanup_end` until unblocked |
| Runtime unrelated worker blocks radio release | `tests/test_stab02_shutdown_failure_modes.py` | Characterization: radio disconnect delayed until worker unblocks |
| CAT lock holder delays PTT release | STAB-02 CAT lock test | Characterization: no unauthorized competing TX0 path |
| Startup incomplete, connected radio | STAB-03 merged tests | Corrected in existing adapter; does not address blocked callbacks |
| 20-second hard real-time guarantee | No such guarantee exists in current implementation | **Not accepted** |

The tests use controlled events and bounded joins, **not** a real twenty-second
sleep or a physical radio. A strict expected failure is an explicit open
requirement, never a passing safety acceptance.

## Gate and smallest candidate correction

1. Prove a deterministic ordering/inhibition contract for physical controls,
   FT8 QSO activity, and runtime resource ownership. No UI step should permit
   new commands after safety shutdown starts.
2. Separate the *safety-essential* radio/PTT release from best-effort, slower
   worker shutdown only after proving a single owner and safe thread ordering.
   Do not reorder radio disconnect ahead of FT8 release, close CAT transport
   while another CAT operation owns it, or run a second CAT writer.
3. Test blocked UI workers, blocked runtime workers, double close, cancellation
   and failure injection without a real radio. Require bounded eventual
   completion of the safely accessible essential path **under explicitly
   stated assumptions** (for example, CAT lock and transport available).
4. Explicitly classify the case where CAT lock/transport is permanently
   unavailable as **release unverified**; a software timeout cannot guarantee
   physical de-keying. Resolve with a separately approved physical fail-safe
   design or documented operator recovery before claiming unconditional safety.
5. Only after passing Ruff, MyPy, pytest and `git diff --check`, validate on
   a parked AnvilMobile using an exact SHA, protected rollback state, complete
   journal and observed UI/systemd ownership. FT-891 powered-on/RF testing
   requires separate explicit owner approval.

**Stop condition:** Do not merge a speculative production reorder or deploy a
release marketed as 'bounded shutdown' while either the strict xfail above or
STAB-05's CAT-unavailable uncertainty is outstanding. The currently merged
STAB-03 partial-startup fix remains useful but does not close these gaps.

## Change history / rollback

2026-11-14: Added offline failure evidence and a deliberately failing desired
contract. No production code, host, service, or network configuration changed.
Rollback: revert the test/document commit; there is no installed-system effect.
