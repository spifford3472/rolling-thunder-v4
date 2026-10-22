# Issue 345 source trace and isolated blocking reproduction

Date: 2026-10-22. Scope: owner-approved diagnostic slice only. This document
does not authorize a production change, deployment, service restart, load test,
hardware probe, RF transmission, CAT/PTT operation, clock change, or any change
to FT8 deadlines, attempts, authorization, or transmit behavior. Issue #359
remains deferred.

## Evidence boundaries

The production evidence is the verified 03:30–05:00 EDT journal summary in
issue #345 comment `6343565345`. It contains rate-limited correlated records,
not an all-callback distribution. The directly observed facts are:

- whole-refresh maxima reached 20,376.76 ms;
- individual records assigned as much as 19,322.61 ms to the broad
  `map_prepare` checkpoint interval;
- individual records assigned more than 10 seconds to `map_update`; and
- one record assigned 3,501.56 ms to `controls`.

Those measurements establish production UI-thread elapsed time at the broad
boundaries. They do not distinguish CPU execution from descheduling, GIL
contention, lock wait, Tk/display-server wait, or storage/provider I/O, and they
do not prove one mechanism caused every event.

The deployed checkout was clean/detached at
`1f2f7c5c739757bd2e5746aa10597b8b9440bf27`. The investigation branch began at
current main `5572872dee7ddd937ad5ff959714fdb603092908`. The deployed SHA is an
ancestor of current main. A path-limited diff is empty for `ui_main.py`,
`application_runtime.py`, `live_map_ui.py`, `live_map_service.py`,
`live_radar_service.py`, `control_dispatcher.py`, `operator_commands.py`,
`ft8/receive.py`, `ft8/panel.py`, their focused tests, and
`r1-a-ui-timing.md`. The only intervening source changes are unrelated Forge
VOACAP/performance work. Therefore the trace below applies to both exact SHAs.

## Synchronous callback path

`ui_main.refresh()` runs on the Tk thread and calls these broad phases in order:

1. `ControlDispatcher.dispatch_available()` drains the source and invokes every
   accepted `OperatorCommands.execute()` inline. The source drain is intended to
   be nonblocking, but the dispatcher imposes no asynchronous boundary or
   per-refresh command budget. Any slow command handler, or a large accepted
   batch, extends `controls` and delays every later Tk event.
2. The interval labelled `map_prepare` contains substantially more than map
   preparation: radio-state synchronization, tune/repeater/DMR completion
   synchronization, retained weather and alert projection, GPS snapshot and map
   controller projection, map/POTA/radar viewport requests and immutable-state
   reads, plus FT8 panel/receive snapshot and selected-target presentation.
3. `LiveMapWidgets.update()` runs inline as `map_update`. It performs canvas
   mutation and bounded pending base/radar image materialization, followed by
   POTA, vehicle, health, status, and FT8 banner drawing.

The following operations are synchronous on the Tk caller in `map_update`:

- `_photo_for_tile()` and `_radar_photo_for_tile()` execute
  `b64encode(png).decode("ascii")` and `tk.PhotoImage(data=...)`;
- `_upsert_tile()` / `_upsert_radar_tile()` then execute canvas image creation;
- POTA label projection executes canvas text creation/configuration and `bbox()`;
- overlay/status work executes canvas delete/create/configure/coordinate calls.

The base and radar queues limit new image construction to two tiles each per
refresh. That bounds count, not duration: each Tk/image/canvas call remains a
synchronous operation with no hard elapsed-time bound.

## Lock and I/O ownership trace

No provider, filesystem, SQLite, serial, audio, CAT, or RF operation was found
directly in the normal `map_update` path. Tk image and canvas operations are the
principal external synchronous boundary there.

The normal `map_prepare` callees use already-published state or short critical
sections:

- `LiveMapService.request_viewport()` holds its lock while coalescing generations
  and assembling a small visible immutable snapshot; tile resolution and refresh
  execute on its worker outside that lock.
- `LiveRadarOverlayService.request_viewport()` holds its lock while evaluating
  FRONT coverage, coalescing a BACK target, and constructing the visible crop.
  Manifest/coverage/provider/PNG work executes outside the lock. Worker
  publication reacquires the same lock for FRONT swap and visible-snapshot
  assembly.
