# Shared Component Contracts

## Purpose

These are the cross-feature invariants most likely to be damaged by a narrowly
scoped agent. They are deliberately stronger than screen-specific preferences.

## Contact information overlay

Owner: shared callsign-intelligence subsystem.

The overlay is **not owned by POTA**. POTA may supply a current park coordinate,
but the lookup lifecycle, stale-response invalidation, presentation, timeout,
and preference are shared.

Changes must consider POTA, DX, Browse/pending-callsign flows, map-overlay
placement, Settings enable/disable behavior, FT8 selected/preparing/active/terminal
lifecycle, and Forge callsign-intelligence responses. Locally known callsign and
valid FT8 grid state may render before enrichment; only current lifecycle ownership
may accept the asynchronous result. Network failure wording uses already-published
connectivity state and must not add a blocking probe or expose exception details.

In POTA, DX, and FT8, popup presentation is armed by an accepted explicit station
action. Browse movement intent, accepted band change, or departure from one of those
contexts suppresses presentation and invalidates its generation. Suppression is
durable across refresh, highlighted/pending callsign changes, active FT8 target
publication, and stale success/failure completion; while suppressed, no popup lookup
or contact mini-map request/render is started by refresh. A later accepted explicit
station action, including the same callsign, rearms one fresh lifecycle. Rejected
radio/tuning/QSO commands neither rearm nor gain authority. Voice/manual pending
callsign flows outside the affected station browsers retain their existing behavior.

## Antenna reference and RF exposure advisory

The antenna-reference subsystem shares typed application configuration, context /
physical navigation, and the local SQLite migration mechanism. Its sole data
authority is manual YAML; schema-21 antenna tables are dormant compatibility storage
and the dashboard neither reads nor writes them. Catalog antennas remain separate
from physical installations. Unknown gain or loss is never zero, gain is never
interpolated beyond an explicit frequency segment, and HF support never implies 6 m.

RF exposure output is a versioned plane-wave approximation. It must always retain
both controlled and uncontrolled FCC limits, its reflection assumption, citations,
and uncertainty warnings. It must never publish a compliant/safe verdict, create an
interlock, derive live transmit authority, change output power, or issue CAT/PTT.
The typed six-foot scenario is exactly 1.8288 m and unverified; front-seat and public
distance kinds require measured/verified values.

The dashboard context and shortcut exist only when the typed feature gate is enabled;
the default navigation sequence is unchanged. Physical controls are view-only for
this context. There is no in-app setup/edit/reload or voice mutation path. One bounded
worker loads and validates YAML once at startup and atomically publishes results;
Tkinter performs no file, SQLite, calculator, radio, or persistence work. Missing or
invalid YAML must remain an explicit error and never appear as a safe estimate.

## Local-first contact durability

A successful operator Commit must be durable locally before remote
synchronization is considered successful.

Network/Forge/Wavelog failure must not erase the local contact. Retry/idempotency
semantics are shared infrastructure.

FT8 and DMR may add feature-specific metadata, but they must not fork a weaker
persistence model.

Completed FT8 contacts participate in the same post-commit background sync
lifecycle as ordinary contacts. `commit_completed` preserves the stable QSO
UUID and frozen QSO data; optional QRZ enrichment uses the existing readiness
gate. A missing grid with configured QRZ fallback is `pending_qrz` until the
shared enrichment worker completes, including lookup failure without a grid.
Only `ready` contacts are upload-eligible. Completion notifications request
background work; they do not select a Wavelog station or perform remote I/O.

That stable QSO UUID is also the FT8 attempt UUID used by optional Forge propagation
analytics. The disabled-by-default PSK service contract requires the immutable
durable FT8 `Contact` and matching successful terminal attempt together; only their
source/transport owner may attest that both are confirmed. The private ingestion API
requires a non-repository bearer credential plus the matching stable UUID as its
idempotency key. Its sink has no Pi,
contact-sync, logging, radio, or transmit authority. Enqueue performs no provider
I/O, and query work remains on an independent bounded scheduler. Process, ingestion,
and provider egress are separate gates that default off. Invalid or mismatched
terminal data must not enter the inbox or trigger a provider query. No current Pi or
Forge producer is implied by the receiving API.

