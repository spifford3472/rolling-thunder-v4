# Pi Forge Shared-Spot Client

## Purpose

The Raspberry Pi Forge client path provides durable, offline-first POTA/DX
snapshots without moving network, SQLite, or CAT work into Tkinter.

The Pi reads the complete versioned Forge snapshot, validates it, persists it in
the existing application SQLite database, and publishes one immutable
last-known shared state consumed by the shared POTA/DX panel.

Checkpoint 8 completes the operator path above that durable client: POTA and DX
use provider-specific filtering plus explicit two-press receive tuning through
`ReceiveTuningService`. The Pi Forge client itself remains read-only operating
intelligence and has no radio authority.

## Configuration

The application `forge` section is disabled by default and supports:

- `enabled`
- `api_url`
- `request_timeout_s`
- `refresh_interval_s`
- `refresh_on_start`
- `max_response_bytes`

When `forge.enabled` is `true`, `forge.api_url` is required. Configuration bounds
request timeout, refresh interval, and accepted response size.

The accepted checkpoint-8 vehicle configuration reaches the production Forge
service through the private routed network at port 8766. The service deployment
and trust boundary are documented in `docs/FORGE_DEPLOYMENT.md`.

## HTTP Boundary

`HttpForgeSpotClient` performs one synchronous worker-side read:

```text
GET <forge.api_url>/api/v1/spots
```

The client uses the injectable `HttpTransport` boundary and an explicit timeout.
It does not contact `/api/v1/health` before retrieving spots.

Before a response can be published or cached, the client rejects:

- non-2xx HTTP responses
- response bodies larger than the configured limit
- invalid UTF-8
- invalid JSON
- non-object JSON roots
- API schema versions other than `"1"`
- malformed revisions or timestamps
- malformed provider health
- malformed callsigns, grids, frequencies, modes, source metadata, or POTA data
- provider/identity cross-field inconsistencies
- duplicate or noncanonical spot ordering
- provider active counts inconsistent with the complete snapshot

The wire DTO uses Forge integer-hertz frequency representation and reconstructs
the immutable shared `SpotRecord` and `SpotSnapshot` domain. Validation errors
are bounded and do not include full response bodies.

## Pi SQLite Schema

Application schema version 7 adds Forge-derived shared-cache tables to the
existing Pi application database. They remain independent of:

- `contacts`
- contact synchronization and retry tables
- legacy `pota_spot_cache` tables

The shared cache stores:

- snapshot revision
- Forge `generated_at`
- Pi `received_at`
- canonical spot position
- provider and stable identity
- callsign
- optional operator name
- optional Maidenhead grid
- integer frequency
- normalized radio mode
- display mode
- UTC source timestamp
- ordered bounded source metadata
- optional POTA park metadata
- deterministic upstream provider health and age/error metadata

Migration from schema 6 to 7 is forward-only and transactional. Existing
contact and legacy POTA-cache data are preserved.

## Durable Reconstruction

`ForgeSpotCacheRepository` replaces one complete shared candidate in one SQLite
transaction. A failed replacement rolls back so the prior durable snapshot
remains intact.

Loading reconstructs the complete immutable domain rather than trusting raw
rows. The repository revalidates stable identities, provider consistency,
canonical ordering, source metadata, frequencies, modes, timestamps, POTA
metadata, provider health ordering, and active counts.

Malformed durable state is reported as a local-storage failure and is never
silently published as valid shared data.

## Persistence Before Publication

A live Pi refresh follows:

1. request `/api/v1/spots` on the Forge worker
2. validate the complete response and reconstruct one immutable snapshot
3. build the complete local cache candidate
4. transactionally persist the candidate
5. atomically publish the new immutable Pi state only after persistence succeeds

A persistence failure cannot leave RAM newer than the durable snapshot.

Transport, HTTP, response-size, JSON, schema, domain-validation, or storage
failure retains the prior published snapshot and updates only bounded
attempt/error diagnostics.

## Published Pi State

`PiForgeSpotService` publishes immutable state with four origin/freshness kinds:

- `empty`: no valid shared snapshot is available
- `cached`: a durable snapshot was restored at process startup
- `live`: the most recent live Forge response was validated and persisted
- `retained`: a live refresh failed while a prior snapshot remains usable

Diagnostics include snapshot revision, original Forge generation time, last live
attempt, last successful Pi receive time, active spot count, bounded error
category/text, and accepted upstream provider health.

A restart does not reset snapshot age. Cached startup state preserves the
original Forge and Pi timestamps and does not fabricate a new live attempt.

## Background-Only Polling

`PiForgeSpotPollingService` owns the worker lifecycle. Production uses one worker
executor plus the repeating scheduler boundary.

`refresh_on_start` queues work onto the background executor; it never performs
Forge HTTP or shared-cache SQLite work inline in `ApplicationRuntime.start()` or
on the Tkinter thread.

The poller provides:

- optional immediate worker refresh
- configured repeating cadence
- one queued/executing refresh at a time
- no overlapping Forge fetches
- explicit start/stop
- cancellation of future scheduled work
- worker shutdown during runtime stop
- continued future attempts after expected or unexpected failures
- injectable scheduler/executor boundaries for deterministic tests

Dashboard and controller callers read only
`ApplicationRuntime.latest_forge_spot_state`, which returns already-published
immutable state and performs no external I/O.

