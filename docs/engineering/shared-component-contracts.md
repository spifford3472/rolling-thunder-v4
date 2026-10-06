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

Forge selects the exact Wavelog station target for every upload through one shared
boundary after receiving the immutable `Contact` and before claiming its UUID in
the Forge ledger. Dynamic mobile identity uses only frozen `my_grid`, `my_state`,
`my_cq_zone`, and `my_itu_zone`; retry/synchronization must never consult current
GPS. The ledger hash binds the actual ADIF payload and exact selected station ID, so
one UUID cannot move between stations. Browse, POTA, DX, FT8, and DMR must not add
feature-specific station-routing forks.

Verified dynamic stations use `Mobile - XXXX - YY`, retain a four-character
profile grid, and belong to the exact configured logbook. Only legacy `Mobile`
fallback receives the existing per-QSO profile-grid PATCH. Wavelog-bound ADIF
always carries full frozen `MY_GRIDSQUARE` when present and carries ADIF `NOTES`
equal to exact nonblank `Contact.notes` or exactly `Mobile QSO` when blank.

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

Do not reuse that implementation as implicit permission for unrelated PTT,
MOX, keying, tuner, or unattended transmission.

FT-891 FT8 context entry and pre-QSO preparation require verified menu 11-05
SSB MIC SELECT = REAR. Shared exit to Browse/POTA/DX normalizes it to MIC,
regardless of its prior value. Failed preparation grants no transmit authority.
See `../FT8_ENGINEERING_GUIDE.md` for cleanup and hardware acceptance.

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
