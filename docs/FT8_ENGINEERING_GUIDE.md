# Rolling Thunder FT8 Engineering / Design Guide

Status: CP9.1 engineering-guide source. This document is intended to become the basis for a printable design/engineering guide after final production acceptance.

## Design Intent

### Completed-contact synchronization

Only a `COMPLETED` result with a received report enters
`FT8QsoLoggingService` -> `ContactLoggingService.commit_completed` -> durable
local `Contact`. The runtime completion callback updates worked-today state
and the dashboard requests shared LOG background synchronization, just as for
ordinary/DMR commits. The stable QSO UUID remains the contact/idempotency key.
Known remote grids are immediately ready; missing grids use the existing
optional QRZ enrichment worker when configured. A failed optional lookup releases
the contact without a grid. `ContactSyncService` uploads eligible contacts via
the Home Platform API to Forge; Forge alone resolves the configured Wavelog
station location. FT8 performance telemetry remains a separate outbox and is
not evidence of contact synchronization.

`tests/test_ft8_contact_sync.py` covers dashboard completion wiring, shared
Pi/Forge serialization, dynamically resolved Mobile profile selection, QRZ
success/failure/absence, and idempotent replay without live services or hardware.
The missing immediate completion notification was reproduced on v4.4.0; healthy
LOG polling/periodic sync can still upload those contacts, so this defect alone
does not establish the cause of a permanently missing production QSO. See
`docs/FORGE_CONTACT_SYNC.md` for evidence collection and installed acceptance.

The native FT8 subsystem is built around three separate concerns:

1. **CQ eligibility/activity** — which stations are allowed to appear in the operator browser.
2. **Attempt history/presentation** — how an already-eligible CQ row is decorated based on current-day prior attempts.
3. **QSO execution/telemetry** — the bounded state machine, radio authority, logging, and machine-analysis records.

Keeping these separate prevents decoded non-CQ traffic or historical attempt data from manufacturing a station that never called CQ.

## CQ Eligibility State

`FT8CQActivityManager` is authoritative for browser membership.

A callsign enters the activity map only from a normalized CQ decode. If a non-CQ decode is received for a callsign that is not already present, it is ignored for browser-membership purposes.

For an existing CQ candidate:
- `last_cq` records the most recent CQ period;
- `last_any_decode` records the most recent decode of any type;
- `cq_count` counts distinct CQ periods;
- non-CQ traffic can update informational fields but does not refresh CQ eligibility;
- the row expires when its most recent actual CQ reaches age six periods;
- insertion order is preserved, so new CQs append at the bottom.

## CQ Presentation State

Base presentation for an eligible CQ is:

1. actual-CQ age 0-1 periods -> yellow;
2. actual-CQ age 2-3 periods -> white;
3. actual-CQ age 4-5 periods -> gray;
4. actual-CQ age 6+ periods -> absent.

Presentation receives the published receive period explicitly and computes age
from `last_cq`; `cq_count` and recent non-CQ activity do not change the normal
row color.

Persistent same-day attempt history has higher presentation precedence:

1. failed/error/retry-exhausted/preparation-failed -> red + `!`;
2. operator aborted -> blue + `■`;
3. otherwise the actual-CQ age mapping above applies.

The selected row retains this callsign color and adds an independent high-contrast selection border/background.

POTA is independent metadata: an explicit POTA CQ token adds the green tree indicator
and remains eligible. On successful logging, the current cached POTA records are
consulted with the same callsign/frequency/mode ambiguity rules as ordinary POTA
logging; exactly one matching park adds `POTA_REF`, while zero or multiple parks add
nothing. A U.S. station explicitly calling `CQ DX` is filtered from the selectable CQ
browser. The right side of the top FT8 title/status row shows `DECODE n` for the most
recently completed decode cycle in the same 48-point bold type as the FT8 status. The
field is absent when no count exists and is cleared in every non-FT8 context; there is
no duplicate decode count in the FT8 footer.

## Attempt History

Attempt history is keyed by:
- normalized callsign;
- band;
- UTC date.

It is derived from the durable FT8 performance outbox rather than a second ad-hoc persistence database.

On application startup, the attempt-history service rebuilds the current UTC day's state from stored performance payloads. New terminal performance records update the in-memory history after durable local storage.

