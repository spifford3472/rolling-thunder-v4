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
placement, Settings enable/disable behavior, and Forge callsign-intelligence
responses.

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
always carries full frozen `MY_GRIDSQUARE` when present and carries ADIF `NOTES`
equal to exact nonblank `Contact.notes` or exactly `Mobile QSO` when blank.

New contacts also retain typed workflow source and optional configured TX power.
When weather-note capture is enabled on the immutable contact, Wavelog notes append
`Contact Wx:` and `Local Wx:` lines; unavailable data is `N/A`. Contact sync performs
no weather lookup: it immediately routes, hashes, and uploads the immutable payload
it received. Local commit may snapshot only fresh already-published Pi retained
weather proven to match the contact's frozen local coordinates (within Forge's default
10 km mobile-weather refresh boundary), falling back to a frozen local-grid match only
when coordinates are unavailable, and callsign-info weather proven to match that
contact's callsign/target;
manual and FT8 logging share this boundary. Weather already present is preserved,
and absent, stale, or mismatched weather formats as
`N/A`. ADIF `TX_PWR` is emitted only
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

## Radio/transmit authority

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

## Physical controls

Physical controls are normalized into typed actions and dispatched through
shared command boundaries.

A feature may interpret an active-panel action but must not create a hidden
second serial/control protocol or bypass shared gating.

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