- `PotaMapMarkerService.request_viewport()` holds its lock only for generation
  state; SQLite runs on its worker before publication.
- Pi weather and alert services fetch and persist outside their publication
  locks; UI getters copy the immutable state under a short lock.
- `FT8ReceiveService.latest_state()` and `select_activity_target()` share
  `_state_lock` with capture/decode publication. Decoder execution, activity
  ingestion, observers, PCM analysis, recorder I/O, and diagnostic writing occur
  outside that lock; immutable-state replacement and target tracking occur
  inside it.
- radio and GPS UI snapshots are published values. No hardware read is issued by
  these getters.

This source audit establishes several possible lock-wait boundaries, but found
no designed multi-second provider or storage operation inside those critical
sections. The 19.323-second `map_prepare` field event therefore remains real but
mechanistically unresolved. Process descheduling, GIL/CPU pressure, an unusually
long short-section operation, or an untraced callback interaction remain
inferences, not incident facts.

## Deterministic reproduction

`tests/test_issue_345_ui_blocking_reproduction.py` uses the real
`LiveMapWidgets._flush_pending_base_tiles()` -> `_upsert_tile()` ->
`_photo_for_tile()` path. A fake Tk adapter enters `PhotoImage` and waits on an
event barrier. The test proves, without sleeps, display hardware, provider
access, serial/audio, or radio activity, that the calling refresh slice cannot
return until synchronous image materialization returns. Releasing the barrier
allows the same call to complete and publish the canvas item.

This is a successful isolated reproduction of a source-proven capability to
stall `map_update`. It is not a reproduction of Raspberry Pi/Tk latency and is
not proof that Tk image construction caused any particular field event.

## Ranked candidate causes

1. **Synchronous Tk image/canvas work in `map_update`.** Direct production
   evidence places multiple long tails in this phase; source proves the
   synchronous boundary; the barrier test reproduces caller blockage. Actual
   incident attribution among PNG encoding, `PhotoImage`, other canvas calls,
   display-server wait, and system resource pressure is unmeasured.
2. **Inline physical-command execution in `controls`.** Direct production
   evidence contains one 3.5-second controls interval, and source proves accepted
   commands execute serially on the Tk refresh caller. The responsible action or
   downstream handler was not recorded, so incident causality and whether the
   time was execution or descheduling remain unproven.
3. **Broad `map_prepare` contention/resource delay.** Direct production evidence
   contains the largest observed interval here. Source exposes several shared
   locks but no long provider/I/O critical section. A specific lock owner is not
   established; attributing this interval to radar, FT8, or any one snapshot
   would be speculative.

## Smallest correction proposal and gates

Do not change behavior from this report alone. The decision-blocking next probe
is one disabled-by-default, bounded monotonic trace that splits:

- each `map_prepare` subcall, including lock-acquiring request/snapshot calls;
- each accepted physical action by action token only; and
- base/radar base64, `PhotoImage`, canvas insertion, POTA, and overlay/status
  subphases.

It must record bounded durations/counts only—no callsigns, location, image bytes,
QSO data, raw control events, audio, or secrets—and must not alter ordering,
thread ownership, FT8 scheduling, radio authority, or error propagation.

If installed evidence confirms image materialization, the smallest correction
candidate is to move immutable byte preparation (including base64 preparation or
frame composition) to the existing map/radar workers, retain all Tk object and
canvas ownership on the UI thread, coalesce stale queued work, and schedule at
most one new materialization between control-drain opportunities. This must be
treated as a latency-risk reduction, not a hard deadline, because one Tk call is
still not preemptible. Required regression gates are map/radar visual parity,
DAY/NIGHT and installed/offline behavior, POTA layer ordering, FRONT/BACK frame
atomicity, stale/superseded queue rejection, control responsiveness, local-first
failure behavior, and existing FT8 receive diagnostics unchanged.

Rollout requires an isolated display replay, then separately approved garage
acceptance on the exact green SHA with radar off, cached radar, and unavailable
Forge. Deployment must retain the prior exact SHA and configuration for rollback;
rollback is the approved deployment wrapper returning both hosts to that SHA.
No merge or deployment is authorized in this slice.