Outcome mapping:
- `COMPLETED` clears failed/aborted presentation history because the normal worked-today subsystem suppresses the successful callsign/band;
- `ABORTED` -> blue;
- `RETRY_EXHAUSTED`, `ERROR`, and `PREPARATION_FAILED` -> red.

Attempt history never inserts a callsign into CQ activity.

At the UTC date boundary, prior-day visual history expires.

## Successful Worked-Today Suppression

`FT8WorkedTodayService` derives successful callsign/band suppression from normal completed FT8 contacts.

A completed callsign/band is hidden for the remainder of the UTC date. Different bands remain independent. This survives application restart because completed contacts are durable.

## Terminal Result Reset

The QSO coordinator and QSO-start controller have separate responsibilities.

When a terminal QSO result is acknowledged and ownership returns to the CQ browser:
- terminal coordinator ownership is released;
- QSO-start presentation state resets to IDLE;
- stale activity/error/attempt-seed data is cleared;
- the next station receives a fresh attempt ID and preparation sequence.

This prevents a prior FAILED banner from contaminating a later station attempt.

## Machine-Analysis Telemetry

Successful, failed, aborted, retry-exhausted, and preparation-failed attempts are stored separately from the normal contact log.

The telemetry model includes structured UTC timing, callsign, band/frequency, local/remote Maidenhead grids, distance, signal reports/SNR, target power, available radio meter values (power/SWR/ALC), outcome, state, and terminal reason.

`tx_power_target_watts` is the requested initial configured-power target and is
retained for API compatibility. Nullable `tx_power_start_watts`,
`tx_power_end_watts`, and `tx_power_max_watts` record actual FT-891 configured
power readback; they are distinct from the raw RF power meter. End readback is
best-effort in terminal/receive handling and can never change the QSO result.
Old Pi payloads remain valid, and Forge schema v1 migrates additively to v2.

For a completed QSO, the same terminal configured-power read is captured on the
immutable Contact for Wavelog `TX_PWR`. A failed read leaves it null and never changes
QSO completion. The coordinator invokes the terminal handler before the later
operator/context exit restores normal 100 W operation, so the saved value is the
final configured FT8 power rather than `FT8_EXIT_POWER_WATTS`. Propagation correlation identifies the operating mode as FT8 even
though CAT power uses the FT-891 HF/SSB configured-power control.

Successful QSO:
- normal contact exactly once;
- telemetry exactly once.

Non-successful attempt:
- no normal contact;
- telemetry exactly once.

The outbox is idempotent by stable attempt UUID and synchronizes to Forge for future AI/statistical analysis.

Phase B additionally snapshots every durable terminal performance record into an
all-outcome attempt event with frozen coordinates, directional decoder reports and
the existing per-emission configured-power evidence. Its optional authenticated
Forge delivery is separately gated, leased/retried and cannot block terminal
handling. Forge correlations use immutable full-input hashes and retain VOACAP
reliability, dB-Hz, missingness, direction and retrospective availability without
claiming QSO odds or pre-choice knowledge. See
`engineering/voacap-ft8-phase-b.md`.

Phase C1 keeps those immutable payload/replay semantics and adds an independent
Forge UUID-keyed provenance boundary. Documented synthetic/test attempts do not
reach VOACAP or training; absent provenance stays explicitly unknown and is not
training evidence. No FT8 UI, logging or radio behavior changes. See
`engineering/voacap-ft8-phase-c.md`.

Phase C2 adds a provider-free, read-only Forge coverage consumer for declared
attempt/history snapshots. Its versioned aggregate omits callsigns, payloads and
exact coordinates and cannot change provenance, leases, FT8 behavior, or training
eligibility. It is not the scheduled baseline or the complete field report.
Forge correlation also records deterministic missing-input directions before
provider work; unknown remote power remains a reverse skip after forward retry
exhaustion. This changes no Pi or RF behavior.
Forward retrospective inputs use the individual transmitted period's UTC, exact
frequency/frequency-derived band, and only verified configured-power readback.
Declared model service versions and assumptions are pre-call hash identity, so replay
performs no duplicate provider request and upgraded models append history without
changing prior evidence. Version-unknown legacy durable inputs are not eagerly
re-requested.

Optional completed-QSO propagation analytics use a separate source outbox only after
both the successful `Contact` and matching successful performance attempt have been
durably written. The terminal callback may perform that short local enqueue but no
network work. VOACAP and PSK delivery state/retry are independent. The production
composition is explicitly disabled by default and schedules authenticated delivery
outside FT8/UI execution only when configured. See
`COMPLETED_QSO_PRODUCER.md`.