The source-side completed-QSO producer uses one local immutable event and separate
durable destination states. It may enqueue only after the matching `Contact` and
successful terminal attempt have both committed. Exact replay is accepted; any
changed event under the stable UUID fails closed. VOACAP and PSK delivery retry
independently on a background worker, use distinct protected bearer credentials,
and require a matching receiver acknowledgement before local completion. No network
or provider work may run in terminal handling, local logging, contact sync, or
Wavelog synchronization. Production composition remains disabled by default, runs
on a separate scheduler, and validates each receiver's acknowledged UUID before
advancing only that destination.

The Phase-B attempt ledger is separate from that successful-QSO event. Every
durable terminal performance attempt is captured, including non-successes, without
fabricating a Contact. It reads period powers only from the existing transmit-period
owner. Exact replay is accepted; changed replay conflicts. Delivery/provider work
are independently scheduled and disabled by default. VOACAP reliability is not QSO
probability, dB-Hz is not decoder dB, missing is not zero, and retrospective results
are not pre-choice evidence.

The undeployed Forge propagation inbox accepts the complete frozen `Contact` under

The disabled Forge propagation inbox accepts the complete frozen `Contact` under
that same UUID without provider work. Exact replay is idempotent; changed frozen
grids, coordinates, UTC start, frequency/mode, or power under the same UUID is a
conflict. Provider correlation runs only from a separately scheduled bounded worker,
so neither local durability nor Wavelog synchronization waits for VOACAP. The worker
has separate disabled-by-default identity/configuration and publishes only
non-secret Forge-local status. Its private HTTP ingestion contract requires a
separate bearer secret, matching UUID idempotency key, bounded complete payload, and
durable inbox commit before acknowledgement. The typed client does not imply that
local logging or contact sync is a producer; source-side durable retry remains an
explicit prerequisite.

Forge selects the exact Wavelog station target for every upload through one shared
boundary after receiving the immutable `Contact` and before claiming its UUID in
the Forge ledger. Dynamic mobile identity uses only frozen `my_grid`, `my_state`,
`my_cq_zone`, and `my_itu_zone`; retry/synchronization must never consult current
GPS. The ledger hash binds the actual ADIF payload and exact selected station ID, so
one UUID cannot move between stations. Browse, POTA, DX, FT8, and DMR must not add
feature-specific station-routing forks.

Verified dynamic stations use `Mobile - XXXX - YY`, retain a four-character
profile grid, and belong to the exact configured logbook. Any legacy `Mobile`
profile alignment also uses only derived grid4; no station profile follows a
moving six-character subsquare. Wavelog-bound ADIF
always carries full frozen `MY_GRIDSQUARE` when present. New Wavelog-bound ADIF
omits blank `NOTES` and preserves nonblank supplied text exactly. Ordinary new
POTA/Browse/FT8 contacts do not generate POTA/mobile/location boilerplate.
Existing saved text and structured location/POTA/weather evidence remain intact.

New contacts also retain typed workflow source and optional configured TX power.
Weather capture remains an immutable structured snapshot, but new uploads do not
append weather to notes, even when the historical weather-note flag is enabled.
Existing claimed uploads retain exact legacy ADIF only when its computed hash
matches the durable claim; both pending retries and synchronized replays retain
that hash and station identity. Changed payloads still fail closed. No ledger or
contact row is rewritten. Contact sync performs
no weather lookup: it immediately routes, hashes, and uploads the immutable payload
it received. Local commit may snapshot only fresh already-published Pi retained
weather proven to match the contact's frozen local coordinates (within Forge's default
10 km mobile-weather refresh boundary), falling back to a frozen local-grid match only
when coordinates are unavailable, and callsign-info weather proven to match that
contact's callsign/target;
manual and FT8 logging share this boundary. Weather already present is preserved;
absent, stale or mismatched observations remain null. ADIF `TX_PWR` is emitted only
when the snapshot contains a verified configured-power value. Dynamic station
profiles remain four-character routing identities while QSO `MY_GRIDSQUARE` remains
the full frozen grid in Rolling Thunder's submitted ADIF. Wavelog 3.2.3 currently
overwrites the imported QSO field from the grid4 station profile; correcting that
provider limitation requires a separate Wavelog API/import change, not temporary
profile mutation.

