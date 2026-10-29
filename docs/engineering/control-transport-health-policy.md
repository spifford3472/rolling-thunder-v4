# Controller recovery policy foundation

## Status and ownership

Issue343 first implementation slice, October28. This pure module is now consumed only by the explicit serial_v2 recovery worker. Legacy serial remains unchanged. It grants no controller action or microphone authority. It does not repair the installed USB connection.
See [investigation](issue-343-controller-recovery-investigation.md) for live
observations and unresolved hardware/protocol gates.

control_transport_health.py owns only immutable health data and retry/session
lifecycle policy. The future hardware adapter must own serial I/O, freshness
validation, bounded worker/mailbox and actual device identity. The existing
ControlSource -> ControlDispatcher -> OperatorCommandController remains the sole
action path across all contexts. Healthy data grants no event or RF authority.

## Contract

An explicit monotonic timestamp drives every operation. Nonfinite, negative,
boolean or regressing values raise before mutation. Durations must be finite and
positive. Snapshot is a frozen detached value; one owner must serialize mutations.
No thread synchronization, I/O, queues, sleep or application callbacks exist.

start schedules the initial attempt immediately and is idempotent while active.
attempt_if_due returns a unique generation once, enters SYNCHRONIZING and clears
the retry deadline. A serial open alone cannot establish HEALTHY. Only a separate
validated_session notification matching the active generation can do so. Current
RTCTRL/1 has no such freshness handshake; do not fake this notification from an
open fd or ordinary EVENT. Host/firmware session validation needs separate work.

Both unfinished synchronization and missed validated heartbeat expire at the
configured threshold, default3seconds. Every timed operation evaluates expiry
before accepting new health; a late heartbeat/session indication cannot revive
an expired generation even if the scheduler did not previously poll. STALE retains
diagnostics and schedules retry; it never issues work automatically.

A current failure invalidates its generation, preserves at most256error characters
and schedules retries0.5/1/2/4/8seconds, capped8. Repeated obsolete failure results
cannot move that deadline. Healthy connection churn preserves backoff; only an
uninterrupted healthy interval of default10seconds resets it. A missed heartbeat
does not count as stable health. A future scheduler can add bounded injected jitter;
the pure policy uses deterministic delays. Thresholds are not deployed tuning.

stop invalidates active generation and cancels deadlines. Old results after stop
or restart cannot validate or fail a new connection. Generation numbers and total
attempt count never reset, while explicit new start resets the retry series.
Snapshots expose state, active generation orNone, next retry, last valid health
observation, totalattempt count and bounded last error. Diagnostics can survive a
stop; a new attempt clears the prior health time. Counters are cumulative and no
per-event history or unbounded collection is retained.

## Validation and remaining delivery

Tests cover exact/capped retry timing, one attempt per due deadline, duplicate and
old results, stop/restart, synchronization timeout, health expiry even without a
prior advance call, short churn versus stable reset, timestamp rejection for every
operation, constructor validation and detached frozen snapshots. Tests use fake
times and no hardware/network.

Before composition: implement one off-Tk serial worker with bounded I/O, mailbox,
shutdown/generation cancellation and health presentation. Resolve DTR/RTS behavior,
v2 freshness handshake and held-button handling; compile and review firmware;
prove stale action rejection and bounded deduplication, all physical mappings,
parked unplug/replug/reset and soak. Bluetooth remains a separate value gate.
No microphone recording or USB reset is part of this policy. Documentation merge
is not permission to deploy or enable recovery. Source rollback removes this
uncomposed module; no database/config/firmware rollback is needed for this slice.

## Implementation provenance

Owner requested Qwen. First bounded run emitted incomplete unexecuted tool markup
and no diff; its green baseline gates were rejected. A smaller fresh Qwen pass
wrote code/tests but failed9tests, then4after its revision; review also found
missing time validation, generation invalidation and incorrect test expectations.
The coordinator stopped that pass and retained its workspace. Primary Codex then
implemented and independently tested this policy under the repository Qwen-first
fallback rule. No Qwen draft is accepted as working code. Run identities:
20261028T213958618308Z-issue343-recovery-policy and
20261028T214639336389Z-issue343-retry-core. No coding worker remains.

Final coordinator validation:63focused tests; full suite3519passed/7skipped; Ruff, strict MyPy344sourcefiles and staged diff checks pass. No installed/hardware acceptance is claimed.

Next source slice: [recovery v2 candidate](controller-recovery-v2.md) adds the still-uncomposed worker and explicit development firmware target. Firmware source now has an opt-in v2 implementation; installed firmware/production behavior remain unchanged. The documented commissioning gates still apply.