## Operator-Authorization Semantics

FT8 transmit authority is based on an explicit operator intent event, not on a
particular hardware input device.

The v4.3.0 implementation treats a short rotary-encoder press on the selected
eligible CQ station as the authorization event for exactly one bounded QSO.

Future interfaces, including voice control, may issue the same typed
authorization only when they resolve to one specific currently eligible station
and traverse the same authorization/preparation boundary. The input source does
not bypass CQ eligibility, freshness checks, band/frequency preparation, timing,
retry limits, or fail-closed behavior.

A generic wake word, passive speech, background decoding, AI output, network
message, or stale selection is not operator authorization.

Authorization is single-use: terminal completion, failure, abort, or cancellation
does not implicitly authorize a subsequent station.

## Safety Boundaries

- UI widgets do not own CAT/PTT/audio authority.
- One explicit selected CQ authorizes one bounded QSO.
- No auto-next station.
- Radio preparation fails closed.
- CAT loss fails closed.
- Receive-only configuration creates no physical transmit authority.
- Local Maidenhead grid is frozen for the duration of one authorized QSO.
- `local_grid6` is authoritative; `local_grid4` and the backward-compatible trusted
  `logging_grid` view are derived and cannot drift.
- Persistent continuous receive architecture remains independent of transmit execution.

## October 6 drive-home behavior

The receive pipeline retains the newest supported addressed-grid or signal-
report decode whose destination is the configured local callsign and whose
source callsign is present. Its immutable incoming-call record preserves the
message kind, report, grid, timing, audio frequency, and raw message. The panel
shows it only in BROWSE. Button 2 explicitly accepts that exact decode into the
responder path, while Button 3 dismisses it; decoding alone never authorizes RF.
Button 2 dismisses the alert only after responder start accepts it. When a
completed QSO returns to BROWSE, addressed traffic from that same remote is
treated as terminal continuation through the next six FT8 periods; other
callsigns remain immediately eligible, and later calls from the worked remote
can appear after the bounded cutoff. Failed, aborted, retry-exhausted, and error
results do not install this continuation guard.
An accepted grid message starts with REPORT and waits for R_REPORT. An accepted
REPORT starts with R_REPORT, retaining the received report for telemetry, and
waits for ACK_73. Both then send 73 and finish under the existing bounded retry,
parity, CAT/PTT, abort, and fail-closed rules. The CQ-selected initiator path is
unchanged.

Initial QSO power is derived only from frozen local/remote Maidenhead grids:
20 W through 3,000 km, then 25/30/35/40/45 W through 4,500/6,000/7,500/9,000/
10,500 km, 50/55/60/65 W through 11,500/12,500/13,500/14,500 km, and 70 W
beyond. Unknown/invalid distance uses 20 W. The target is applied once during
preparation and is never continuously reasserted during the active QSO.

CQ freshness is validated synchronously at the explicit operator selection
against the period in the one immutable receive snapshot the operator saw. A
receive snapshot at the wall-clock period or one period behind is allowed;
two-period-stale or future receive state fails closed. The selected CQ must be
age 0-5 relative to that frozen receive period. One encoder activation uses one
panel snapshot and one exact activity object; a rejected authorization leaves
the selection highlighted.
The accepted selection remains valid across bounded CAT preparation delay;
post-preparation authorization still checks all radio, mode, location, identity,
and transmit-session gates without aging the already accepted selection again.


## CP9.1 Final Acceptance Record — 2026-10-03

Checkpoint 9.1 completed installed-hardware and repository acceptance on
`anvilmobile` using the isolated Round 4 FT8 database.

Installed-hardware acceptance confirmed:

- a successful 40 m FT8 QSO with N6RAM was logged exactly once through the
  normal FT8 contact path;
- after acknowledging success, N6RAM disappeared from the 40 m CQ browser as
  required by same-UTC-day worked suppression;
- a ZF2OO attempt exhausted its retry budget, displayed FAILED, returned cleanly
  to the CQ browser after encoder acknowledgement, and did not block subsequent
  rotary selection;
- a W0ERB operator-aborted attempt rendered with the blue aborted presentation
  and was recorded only as FT8 performance telemetry, not as a normal contact;