Forge persists each Rolling-Thunder-created dynamic station's verified exact name,
ID, and UUID before its first logbook link attempt. If Wavelog's `active_log_only`
list hides that unlinked station, retry may direct-fetch only the bound ID and must
reverify name, UUID, frozen routing metadata, and legacy-template callsign/DXCC.
Missing or changed bindings fail closed. A generic hidden-station 409 without a prior
verified binding is not recoverable by guessing or scanning IDs. Health remains
strictly read-only and never creates, links, or binds stations.

## Current location and QSO grid

GPS/location is shared infrastructure.

Features consume published GPS state rather than opening serial GPS paths.

`Contact.my_grid` is the single six-character persisted local-grid source.
`my_grid6` exposes it explicitly and `my_grid4` is derived from its first four
characters. FT8 likewise has one authoritative `local_grid6`; its on-air
`local_grid4` and trusted logging view are derived rather than separately stored.

When a QSO workflow requires a stable grid for the duration of an attempt, it
may snapshot the current shared grid at the defined lifecycle boundary. FT8 does
this per QSO attempt: the captured grid remains fixed until that attempt
succeeds, fails, is aborted, or otherwise terminates. The next QSO obtains a new
current grid.

FT8 clock-readiness diagnostics consume the existing published trusted GPS UTC
observation only as fallback/independent verification when normal host NTP is
not ready. They must not open a second GPS serial path, weaken UTC trust, or
silently claim readiness when NTP and GPS disagree.

Do not globally freeze location merely to satisfy one feature.

## Shared POTA/DX spot identity

POTA and DX use provider-neutral typed spot records and stable identities.
Selection must not depend on row position.

A selected/staged action must not silently redirect to a neighboring/new spot
after refresh. Action-critical changes invalidate staging.

POTA-specific behavior must not leak into DX and vice versa unless the shared
contract is intentionally changed.

Worked state remains provider-specific even though POTA and DX reuse the same
card treatment. POTA keys worked state by callsign, amateur band, and displayed
mode. DX keys it by callsign and amateur band only. Both markers are created
only after successful local contact durability and expire from presentation at
UTC-day rollover.

## Receive tuning

`ReceiveTuningService` is the shared receive-tuning authority for applicable
workflows. Feature code should submit typed intent rather than issue raw CAT.

A new screen-specific raw-CAT shortcut is an architectural regression unless
explicitly approved.

## STAB-04B shutdown command and FT8 authority

The dashboard close event revokes the existing `OperatorCommandController`
mutation boundary. The physical-control dispatcher must also discard queued
events without invoking event interceptors once closing begins, and re-check
the event between actions in a drained batch. The dashboard's F12 Tron
shortcut is inert once closing begins. The once-only close worker uses
an atomic shutdown-request claim, retaining one lifecycle owner.

The bounded FT8 executor must serialize `PTT.key()` with its own existing
`close()` latch, including final authorization **after** radio verification
that may have yielded to shutdown. A request that was already admitted but
has not keyed must not key after shutdown has closed the executor. Hardware
CAT continues to be serialized exclusively by the existing FT-891 adapter.

A successful software `TX0;` write is not physical proof of de-keying.
Stuck CAT I/O and pre-existing in-flight audio/worker behavior remain
subject to supervised STAB-05/REL-01 acceptance.

## Radio/transmit authority

During incomplete application startup, shutdown must release an already-CONNECTED radio only through the existing radio adapter, after existing FT8 transmit/QSO cleanup. A failed adapter disconnect must remain a reported shutdown error and retryable; a radio not yet connected must not be opened just to shut it down. No parallel or implicit transmit authority is introduced.


General UI/controller code does not have blanket transmit authority.

FT8 has a deliberately bounded transmit path requiring explicit operator
authorization for one QSO target and fail-closed preparation/session checks.
An addressed decode remains receive-only until Button 2 explicitly accepts its
exact immutable inbound record. Responder start phase is protocol-derived from
that record (grid to REPORT; report to R_REPORT) and must not reuse the
CQ-selected initiator start phase.
Failed responder start leaves the inbound alert eligible. A completed QSO adds
only a bounded six-period same-remote continuation guard; unsuccessful terminal
results do not prevent an immediate retry, and different callers are unaffected.

Do not reuse that implementation as implicit permission for unrelated PTT,
MOX, keying, tuner, or unattended transmission.

