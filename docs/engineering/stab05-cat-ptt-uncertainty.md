# STAB-05 — CAT/PTT uncertainty and shutdown safety boundary

Status: **STAB-05B fail-closed CAT/PTT correction under CI; physical safety unverified**.

## Existing mechanism and invariant

The FT-891 CAT adapter (`src/rolling_thunder/ft891_radio.py`) owns one
`RLock` for serial operations. CP6/FT8-specific PTT capability calls the
same `_release_cp6_cat_ptt()` path and never authorizes general-purpose
transmission. When TX0 fails, the adapter preserves its asserted/uncertain internal flag
and reports `RT_PTT_RELEASE ... result=error`; a subsequent release may retry.
The STAB-05B correction additionally sets an explicit internal **uncertain**
latch that rejects further `PTT.key()` attempts, including after a partial
TX1 write and failed compensating TX0. Only the existing serialized owner
completing another TX0 write clears that latch. The result is permission to
consider a new, separately authorized software operation, **not** a physical
RX confirmation. Neither `transmitting=False` in a state snapshot nor
`TX0;` write success verifies the physical RF state independently.

## Offline evidence and limits

- `tests/test_ft891_ptt_release_timing.py`: measures lock/CAT sections
  and release success/failure diagnostics.
- `tests/test_shutdown_contention.py`: release waits for an unrelated
  CAT command to relinquish the lock.
- `tests/test_stab02_shutdown_failure_modes.py`: blocked TX0, lock
  contention, retry after failed radio disconnect.
- `tests/test_stab05_cat_ptt_uncertainty.py`: a failed PTT-close remains
  retryable and actively rejects new TX1 during uncertain state; failed
  disconnect, partial TX1 and failed compensating TX0 also remain inhibited;
  stalled lock does not emit premature success.
- `tests/test_pyserial_cat_transport.py`: timeout must be finite and no more
  than 60 seconds; default serial I/O timeout remains 1 second with the same
  configured bound for reads/writes in the PySerial factory.

**Hard constraint:** If the CAT lock or device command never completes, no
software-only timeout can guarantee that physical PTT has been deasserted.
No second CAT path, unsafe lock bypass, forced close of an in-flight serial
operation, or automatic RF keying is permitted. Treat state as **release
unverified**, not success. Observe physical rig transmit indicator and safe
RF behavior only under separately approved parked/supervised testing.

## Next corrective gate

1. The PySerial adapter has a configurable finite read/write timeout
   (default 1 second, typed config may allow up to 60 seconds). This timeout
   is **per blocking serial operation** and does not bound waiting for the
   radio's shared `RLock`, accumulated reads, stalled drivers, FT8 executor
   or the full 20-second systemd stop window. These remain separate timing
   domains for failure injection and parked validation.
2. A `TX0;` attempt normally uses the existing PySerial write timeout, but
   Python cannot enforce a hard bound on a permanently blocked driver/lock.
   Do not add a second CAT writer or claim the serial timeout guarantees
   physical de-keying.
3. Implement only the smallest proven correction; do not add general PTT,
   parallel CAT, new supervisor or indefinite retry loop.
4. Tests must distinguish failed, blocked, completed and physically unverified
   outcomes. Include repeated shutdown, immediate disable of further FT8
   authorization and an explicit operator recovery path.
5. Full Ruff/MyPy/pytest/diff gate, then owner-approved exact-SHA parked
   hardware acceptance before declaring safety complete.

An unconditional bounded shutdown guarantee remains **unproven**. This
explicit constraint is not resolved by the existing tests.

## Change history / rollback

2026-11-14: Added hardware-free error and lock-contention test evidence.
No production code, systemd settings, network, or radio configuration changes.
Revert this test/document change to roll back; no runtime restart required.

2026-11-14: STAB-05B adds explicit unverified-PTT latch, fail-closed rekey,
clear only on successful existing-owner TX0 retry, deterministic failure
injection and finite serial-timeout configuration validation. No new CAT
writer or automatic transmit retry. Rollback: revert these branch commits;
no host or hardware changes made. Release still requires parked approval.