- failed/error attempt history rendered red with the redundant `!` marker;
- operator-aborted history rendered blue with the redundant `■` marker;
- fresh/repeated/non-CQ CQ lifecycle colors rendered as yellow/white/gray;
- the operator confirmed the installed display presentation was usable;
- CQ browsing recovered correctly after terminal success, failure, and abort;
- shutdown left no Rolling Thunder, FT8 decoder, playback, or capture process
  behind;
- the isolated database passed `PRAGMA integrity_check`.

The Round 4 telemetry record contained successful, retry-exhausted,
preparation-failed, and operator-aborted attempts while the normal contact table
contained only the completed FT8 QSO. This confirms the separation between
normal QSO logging and machine-analysis attempt telemetry.

Final repository acceptance at code head
`6d9b0a07dfb053b76623a324f139dc0144521278`:

- 2,511 tests passed;
- 7 tests skipped;
- `git diff --check` passed;
- focused Ruff validation passed;
- repository-wide Ruff passed with one explicitly excluded inherited baseline
  file: `tools/regional_map_builder.py`.

The excluded file reports Ruff `EXE001` because it contains a shebang while
being stored as non-executable mode `100644`. The blob SHA
`69a6f884c5ac160774ff4f10a594683e4b0bcf9b` is identical on `main` and the
CP9.1 branch, so this warning is not a CP9.1 regression and was not modified as
part of the FT8 scope.

CP9.1 received explicit owner approval for merge and v4.3.0 release tagging on 2026-10-03.


## Long-Run Receive Clock Discipline

Rolling Thunder is expected to remain continuously powered for 30–90 days or
longer. The DigiRig USB audio oscillator and the Raspberry Pi system clock are
independent clocks and must not be assumed to remain phase-aligned indefinitely.

A production smoke test on 2026-10-03 demonstrated that the original continuous
capture implementation could decode correctly after startup and later stop
producing CQ rows after many hours of uninterrupted runtime. Direct capture from
the same DigiRig path, freshly aligned to a UTC FT8 boundary, immediately decoded
22 messages. Restarting the receive service restored CQ decoding.

Root cause: the receive path initially aligned one PCM window to UTC and then
advanced subsequent windows by exactly 180,000 captured samples. Any persistent
USB sample-clock error therefore accumulated across every 15-second period until
the extracted PCM windows drifted far enough from UTC FT8 boundaries to impair
decoding.

The v4.3 release fix re-anchors the next capture-window start to UTC after every
completed FT8 period. Sample-clock error is therefore bounded to one 15-second
period and cannot accumulate across days or months.

Regression coverage includes a deterministic 90-day runtime model with a
conservative 100 ppm USB-clock offset. The test verifies that the UTC boundary
sample is used for the next period rather than the previous start plus a fixed
180,000-sample increment.

Operational expectation: FT8 receive must remain correctly aligned during
30–90-day continuous Rolling Thunder uptime without requiring a service restart.

## Receive-Loss Investigation Diagnostics

Issue #237 distinguishes three different quantities that must not be conflated:

1. all normalized FT8 messages decoded by a backend;
2. the subset of those messages that are CQ messages; and
3. CQ rows still eligible for the operator browser after activity expiry and
   worked-today filtering.

The earlier decoder bake-off already establishes a sensitivity limitation in
the default backend. On the same five WAV periods, `ft8_lib` matched 62 of 88
WSJT-X oracle messages while `ft8mon` matched 70 of 88. A lower Rolling Thunder
count than iFTx is therefore not, by itself, evidence of audio loss or CQ
filtering. The bounded diagnostic mode runs both configured adapters against
the exact same immutable `FT8PcmPeriod` and retains independent ALL and CQ
counts so the remaining gap can be localized.

Adapter parsing also accepts leading whitespace, signed decimal DT/frequency
values, and `ft8_lib` lines both with and without the optional `~` separator;
decoder-looking lines that still fail normalization are counted as malformed
instead of disappearing without evidence.

The optional diagnostic session is deliberately temporary. Its configured
local cutoff is interpreted in `America/New_York`; the issue-237 run uses
`05:15`. A session started before the morning cutoff stops comparison at that
cutoff. A session started after 18:00 runs only until the next morning cutoff,
while one started after the cutoff during the day remains inactive. The primary
decoder continues normally after the comparison session ends.

