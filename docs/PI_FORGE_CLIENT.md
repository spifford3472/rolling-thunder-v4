# Pi Forge Shared-Spot Client

## Purpose

Checkpoint 6 adds the Raspberry Pi-side Forge client path for shared POTA/DX
snapshots without changing the running POTA dashboard or receive-tuning workflow.

The Pi now has an optional background-only client stack that reads the complete
versioned Forge snapshot, validates it, persists it in the existing application
SQLite database, and publishes one immutable last-known shared state for future
presentation work.

Checkpoint 7 now uses the durable Forge shared snapshot for both POTA and DX
presentation through the shared panel.

## Configuration

The application `forge` section is disabled by default and supports:

- `enabled`
- `api_url`
- `request_timeout_s`
- `refresh_interval_s`
- `refresh_on_start`
- `max_response_bytes`

When `forge.enabled` is `true`, `forge.api_url` is required. Configuration bounds
request timeout, refresh interval, and accepted response size. No Forge
credentials are introduced in checkpoint 6.

## HTTP Boundary

`HttpForgeSpotClient` performs one synchronous read:

```text
GET <forge.api_url>/api/v1/spots
```

The client uses the existing injectable `HttpTransport` boundary and an explicit
configured timeout. It does not contact `/api/v1/health` before retrieving
spots.

Before a response can be published or cached, the client rejects:

- non-2xx HTTP responses
- response bodies larger than the configured accepted byte limit
- invalid UTF-8
- invalid JSON
- non-object JSON roots
- API schema versions other than `"1"`
- malformed revision or timestamps
- malformed provider health
- malformed callsigns, grids, frequencies, modes, source metadata, or POTA data
- provider/identity cross-field inconsistencies
- duplicate or noncanonical spot ordering
- provider active-count values that do not match the complete snapshot

The wire DTO uses Forge's integer-hertz JSON representation and reconstructs the
existing immutable shared `SpotRecord` and `SpotSnapshot` domain. Validation
errors are bounded and do not include full response bodies.

## Pi SQLite Schema

Application schema version 7 adds Forge-derived shared-cache tables to the
existing Pi application database. They are independent of:

- `contacts`
- contact synchronization and retry tables
- legacy `pota_spot_cache` tables

The legacy POTA cache is intentionally retained unchanged until checkpoint 7.

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
transaction. A failed replacement rolls back so the previous durable snapshot
remains intact.

Loading reconstructs the complete immutable domain again rather than trusting
raw rows. The repository revalidates:

- stable identities
- provider consistency
- canonical ordering
- source-metadata ordering
- frequencies and modes
- timestamps
- POTA metadata
- provider health ordering and active counts

Malformed durable state is reported as a local storage failure and is never
silently published as valid shared data.

## Persistence Before Publication

A live Pi refresh follows this order:

1. request `/api/v1/spots` on the Forge worker
2. validate the complete response and reconstruct one immutable snapshot
3. build the complete local cache candidate
4. transactionally persist the candidate
5. atomically publish the new immutable Pi state only after persistence succeeds

This ordering is mandatory. A persistence failure cannot leave RAM newer than
the durable snapshot.

On transport, HTTP, response-size, JSON, schema, domain-validation, or storage
failure, the service retains the prior published snapshot and updates only
bounded attempt/error diagnostics.

## Published Pi State

`PiForgeSpotService` publishes immutable state with four origin/freshness kinds:

- `empty`: no valid shared snapshot is available
- `cached`: a durable snapshot was restored at process startup
- `live`: the most recent live Forge response was validated and persisted
- `retained`: a live refresh failed while a prior snapshot remains usable

Diagnostics include:

- snapshot revision
- original Forge snapshot generation time
- last live attempt time
- last successful Pi retrieval/receive time
- active spot count
- bounded error category and text
- accepted upstream provider-health metadata

A process restart does not reset snapshot age. Cached startup state preserves the
original Forge generation and Pi receive timestamps and does not fabricate a new
live-attempt time.

## Background-Only Polling

`PiForgeSpotPollingService` owns the worker lifecycle. Production uses a single
worker executor plus the existing repeating scheduler boundary.

`refresh_on_start` queues work onto the background executor; it never performs
Forge HTTP or shared-cache SQLite work inline in `ApplicationRuntime.start()` or
on the Tkinter caller thread.

The poller provides:

- optional immediate worker refresh
- configured repeating cadence
- one queued/executing refresh at a time
- no overlapping Forge fetches
- explicit start/stop
- cancellation of future scheduled work
- worker shutdown during runtime stop
- continued future attempts after expected or unexpected worker failures
- injectable scheduler/executor boundaries for deterministic tests without real
  sleeps

The dashboard and other callers may only read `latest_forge_spot_state`, which
returns already-published immutable state and performs no external I/O.

## Application Runtime Composition

`ApplicationRuntime` composes the Pi Forge path only when `forge.enabled` is
true. The composition stack is:

```text
HttpForgeSpotClient
    -> ForgeSpotCacheRepository
    -> PiForgeSpotService
    -> PiForgeSpotPollingService
    -> ApplicationRuntime.latest_forge_spot_state
```

When Forge is disabled, no Forge client, cache repository, worker, or scheduler
is composed.

Runtime start and stop include the optional Forge polling lifecycle but do not
route current POTA presentation or tuning through the new shared path.

## Coexistence with the Legacy POTA Path

Checkpoint 7 makes Forge authoritative for live POTA/DX ingestion whenever
`forge.enabled` is true.

When Forge is enabled, the Pi Forge polling/cache and shared POTA/DX panel are
active, and the legacy direct-POTA runtime poller is not composed.

When Forge is disabled, the legacy direct-POTA implementation remains available
as a rollback/compatibility path according to `pota_spots` configuration.

The legacy source modules and `pota_spot_cache` tables remain intact. Checkpoint 7
performs no destructive database migration or cache deletion.

Local SQLite contact logging remains authoritative regardless of Forge state.
Shared POTA records provide compatible contact-context metadata without requiring
a live Forge request during Commit.

The real checkpoint-7 bench validated live POTA and DXSpider data through Forge,
WireGuard/CarLAN, the Pi durable cache, the shared dashboard, and the installed
physical controls. Encoder activation staged the selected record without changing
the FT-891 frequency.

Permanent Forge installation, systemd lifecycle, service-account configuration,
firewall policy, authentication/TLS, and deployment hardening remain checkpoint-8
work.

## Offline-First and Radio-Safety Boundary

Forge availability is not required for local logging or current vehicle
operation. A lost WireGuard route, cellular outage, Forge outage, public-internet
failure, provider outage, or rejected Forge response leaves the last valid
shared snapshot available when one exists.

The Pi Forge client/cache/service/poller perform no:

- CAT commands
- band, frequency, or mode changes
- receive tuning
- PTT, MOX, keying, tuner, power, or transmit control
- unattended radio action
- contact modification as part of spot refresh
- Tkinter network or SQLite work

`ReceiveTuningService` remains the only receive-tuning authority. The shared
Forge path introduced in checkpoint 6 is read-only operating intelligence.
