# Issue #345 measurement handoff — October 26, 2026

Status: **OPEN; probe installed and one real but unlabeled capture measured; field
comparison and physical acceptance remain incomplete.** No runtime correction is
justified by this packet. No RF, CAT/PTT action, host/service/network action,
production-data exercise, merge, push, or deployment was performed against either
production host by this source worker.

## Identity, retained evidence, and gates

The source worker is based at
`f03c48198ce30d07c6e26a8d12241c9281fdf51f`. Before cutover the Pi was clean at
`25dc3ea4e004719852b08853f707697b93a4017f`, active, with
`RT_R1A_UI_TIMING=1`; that release already contained popup PR #360 and offline
logging PR #361. The approved controller deployed the probe commit
`d271d065e5ee75282f326a50016648eed8f88f03` at 07:26:53 EDT. Independent readback
reported that exact clean target, active/running service, and `NRestarts=0`.
Installed `d271d06` is six commits behind source `f03c481`, but the intervening
changes are Forge #353 scheduling work only: the #345 UI timing, map, controls and
FT8 source/test paths are identical.

- **Gate A — CAT/PTT/FT8 timeline: incomplete live correlation.** Source retains
  the one-QSO authorization, fail-closed preparation and release paths and the
  existing 0.980 s safe-start guard unchanged. Existing tests are no-RF evidence;
  no transmission was authorized. The exported packet has no FT8
  `boundary_lateness_ms`, `periods_dropped`, CAT or PTT timeline, so it cannot show
  whether a UI tail affected an FT8 boundary or radio operation.
- **Gate B — popup/UI responsiveness: partial.** PR #360 behavior and regressions
  are installed, and the fine UI probe now has real Pi records. Still missing is
  owner physical acceptance on the 1280x720 display for POTA/DX/FT8 popup
  open-dismiss-rearm behavior and their encoder/context-button controls, plus a
  labeled radar-off/radar-on/Forge-slow comparison. Tests and timing records do not
  substitute for that observation.
- **Gate C — offline logging/recovery: complete for this issue slice.** PR #361's
  integrated test holds network upload while an ordinary local commit completes,
  reconstructs ordinary and FT8 durable rows/retry state, and proves reconnect/lost
  response idempotency. Preserve that evidence; do not fabricate outages or repeat
  production backup/restore/contact drills. The probe deployment separately created
  `/var/backups/rolling-thunder-deploy/rolling-thunder-20261026T112633Z-25dc3ea4e004719852b08853f707697b93a4017f.db`;
  schema 21, integrity and foreign-key checks passed.

The Oct. 22 authoritative field evidence remains: a 20,376.76 ms refresh, a
19,322.61 ms broad `map_prepare` interval, more than 10 seconds in `map_update`,
and a 3,501.56 ms `controls` interval. The deterministic source reproduction still
proves synchronous `PhotoImage` can retain its caller, not that it caused any one
field incident. Popup, offline durability and recovery evidence are retained rather
than rerun.

## October 26 measurement and ranked interpretation

Private capture metadata declares source `d271d065...`, condition `unlabeled`, 207
rows at export time, `controlled_radar_comparison=false`, and
`operator_acceptance=false`. The later read-only file contained 238 valid timing
records: 37 refresh rolling-window reports and 18 rate-limited slow-refresh records.
Across overlapping refresh windows, the *reported* p95 values ranged 26.02–38.45 ms
and the reported maxima ranged 41.79–174.20 ms. These windows overlap; their p95s
must not be averaged or reinterpreted as global p50/p95/p99. Slow records are a
selected sample, not all callbacks or operator end-to-end latency.

1. **Map overlay/status canvas — measured current boundary; mechanism inferred.**
   In refresh ID 397, the 174.20 ms refresh contained 121.17 ms `map_update` and
   115.79 ms `overlay_status_canvas`. Same-ID correlation supports attribution to
   that fixed synchronous Tk/canvas region. It does not distinguish Tk execution,
   display-server wait, descheduling or resource pressure, and it does not justify
   a rendering refactor yet.
2. **Presentation/context widgets — measured broad boundaries; cause unresolved.**
   Refresh ID 118 assigned 144.65 of 167.33 ms to `context_widgets`. ID 4422
   assigned 88.70 ms to `presentation` and, separately in that same refresh, 50.93
   ms to `map_update` (50.67 ms `overlay_status_canvas`). These maxima are not
   combined across IDs. The broad presentation/context internals are not split by
   the current probe, so a particular widget or lock remains inference.
3. **Historical map preparation/controls — measured historically, not reproduced
   at prior severity.** Current selected-record maxima were 9.61 ms
   `map_prepare` and 15.64 ms `controls`, both in ID 341; none of the 18 records
   contained an accepted-action token. This neither erases the Oct. 22 multi-second
   observations nor identifies their action/lock/resource cause. Current radar
   rolling records reported p95 0.02–0.06 ms and max 0.05–0.22 ms, but the condition
   is unlabeled and no slow record performed radar image materialization; this is
   not evidence for radar-off versus radar-on causality or improvement.

## Exact next packet, acceptance, and recovery

Park the vehicle and keep FT8 receive-only. On the same exact installed SHA, collect
separate bounded exports explicitly declared by the operator as `radar_off`, then
`radar_on` after a cached frame is visibly present, and `forge_slow` only if that
condition occurs naturally or is separately approved—do not create a production
network outage. Record capture start/end, SHA, timing-row/byte limits, display size,
radar state and whether FT8 receive was active. In each window retain the matching
FT8 diagnostic snapshot (`boundary_lateness_ms`, `periods_dropped`, clock health)
and correlate only within the same capture and refresh ID. Compare the reported
rolling windows as windows; do not average them into global percentiles.

On the physical 1280x720 display, separately verify POTA and DX encoder movement,
band/mode buttons, accepted selection popup, dismissal and same-station rearm; then
verify FT8 encoder browse, accepted CQ popup, band button dismissal, incoming-call
Button 2/3 presentation without answering/transmitting, Back/context departure, no
clipping, and visible control response. This acceptance is **not yet performed**.

The exact installed probe/redeployment candidate is
`d271d065e5ee75282f326a50016648eed8f88f03`; the source handoff branch adds only
the offline reporter, tests and documentation on
`f03c48198ce30d07c6e26a8d12241c9281fdf51f` and still requires controller
commit/push/review. Recovery references are prior exact Pi SHA
`25dc3ea4e004719852b08853f707697b93a4017f`, the database backup above, and the
approved deployment wrapper documented in `codex-deployment-workflow.md`; do not
bypass it.
If the labeled packet cannot be collected safely, stop here with #345 open. Do not
make a speculative production rendering, CAT/PTT, FT8 timing, or shared-policy fix.