The receive configuration shape for the planned run is:

```yaml
ft8:
  receive:
    decoder_backend: ft8_lib
    decoder_executable: /absolute/path/to/decode_ft8
    comparison_backend: ft8mon
    comparison_decoder_executable: /absolute/path/to/ft8mon
    diagnostic_session_end_local: "05:15"
    diagnostic_snapshot_path: /absolute/bounded/path/ft8-diagnostics.json
    saved_pcm_directory: /absolute/bounded/path/ft8-pcm
    saved_pcm_periods: 3
```

Comparison and saved PCM configuration are rejected unless the local session
cutoff is also present. Normal production configuration leaves these fields
null/zero.

PCM retention is capped at one to three stable WAV slots. Later process starts
replace the same slot names rather than creating an unbounded period archive.
The JSON diagnostic snapshot is also atomically replaced in place. Snapshot
state includes capture/restart/drop counts, audio level/clipping, capture-boundary
lateness, parser/malformed-line counts, primary and comparison decoder metrics,
and the bounded session aggregate. Optional diagnostic I/O or clock-probe
failure is reported in state but cannot stop receive.

### Clock readiness

FT8 UTC slicing now treats the host's normal chrony/NTP synchronization as the
primary clock authority. A read-only `chronyc tracking` probe requires a normal
leap state, a usable source, and stratum 1–15. It changes no service or clock
configuration. When NTP is unavailable, already-published trusted GPS UTC is
the fallback verifier. If both are available but disagree by more than one
second, or either trusted source reports excessive offset, FT8 diagnostics fail
safe to degraded rather than claiming readiness.

GPS-assisted system-clock correction remains owned by the existing bounded
`ClockSynchronizationService` and its explicit deployment enablement. This
investigation does not alter sudoers, the privileged helper, chrony/systemd
configuration, or production ALSA. Receive diagnostics do not gain clock-write,
radio-control, or RF-transmit authority.

### Capture-boundary correction

Per-period UTC re-anchoring now back-projects from observed scheduler wake
lateness instead of blindly treating the next buffered sample as the UTC
boundary. The measured lateness travels with the exact PCM period for diagnosis.
This closes a smaller per-period alignment error that could otherwise remain
after the earlier long-run USB-clock drift fix.


## FT-891 context audio source

FT8 entry automatically sets and verifies menu **11-05 SSB MIC SELECT = REAR**
(`MIC = 0`, `REAR = 1`). FT8 uses the rear DATA/RTTY audio path.
Returning from FT8 to Browse, POTA, or DX sets **11-05 = MIC** so ordinary SSB
voice uses the front microphone. The destination context is authoritative;
the prior menu value is not restored.

The existing typed FT-891 adapter owns CAT encoding and readback. FT8 receive
entry/band changes and pre-QSO preparation require REAR. A failed write,
malformed reply, or mismatched readback prevents QSO authorization; no PTT or
transmit audio is permitted through the preparation path. Existing USB,
11-07 SSB BFO, IPO/preamp, NAR, NB, power, and bounded transmit policy remain.

Shared exit/rollback cleanup attempts MIC even if another restoration fails.
Failed-QSO recovery that remains on the FT8 screen reapplies REAR; a requested
context exit skips that recovery. CAT-safe shutdown performs serialized normal
receive cleanup before disconnect. With CAT unavailable, restoration cannot be
confirmed: check 11-05 manually before voice operation. Hardware acceptance of
this change is still required.


### Owner acceptance for menu 11-05

Do not perform these hardware steps in Codex Cloud. On the Pi, deploy the exact
PR commit into an isolated validation worktree with isolated validation data and
an exact rollback point. Keep production checkout/configuration/databases intact.

1. Record the commit and verify 11-05 = MIC in Browse, POTA, and DX voice contexts.
2. Enter FT8 and verify 11-05 automatically becomes REAR.
3. Verify USB, 11-07 USB, IPO/preamp, NAR OFF, and NB OFF remain correct; verify
   existing power policy at its established preparation boundary.
4. Perform owner-approved bounded FT8 operation with suitable RF conditions.
5. Confirm successful local logging, stable contact identity, and background
   Forge/Wavelog synchronization; verify failed/aborted attempts create no contact.
6. Exit FT8 to each of Browse/POTA/DX and verify 11-05 = MIC and normal front-mic
   SSB audio. Repeat with active-QSO abort followed by context exit, failed-QSO
   exit, and CAT-safe application shutdown.