## Application Runtime Composition

`ApplicationRuntime` composes the Pi Forge path only when `forge.enabled` is
true:

```text
HttpForgeSpotClient
    -> ForgeSpotCacheRepository
    -> PiForgeSpotService
    -> PiForgeSpotPollingService
    -> ApplicationRuntime.latest_forge_spot_state
```

When Forge is disabled, no Forge client, shared cache repository, Forge worker,
or Forge scheduler is composed.

## Shared POTA/DX Presentation

When Forge is enabled, the shared POTA/DX panel consumes only the already
published Pi Forge state.

The panel provides:

- one provider-neutral controller
- POTA and DX provider views
- stable identity-based selection
- provider-specific band and mode filter state
- POTA age filtering
- truthful live/cached/retained source status
- exact staged receive actions

The supported mobile band filters for both POTA and DX are 80, 40, 20, 17, 15,
12, and 10 meters. Both expose only ALL, SSB/PHONE, and CW mode groups; ALL is
restricted to Phone/SSB/CW and excludes digital modes. Both providers start in ALL.
On provider activation the current FT-891 band is used when supported, otherwise
20 meters is used.

Selection is preserved by stable identity, not row number. If a refresh or
filter removes the selected identity, selection and staging clear with no
neighboring fallback.

See `docs/SHARED_SPOT_DOMAIN.md` for the complete selection, filtering,
staging, two-press, and safety contracts.

## Two-Press Receive Tuning Boundary

The Forge client/cache never tunes the radio. Shared-panel execution is a
separate application path:

```text
first activation
    -> stage exact target
    -> no CAT

second activation of same still-valid target
    -> SharedSpotTuneController
    -> ReceiveTuningService
    -> typed Radio boundary
```

The active-panel controller rejects staging/tuning when the latest radio state
is disconnected, lacks frequency or mode, or reports transmitting. Existing
staging is invalidated in those states.

Blocking receive-tuning work runs outside Tkinter. Tune result presentation is
published through the thread-safe status-message service.

The Forge client, repository, poller, shared panel, and Tkinter perform no raw
CAT operations.

## Coexistence with the Legacy POTA Path

Forge is authoritative for live POTA/DX ingestion whenever `forge.enabled` is
true.

When Forge is enabled, the Pi Forge polling/cache and shared POTA/DX panel are
active and the legacy direct-POTA runtime poller is not composed.

When Forge is disabled, the legacy direct-POTA implementation remains available
as a rollback/compatibility path according to `pota_spots` configuration.

Legacy source modules and `pota_spot_cache` tables remain intact. No destructive
cache migration is required.

Local SQLite contact logging remains authoritative regardless of Forge state.
Shared POTA records provide compatible contact-context metadata without a live
Forge request during Commit.

## Production Forge Path

Checkpoint 8 formalizes Forge as a systemd-managed service on the trusted private
network. The accepted production service:

- runs under dedicated account `rollingthunder`
- uses application path `/opt/rolling-thunder-forge`
- uses config `/etc/rolling-thunder/forge-spots.yaml`
- uses persistent DB `/var/lib/rolling-thunder/forge-spots.db`
- listens on `192.168.9.170:8766`
- is active and enabled at boot
- uses journald for process logs
- retains QRZ credentials outside YAML when QRZ is enabled

The REST API intentionally has no TLS or application-layer authentication in
checkpoint 8. It is supported only inside the documented private
RadioLAN/CarLAN-over-WireGuard trust boundary. See `docs/FORGE_DEPLOYMENT.md`.

The checkpoint-8 production acceptance demonstrated live healthy POTA and DX
provider refreshes and real Pi `/api/v1/spots` requests through the private
routed path.

## Offline-First Behavior

Forge availability is not required for local logging or vehicle operation.

A lost WireGuard route, cellular outage, Forge outage, public-internet failure,
provider outage, rejected Forge response, or local shared-cache write failure
leaves the last valid shared snapshot available when one exists.

No failure in the Forge path may prevent local SQLite contact Commit or Discard.

## Radio-Safety Boundary

The Pi Forge client/cache/service/poller perform no:

- CAT commands
- band, frequency, or mode changes
- receive tuning
- PTT, MOX, keying, tuner, power, or transmit control
- unattended radio action
- voice-originated tuning
- contact modification as part of spot refresh
- Tkinter network or SQLite work

`ReceiveTuningService` remains the sole receive-tuning authority. The Forge path
is operating intelligence, not a radio-control service.

## Checkpoint-8 Acceptance Status

Completed:

- shared POTA/DX Forge client and durable Pi cache
- background-only refresh lifecycle
- retained/cached/live state semantics
- shared POTA/DX panel migration
- DX band and mode filtering
- two-press exact staged receive-tuning path
- radio-state invalidation before staging/tuning
- production Forge systemd deployment and live provider acceptance

Remaining before issue #148 is complete:

- final real FT-891 shared POTA/DX same-band and cross-band bench
- first-press no-radio-change confirmation on final checkpoint-8 build
- filter/context/stale-action invalidation checks on installed controls
- ATAS warning acceptance on shared cross-band tuning
- retained Forge interruption and local logging-continuity acceptance
- full Ruff, strict MyPy, pytest, pre-commit, diff, and CI gates