FT-891 FT8 context entry and pre-QSO preparation require verified menu 11-05
SSB MIC SELECT = REAR. Shared exit to Browse/POTA/DX normalizes it to MIC,
regardless of its prior value. Failed preparation grants no transmit authority.
See `../FT8_ENGINEERING_GUIDE.md` for cleanup and hardware acceptance.

FT8 initial power is a single preparation-time request derived from the frozen
local/remote grids and hard-clamped to 20–70 W. Active-QSO code must not
continually reset configured power because operator manual override is
authoritative. Configured-power CAT readback is not the raw RF meter and failure
to read it must not alter or fail a QSO.

## Voice microphone ownership

The microphone is exclusive shared hardware. If Tron owns it, a physical
callsign request must immediately reserve callsign priority, stop new Tron
commands, signal and reap the active recorder, and only then start callsign
capture. The callsign controller releases priority only after its recognition
worker exits. No UI thread may join or wait for audio work. Callsign capture
remains available with Tron disabled. Three physical callsign Discard/Cancel
presses within two seconds toggle Tron listening, while every press retains its
ordinary discard behavior. The gesture is suppressed during a PTT alarm/inhibit
or pending power confirmation. Tron intents require the exact wake word, use
only existing read-only navigation, and cannot acquire radio, logging, or
configuration authority.

## Physical controls

Physical controls are normalized into typed actions and dispatched through
shared command boundaries.

A feature may interpret an active-panel action but must not create a hidden
second serial/control protocol or bypass shared gating.

Settings power confirmation is the sole event-aware consumer: the dispatcher
retains already-validated identity only for it. Destructive physical input needs
current healthy serial-v2 nonce/generation, host expiry, distinct increasing
RELEASE IDs, and deliberate spacing. Default consumers remain unchanged.

## Global status messages

The status service is shared. Priority, replacement keys, expiration, and
presentation semantics can affect unrelated workflows.

A feature should publish status through the service rather than directly
overwriting another feature's status presentation.

## Map and GPS presentation

The primary live map is local-first and can remain useful from installed/cache
data when networks fail.

The primary live map is authoritative for DAY/NIGHT style and installed-style
availability. Solar automation and the manual Settings toggle must use the same
style fan-out; the callsign mini-map mirrors accepted style changes but retains
its separate worldwide online source and cache. Its cache must partition styles,
and a non-style-aware fallback may satisfy NIGHT only through the explicit
callsign-only validated dark-raster transform. Raw DAY bytes must never be
relabelled or persisted in the NIGHT partition. A `{style}` source must use its
actual style endpoint without the local transform. The primary live-map client
must not opt into this fallback. Map zoom remains scoped to the primary live map.

Map availability and GPS availability are distinct states.

Do not infer current GPS merely because a map snapshot exists, and do not blank
a usable retained map simply because a provider is unavailable.

## Retained Forge state

Where a Forge/Pi retained service follows persistence-before-publication,
preserve the sequence:

```text
retrieve/build complete candidate
    -> validate
    -> persist transactionally
    -> publish immutable state
```

A failed candidate must not replace the last valid retained state.

## Forge APIs

Forge APIs are presentation-neutral reusable service contracts. They must not
return Tkinter/widget layout or assume one Rolling Thunder context is the only
consumer.

The optional style-aware map route is layered onto the existing private Forge
spot API listener. It supports only validated `day` and `night` tiles, delegates
all non-map paths unchanged, and must remain failure-isolated from spots,
weather, alerts, mobile location, radar, and health. Enabling it must not create
a second production listener. Health requests never trigger map rendering.
The route is optional rather than a prerequisite for the callsign mini-map and
is a valid worldwide source only when backed by worldwide renderer data; the
regional I-71 dataset does not satisfy that contract.

Provider quirks, credentials, reconnect etiquette, and polling belong behind
Forge service/provider boundaries.

## VOACAP solar input provenance

VOACAP SSN is a scientific input, not a synonym for any field containing the word
`sunspots`. C4 accepts NOAA/SWPC `predicted_ssn` only for the exact `time-tag`
`YYYY-MM` being modeled: it is the product's forecast-month smoothed predicted SSN,
not `observed-solar-cycle-indices.json` `smoothed_ssn` and not HamQSL's raw observed
count. The current NOAA feed supplies no provable per-record issue timestamp, so the
source release is explicitly unknown and capture time is the earliest availability
claim. Exact raw bytes/hash, obtainable HTTP headers, source schema and mutable-feed
revision policy are retained append-only. An adapter fails closed on semantic/month
mismatch, schema/version drift, future or stale capture, malformed/oversized input,
or absent as-of evidence. C4 rows remain training-ineligible by presence alone.