7. Confirm an abort that remains in FT8 retains the FT8 destination profile.
8. Perform an owner-controlled CAT failure/readback-failure check before QSO
   authorization: verify no PTT or transmit audio, visible failure, and no retry
   that grants authority. Restore CAT, exit FT8, and confirm MIC before voice use.
9. Record outcomes and hardware/radio firmware details; roll back to the recorded
   exact baseline if acceptance fails. Automated tests do not establish live RF
   or front-microphone acceptance.

## CP3.1 Step 3 — busy-target retry extension (2026-10-11)

The already-selected and explicitly authorized QSO normally has six attempts for
each unchanged phase. The QSO coordinator reads the existing immutable receive
`target_activity` snapshot once per observed period, **without** a second decode
observer. Only source-attributed, fresh (age 0–3 FT8 periods) messages **from**
the exact authorized target **to a third-party callsign** qualify: addressed
grid, report, R-report, or 73. A CQ, third-party traffic **to** the target,
unknown/stale/ambiguous attribution, or messages to KI5VNB never qualify.

An eligible observation grants exactly two extra attempts (7 and 8 maximum)
for the **current unchanged phase**, with a fixed, latched allowance. Once
granted it is not revoked solely because the message ages out; a valid QSO
phase transition clears the allowance, requiring new evidence for that phase.
Selection changes, band change, browser cleanup, and termination leave no
permission to transmit another QSO. An observed third-party 73 does not count
as our QSO completion. No ninth attempt is possible.

The extended request carries `busy_extension=True` through the existing
transmit-session/hardware boundary; attempts 7 and 8 skip automatic CAT power
step-up, while retaining the existing CAT readback, manual override and band
power ceiling enforcement. Earlier attempts retain the pre-existing power
policy. Terminal attempt performance records add optional-compatible
`busy_extension_attempts` (default 0; max 2), separate from ordinary total
transmit attempts and reachability evidence; consumers must not interpret those
extensions as additional independent reachability failures. No logging,
provider, Wavelog, RF configuration or UI layout changes are made.

Acceptance remains simulation-only until explicitly authorized live validation.

## CP3.1 Step 4 — offline integrated acceptance review (2026-10-11)

Step 3 was merged as `21cc542ba2eae4f50b729d887483dfcb9b2918c6`.
Hardware-independent simulations now exercise the coordinator's real period ticks,
immutable published third-party tracker snapshot, authorized single-target state,
retry ceiling, no ninth transmission, terminal result and extension telemetry.
Existing tests exercise CQ/third-party report/R-report/73 interpretation,
phase transition and normal six-attempt exhaustion; extended calls explicitly
suppress adaptive CAT power step-up without disabling normal power limits.

A release blocker was identified in review: `FT8PerformanceAttempt` contained
`busy_extension_attempts`, but Forge's structured performance SQLite schema 2
silently omitted it. The Step 4 follow-up introduces Forge schema 3 with a
transactional `busy_extension_attempts` column (zero for historical rows),
updates inserts, and preserves old schema-2 attempt-UUID idempotent replay when
the extension value is zero. A changed nonzero replay remains a conflict.
Local Pi outbox already serializes the complete typed attempt payload. Forge
service deployment/migration needs separate authorization and verified backup.

**Acceptance boundary:** all current tests are offline fakes. No real FT-891,
DigiRig, PTT, antenna, Forge production DB, or anvilmobile runtime was touched.
Operators must separately authorize any staged installation, hardware/RF
acceptance, and production cutover.

## CP3.1 post-deployment UI follow-up — retry denominator and TX activity

The operator-visible TRY and ATTEMPT denominators are derived from the live
controller's effective phase budget: six normally, eight only after qualifying
selected-target third-party activity. The underlying configured retry baseline
stays six, and no additional transmissions become authorized by rendering.

The FT8 coordinator exposes simple read-only presentation properties without
acquiring its transmit-slot lock. An entire synchronous physical FT8 playback
can hold that lock; blocking the UI on it previously prevented a screen refresh
while PTT was keyed. Mutation, session cancellation, terminal capture and
transmit authorization continue using the existing synchronized paths.
This is a read-path-only fix: UI sampling may see a transient snapshot of a
state transition, but it never gains control of transmission.
