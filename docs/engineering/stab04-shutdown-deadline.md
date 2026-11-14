# STAB-04 — shutdown deadline and safety critical-path evidence

Status: **UI-priority correction proposed; broader safety gate unresolved**. This document is
a current-code analysis after STAB-03; it does not authorize a deployment, RF
test, change in systemd stop timeout, or additional CAT command path.

## Verified code paths

- `src/rolling_thunder/ui_main.py`: the SIGTERM handler queues the normal
  Tk-triggered close worker. `close_worker()` executes `_run_cleanup_steps`
  synchronously and in order. The STAB-04 candidate now invokes
  `runtime.stop()` first via `_run_orderly_shutdown`, followed by physical
  controls, callsign audio, Tron, OHGO, DMR, antenna, log panel, status,
  preferences and power worker. This prevents a *peripheral UI* callback
  from starving entry to the existing runtime cleanup, but a runtime-internal
  callback can still block indefinitely.
- `src/rolling_thunder/application_runtime.py`: once entered, the existing
  `stop()` attempts FT8 QSO/transmit cleanup first, then radio polling,
  band restoration and radio disconnect **before** unrelated worker stops.
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
| Peripheral UI callback never returns | `tests/test_stab04_shutdown_deadline_contract.py` | Proposed correction: runtime entered before peripheral callback, then stall is exposed truthfully |
| Stall logging for generic sequential cleanup | Same module | `step_start` without `step_end` or `cleanup_end` until unblocked |
| Runtime unrelated worker blocks after radio release | `tests/test_stab02_shutdown_failure_modes.py` | Candidate correction: radio disconnect is reached first; worker can still stall completion |
| CAT lock holder delays PTT release | STAB-02 CAT lock test | Characterization: no unauthorized competing TX0 path |
| Startup incomplete, connected radio | STAB-03 merged tests | Corrected in existing adapter; does not address blocked callbacks |
| 20-second hard real-time guarantee | No such guarantee exists in current implementation | **Not accepted** |

The tests use controlled events and bounded joins, **not** a real twenty-second
sleep or a physical radio. The prior strict xfail is replaced with a normal regression for **UI-level
ordering only**. This is not a passing runtime-internal or physical safety
acceptance.

## Gate and smallest candidate correction

1. Verify the proposed ordering/inhibition contract for physical controls,
   FT8 QSO activity, and runtime resource ownership. The UI and runtime now
   execute existing FT8 release and radio-owner cleanup ahead of unrelated
   callbacks, but control input inhibition and asynchronous worker races need
   additional deterministic evidence.
2. The candidate places the *safety-essential* radio/PTT release before
   best-effort, slower worker shutdown while preserving the single existing
   adapter. Do not reorder radio disconnect ahead of FT8 release, close CAT
   transport while another CAT operation owns it, or run a second CAT writer.
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

**Stop condition:** Do not market this as 'bounded shutdown' or deploy while
control-input inhibition and concurrent runtime-worker access remain unverified,
FT8/radio-owner cleanup itself can hang, or STAB-05's CAT-unavailable uncertainty
remains. Peripheral worker stalls no longer delay *entry* to the original radio
release path under this candidate; this is NOT a hard real-time guarantee. The UI-runtime-first candidate
has not independently proved FT8/PTT safety. The currently merged
STAB-03 partial-startup fix remains useful but does not close these gaps.

## Change history / rollback

2026-11-14: Added offline failure evidence and a deliberately failing desired
contract. No production code, host, service, or network configuration changed.
Rollback: revert the test/document commit; there is no installed-system effect.

2026-11-14: Proposed explicit runtime-first UI close ordering in the existing
single close worker; no new CAT/PTT command writer, systemd change or timer.
Acceptance remains blocked on the runtime-internal cleanup order and input
inhibition/race review. Roll back with the candidate commit before deployment.

2026-11-14: Runtime cleanup candidate now closes FT8 and existing radio owner
before unrelated network/GPS persistence workers. The original STAB-02 blocked
runtime worker characterization was updated to assert the new ordering. No
second radio path or supervisor was introduced; concurrent-input and parked
hardware acceptance remain mandatory.