## DX Summit connection

Forge owns one long-lived DX Summit IRC connection. It is not a polling socket.

Do not:
- reconnect because a Pi refreshes;
- reconnect on a timer/connection age;
- connect/scrape/disconnect repeatedly;
- make the Pi connect to IRC directly.

Reconnect only after genuine failure with bounded backoff.

## Configuration/preferences

Persisted preference keys and meanings are cross-version contracts. Renaming or
changing semantics requires migration/backward-compatibility consideration.

## Documentation contract

If any contract above intentionally changes, update:
- this file;
- `ownership-and-dependencies.md`;
- `shared-component-consumers.md` if consumers change;
- relevant subsystem docs;
- the Operator's Guide if behavior is visible.


## Friend classification is informational

Known/friend directory status may decorate remote callsigns only. It must never
affect canonical callsign identity, capture, filtering, selection, worked state,
FT8 eligibility/retry/authorization, radio/tuning, logging or synchronization.
Admin comments are Forge-only. Rendering uses an already-published bounded set;
failed/stale Forge classification removes decoration without disabling local
operations. See `../KNOWN_CALLSIGNS.md`.

## QSO-local coordinate contract

Contact owns paired optional frozen my_latitude/my_longitude. Ordinary logging
uses the controller's captured GPSState and existing freshness policy; FT8 uses
authorized FT8QsoContext. Repository/recovery and complete-contact JSON format 3
preserve both values; old formats 1/2 and old contacts default to None. Sync and
QRZ enrichment never derive historical coordinates from current GPS. Local UUID
replay compares coordinates; Forge retains its existing ADIF/profile hash. Upgrade
the receiving Forge package before the expanded Pi sender. See
[contact synchronization](../FORGE_CONTACT_SYNC.md#immutable-qso-location-checkpoint-a).

## FT8 selected-target activity (CP3.1 Step 1)

The receive service owns the optional selected-target activity observation. It uses immutable normalized decoded traffic, and never changes selection eligibility, QSO authorization, retry policy, or CAT power. Activity involving another callsign is reported only when the selected station is **the decoded source**, and excludes exchanges addressed to the configured local station. No decoded traffic is never proof the target is idle or available. Freshness expires after four 15-second periods; selecting a different station or changing the receive band clears the observation. UI wiring, green/white status-strip presentation, and busy-station retry extensions are separate future steps.

## Live map FT8 banner input

`LiveMapWidgets.update` accepts optional `ft8_status` (own operator phase, white) and `ft8_remote_status` (fresh, source-attributed selected-target decode evidence, green). Other map consumers omit both and retain the same layout. Both are presentation-only strings; remote evidence does not authorize RF, alter retries, or establish QSO completion. The FT8 caller clears its observation selection when leaving the FT8 context.

Step 2A renders these two strings on one baseline, with measured font widths and own-state priority, without changing map dimensions. FT8 decode-in-progress is a read-only published receive-state flag; TX-running is a read-only property of the bounded hardware executor keyed-PTT interval. No observer, radio-control, or transmission authority is added to presentation.

FT8 CP3.1 busy-target continuation remains subject to the same one-target
authorization: source-attributed third-party replies may latch at most two
additional unchanged-phase transmissions, never beyond eight. Extended
transmit requests suppress automatic power step-up and carry separate
`busy_extension_attempts` telemetry (backward-compatible default zero).

CP3.1 Step 4 Forge performance schema version 3 durably records
`busy_extension_attempts` (0–2). Historical schema-2 attempts migrate with
zero extensions, and exact replay of legacy payloads is still idempotent.
Additional target-busy attempts must remain distinguishable from reachability
failures in any future model training or analytic aggregate.

Forge performance schema version 4 additively stores paired nullable frozen local
latitude/longitude already carried by the typed attempt. Schema-1 and schema-3
databases must migrate forward without rebuilding rows, backfilling coordinates, or
rewriting payload hashes. Exact current and legacy replay remains idempotent;
changed current payloads still conflict. This telemetry path is not a contact
receipt and must never invoke Wavelog, CAT/PTT, or RF behavior.

## FT8 attempt analytics provenance

The immutable attempt payload, canonical SHA-256 and UUID replay decision are not
provenance labels and must not be rewritten to classify test data. Forge owns a
separate auditable UUID-keyed provenance record. A documented synthetic/test UUID is
excluded before VOACAP provider processing and from training while its raw inbox row
and replay behavior remain unchanged. An absent record means provenance is unknown,
not field-observed; unknown rows may retain Phase B retrospective processing but are
training-ineligible. Retrospective availability remains training-ineligible even for
later audited field observations. See `voacap-ft8-phase-c.md`.

Phase C2 coverage consumes declared snapshots through read-only/query-only SQLite
connections. It never claims leases, calls a provider, changes provenance, or emits
callsigns, raw payloads, or exact coordinates. It fails closed on immutable identity/
hash disagreement, changed documented exclusions, cross-database UUID mismatch,
foreign-key errors, and any training-eligible link that is not an audited field,
ready, pre-choice result available by its cutoff. A ready provider result is required
when persisting any new training-eligible link.

Deterministic missing-input directions are persisted before provider work. Unknown
remote power remains an explicit reverse-direction `skipped` run even when forward
work retries or dead-letters. A response with no parsed requested-hour/band value is
`unavailable`; it is not zero and is not training evidence.
Historical forward correlation uses each transmitted period's UTC, exact frequency,
frequency-derived band, and only CAT-verified configured power. A declared model
service version and modeled assumptions are canonical input identity before provider
egress: terminal replay performs no request, while changed versions append new runs
without mutating older evidence. With no pre-call version, matching durable terminal
history suppresses eager re-query. Version-unknown legacy input hashes remain stable.

Phase C3 historical replay is allowed only against declared copied/fixture SQLite
inputs. The source connections are query-only and their logical contents and lease
state must remain unchanged; a new history output is required. The approved AA4NP
event is identified by UUID `938620bb-b4ff-40b2-9493-081b56bb038c` and immutable
payload SHA-256
`9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab`.
Replay requires its independently verified production provenance row to already be
`field_observed`; code must never seed, replace, or reclassify that row. The two C1
synthetic exclusions remain exact and immutable.

The C3 CLI has no network provider adapter. Its only provider is a bounded,
versioned local fake fixture keyed by year, month, selected UTC hour, band, mode,
and configured watts. Provider requests retain the real summary contract (year and
month in the request; hour selected from the response) and never fabricate
second-specific prediction inputs. Every result is `retrospective` and therefore
training-ineligible even for audited field evidence. Immutable input and response
hashes, zero-call terminal deduplication, append-only model-version forks, missing/
unsupported results, C2 reconciliation, and source non-mutation are part of the
versioned report.

Phase C4 baseline evidence is independent of attempt correlation. Immutable plans
freeze origin grid6, curated versioned target cells, supported bands, UTC slots,
20-W reference, SSN provenance and model/service identity. A monthly provider
response may be reused only under the exact canonical request SHA-256; individual
hour/band slots remain distinct. Every result preserves scheduled, forecast and
generation times plus pre-choice/late/backfill/missed status. Baseline diagnostics
are read-only and all C4 data is training-ineligible. No baseline result may imply
decoder dB equals VOACAP dB-Hz, configured/model watts equals measured RF watts, or
modeled circuit reliability equals QSO success probability.

Phase C5 may pair only audited field observations with forecasts generated and
available at or before the frozen choice time. Late, backfill, retrospective,
synthetic and unknown-provenance evidence is never prospective training evidence;
future SSN values are forbidden. Attempt UUID/QSO groups and independent forecast
inputs have separate denominators, and reused hourly cells from one monthly input do
not become independent forecasts. Grid precision/uncertainty, 7.2-MHz modeled band
center versus 7.074-MHz dial, VOACAP dB-Hz versus decoder dB, and missingness remain
explicit.

Every C5 advisory is Forge-only and immutable with `shadow_only=true`,
`apply_allowed=false`, `may_transmit=false`, and the current 20-W operational
baseline. It must not alter live CQ order, the existing retry ladder or configured
power. `armed_when_ready` computes only future readiness. Any future actuation or
operator-visible use requires a separate contract, approval and regression review.

## Scheduled VOACAP response content and provenance

The capture response table deduplicates canonical JSON bytes, with immutable first-observation version metadata. Per-request provider/model columns carry the verified issuer of each distinct POST; consumers must not attribute every request to the first blob issuer. Different versions may return identical bytes without identity conflict. Missing reliability or SNR yields an unavailable hour/band with both derived values NULL, never substituted zero/sentinel values. See `issue-353-response-identity-and-missing-values.md`.

## Uncomposed controller recovery policy

`control_transport_health.py` publishes pure immutable health/backoff data only. No production consumer or activation gate is wired. `validated_session` is a future adapter trust boundary; neither an open serial descriptor nor current RTCTRL/1 events prove freshness. It grants no action/radio authority and does not replace existing physical-control gating. See `control-transport-health-policy.md`.

Recovery v2 adds strict session/age validation and a bounded serial-owner worker, selected only by explicit serial_v2 configuration; legacy serial is unchanged. Health-only traffic is never an application action; pending input is discarded on loss/expiry. Legacy gating and all current consumers remain unchanged. See `controller-recovery-v2.md` for the firmware, ownership, reset and bounded-gating commissioning prerequisites.

ControlInputEvent has optional host-monotonic expires_at_s metadata (default None for legacy producers). The v2 worker supplies its bounded expiry and the recovery gate requires it at each dispatch; slow earlier commands cannot replay the batch remainder. The legacy gate/three-argument event constructors retain compatibility.


Issue246 extends shared last-QSO history with optional strict full worked_count and
last band. Missing metadata is unknown, never a fabricated count or first contact.
Pi renders the published values without I/O and omits notes/comments. See
`../CALLSIGN_INFO.md` for exact-call/token scope, cache and Pi-first rollout.


Settings power requests permit an explicitly disconnected radio whose published
TX flag is false, provided every independent local FT8/hardware/PTT/commit guard
is idle. This supports shutting down with the radio already switched off. A retained
TX flag is never cleared by disconnection; connecting/error states remain unknown
and block the action. No live CAT query or radio command is issued by this guard.


## Opt-in MeshCore passive observation extension

The opt-in MeshCore collector may consume a caller-supplied immutable `GPSState` and separate version-1 MeshCore-only tables but must not query a second GPS receiver, infer routes from cached outbound paths, assume RSSI/SNR from 0x80/0x81/0x8A, connect to radio hardware or introduce an application-originated unattended transmit path. Existing MeshCore firmware-managed RF is permitted by the owner but does not authorize the application to send discovery, adverts, messages or other transmissions. Default configuration remains disabled; live activation requires a verified exclusive physical USB path and parked hardware acceptance. No ordinary radio control, PTT, contact logging or GPS acquisition is delegated to MeshCore.

Heltec V4 native CDC ACM is an approved receive-adapter transport only for a physically validated `303a:0002` USB device on an explicit `/dev/serial/by-path` selector. Its USB DTR signal must be asserted for firmware replies and does not authorize any MeshCore application-originated RF command. The legacy Heltec V3 `10c4:ea60` CP2102 transport remains supported with DTR deasserted. A validated USB hardware model is not proof of firmware version; version identification is conducted separately.


### MeshCore independent ownership (cutover implementation)

The standalone collector is the exclusive MeshCore USB owner; Rolling Thunder only publishes nonblocking, atomic snapshots of its current GPS state from the existing polling listener. Absence of fresh GPS state causes explicit null receiver location, never a new GPS acquisition. The read API uses a permission-restricted Unix socket, has no mutating endpoints and never exposes raw RF message data. RF signal metrics from 0x88 carry no trusted sender identity or routing attribution. Durable MeshCore-only SQLite is outside the RT production worktree and separately migrated; local QSO SQLite and FT8/Radio/CAT are untouched.

## MeshCore private activity API

The isolated MeshCore collector is the sole owner of its serial device and schema-2 observation database. Only the existing local permission-restricted Unix socket can serve `meshcore/activity/v1` through `GET /v1/activity`. Calls are read-only, bounded to rolling UTC 24 hours with at most 25 receiver-reception bins; POST and unknown routes are rejected. Receiver coordinates are not peer/device coordinates. No new network listener, second GPS reader, raw message persistence or RF command is introduced. UI clients must consume snapshots through a bounded asynchronous adapter; do not synchronously query the socket on Tk.

## MeshCore message broker privacy and delivery

Only the independent collector serial owner may issue audited *host-local* GET_CHANNEL and SYNC_NEXT_MESSAGE requests. Dequeued private contact frames must be synchronously preserved in an isolated protected inbox before the next dequeue; verified public and restricted quarantine streams are separate. A public-looking hashtag is not proof of public channel membership. Acknowledgements are scoped by bearer-verified consumer identity and stream, and never erase another consumer's unread message. The original passive observation API remains read-only. Full storage, mismatched channel identity and uncertain command timeout stop new dequeues. The owner accepts an at-most-one-message power-loss gap between firmware pop and SQLite commit. No RF transmission is authorized.

## MeshCore public consumer read boundary

The common consumer transport authenticates via the preexisting per-consumer protected local token file and connects only to the independent broker Unix socket. Its default behavior is bounded, immutable public-only reads with **no cursor advancement**. Private/quarantine frames must never cross into a public consumer even on malformed/unknown responses. A separate explicit `acknowledge_processed` action is reserved for a downstream consumer that has completed durable processing; no CLI preview, keyword classifier, dashboard refresh or SCOUT pilot is authorized to call it implicitly. Traffic classification requires the exact approved #traffic slot and retains unverified sender/location semantics. No UI, radio or GPS side effects.

## MeshCore durable traffic worker commit-before-ACK

The independent public consumer's broker cursor is ACKed **only after** the worker's separate SQLite ledger transaction has durably committed the exact source broker message ID and analysis disposition. A failed persistence step must not ACK. A committed-but-unacknowledged replay must validate the exact message fingerprint and retry ACK without duplicating a candidate. A broker ID reused with different source payload fails closed. Public general-channel messages are explicitly ignored in analysis but still durably recorded and ACKed; private/quarantined messages must never enter the worker. Similar traffic reports may be recorded as duplicate rather than new candidates within the bounded rolling suppression window, but source IDs remain recorded separately. Neither Tk, SCOUT, FT8 nor another consumer may ACK the worker's cursor or use its candidate rows as verified geographic hazards. The worker remains opt-in and has no RF, alert, route or provider authority.


## MeshCore analysis-only geographic relevance

The existing broker and traffic worker retain all public-intake, private
isolation and ACK ownership. Parsing must not promote unknown or ambiguous
messages into incidents or invent a point from highway text. An independent
geocode provider is disabled by default and constrained by rate limits,
cache, exact road and landmark evidence. The GPS sampler reuses only
the existing snapshot at <=1 Hz; its 2–5-second history must be fresh and
accurate before movement relevance. Heading alone is insufficient to confirm
route alignment. Decisions cannot issue driver warnings, navigation changes
or MeshCore RF commands. No new service, schema or external listener.

## MeshCore Forge geographic evidence contracts
No highway-name centroid becomes a trusted site or confirms a crash.
Offline reviewed source identity is immutable; the catalog fails closed
on multi-match, missing or stale records. No public/private messages,
credentials, GPS track or broker cursor are exposed in the assessment
store. No existing live database/service is migrated. See
meshcore-forge-road-evidence.md.

## OHGO optional Forge provider / mobile read-only view

New screen `MESHCORE & OHGO` does not grant transport, broker, map,
radio or navigation authority. Forge alone reads the OHGO credential
from systemd `LoadCredential`; no key is transported to Pi or persisted
in source. Its optional background provider must fail closed on stale,
unauthorized, malformed or paginated data and must never block the Forge
HTTP handler. Pi's background poll must never run on Tk's refresh thread.
No unsolicited alert/route change is permitted.

### MeshCore/OHGO context-scoped rotary scrolling

The dashboard's shared physical control input remains guarded/deduplicated
by the existing control dispatcher. Its MOVE_NEXT / MOVE_PREVIOUS actions
may scroll the OHGO read-only text viewport **only when that context is
selected**, with existing safety/lock gates preserved. All other contexts
retain their original active-panel navigation and encoder semantics.
No new radio, GPS, broker, voice or transmitter permissions are introduced.
See `meshcore-ohgo-incidents.md`.
