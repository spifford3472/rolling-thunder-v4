# Forge Spot Aggregation Service

## Purpose

The Forge spot aggregation service is an independent process that prepares
provider-neutral POTA and future DX spot snapshots for later Rolling Thunder
clients.

It is not part of the Raspberry Pi `ApplicationRuntime`. It performs no radio,
CAT, receive-tuning, contact-logging, Tkinter, or transmit-control work. The Pi
remains local-first and continues to operate when Forge, WireGuard, cellular
service, or the public internet is unavailable.

Checkpoint 4 of GitHub issue #129 adds:

- typed Forge-only configuration
- a provider-neutral Forge spot-provider boundary
- the initial public POTA provider adapter
- complete immutable provider slices
- persistence-before-activation aggregation
- a dedicated transactional SQLite snapshot repository
- retained durable state on startup
- lifecycle-managed background refresh
- versioned read-only REST endpoints
- bounded provider, storage, and lifecycle failure state

DXSpider and QRZ enrichment remain later checkpoints.

## Process Boundary

The service runs through the separate console entry point:

```text
rolling-thunder-forge-spots --config config/forge-spots.yaml
```

The composition root is `rolling_thunder.forge_spot_main`. It owns:

1. Forge YAML loading and validation
2. Forge-specific SQLite initialization
3. public POTA HTTP source composition
4. POTA-to-shared-domain normalization
5. aggregation and publication state
6. background refresh scheduling
7. the read-only HTTP listener
8. orderly shutdown

The HTTP listener is started before optional refresh-on-start work. A retained
SQLite snapshot can therefore be served immediately while the first live
provider refresh is still running.

This process is intentionally not composed into the Pi UI or
`ApplicationRuntime`.

## Configuration

The safe example is:

```text
config/forge-spots.example.yaml
```

The default production path expected by the console command is:

```text
config/forge-spots.yaml
```

The typed configuration includes:

- `server.bind_host`
- `server.bind_port`
- `storage.database_path`
- `aggregation.refresh_interval_s`
- `aggregation.refresh_on_start`
- `pota.enabled`
- `pota.base_url`
- `pota.request_timeout_s`
- `logging_level`

The default bind address is `127.0.0.1`. The default database is a relative
Forge-only path and is resolved relative to the YAML file.

Configuration rejects:

- blank bind hosts
- ports outside 1 through 65535
- blank or current-directory-only database paths
- nonpositive refresh intervals
- nonpositive or excessive provider timeouts
- malformed public HTTP URLs
- unsupported logging levels
- unknown keys

No credentials are stored in this configuration. The current public POTA
provider requires no credentials.

## Provider Boundary

`ForgeSpotProvider` is a synchronous provider-neutral protocol used only by the
Forge refresh core. A provider exposes:

- one `SpotProvider` family
- one `fetch_slice()` operation
- a complete immutable `ForgeProviderSlice`
- a timezone-aware fetch timestamp
- typed connection, response, and normalization failures

`MockForgeSpotProvider` provides deterministic provider behavior for tests and
development.

A provider slice contains one provider family only. Its records must already be
canonical, duplicate-free, and deterministically ordered through the shared spot
domain.

## Initial POTA Provider

`ForgePotaSpotProvider` reuses the existing typed public POTA HTTP source and
maps `PotaSpot` records into provider-neutral `SpotRecord` values.

The mapping preserves:

- normalized activator callsign
- integer-hertz frequency
- normalized radio mode
- provider display mode
- provider source timestamp
- stable POTA identity
- park reference
- optional park name
- optional location code
- optional latitude and longitude
- bounded comments as source metadata

Operator name and Maidenhead grid remain `None` in this checkpoint. QRZ
enrichment is not performed here.

A successful empty public provider result is a valid complete empty slice. A
nonempty public response that produces no usable typed records is treated as a
provider failure rather than silently activating an empty result.

## Persistence-Before-Activation Rule

A provider refresh follows this order:

1. fetch one complete provider slice outside request handling
2. validate and canonicalize the provider slice
3. combine it with previously active slices from other providers
4. build one complete candidate `SpotSnapshot`
5. validate the candidate snapshot
6. transactionally persist the complete snapshot and provider-slice metadata
7. receive the new durable revision from the repository
8. atomically publish the new immutable aggregation state

The in-memory active snapshot is never changed before persistence succeeds.

If fetch, parsing, normalization, candidate validation, or persistence fails:

- the previous provider slice remains active
- the previous aggregate snapshot remains active
- the previous revision remains active
- health records the failed attempt
- future scheduled refreshes continue

No partially validated or non-durable candidate is published.

## Dedicated SQLite Storage

`SqliteForgeSnapshotRepository` owns a Forge-specific SQLite schema. It must use
a database separate from the Pi contact database.

The repository refuses to initialize Forge snapshot tables in a database that
appears to contain the Rolling Thunder application contact schema.

One transaction replaces:

- aggregate snapshot metadata
- monotonically increasing revision
- provider fetch timestamps
- all canonical spot rows

Stored rows preserve:

- stable provider identity
- normalized callsign
- optional operator name
- optional grid
- integer frequency
- normalized radio mode
- display mode
- UTC source timestamp
- bounded source metadata
- optional POTA park metadata

Loading reconstructs provider slices and the complete `SpotSnapshot`, then
revalidates canonical ordering, duplicate collapse, identities, timestamps, and
provider composition before returning durable state.

Malformed or inaccessible durable data raises a typed storage error.

## Startup Behavior

On process composition:

- the last durable snapshot is loaded and revalidated when available
- its revision and complete provider slices become the initial published state
- provider health is marked degraded because the data is retained rather than a
  successful live refresh from the current process
- the HTTP listener can serve this retained state immediately
- a successful live refresh clears retained/startup degradation

When no durable snapshot exists, the process starts with revision `0` and an
empty snapshot.

A storage-load error is exposed through bounded health state instead of
silently publishing malformed data. A repository initialization failure remains
a process-start failure because no safe durability boundary exists.

## Refresh Lifecycle

`ForgeSpotPollingService` owns the configured refresh lifecycle.

It provides:

- a required positive interval
- optional immediate refresh on start
- injected scheduling for deterministic tests
- explicit start and stop
- cancellation of future callbacks
- no real sleeps in unit tests
- continued future attempts after provider or persistence failures

The aggregation service serializes refreshes. If a refresh is already executing,
an overlapping request returns the currently published state rather than
starting another provider operation.

The production `ThreadedPollScheduler` uses a cancellable daemon thread. Its
callback boundary intentionally catches and logs unexpected exceptions so one
unanticipated failure cannot silently terminate all future refresh attempts.

## Published Immutable State

The aggregation service publishes one immutable `ForgeAggregationState` behind
a small lock.

It contains:

- snapshot revision
- complete canonical `SpotSnapshot`
- deterministic provider-health entries
- optional startup-storage error
- optional persistence error

Provider health contains:

- provider family
- `starting`, `healthy`, `degraded`, or `unavailable`
- active spot count
- last attempt timestamp
- last success timestamp
- bounded last error

A failed provider with a retained active slice is `degraded`. A failed provider
without retained data is `unavailable`.

## Versioned REST API

The service exposes two read-only endpoints:

```text
GET /api/v1/health
GET /api/v1/spots
```

Both return deterministic UTF-8 JSON with:

```text
Content-Type: application/json; charset=utf-8
Cache-Control: no-store
```

Unknown paths return `404`. Unsupported methods return `405` with
`Allow: GET`.

Request handlers only read the already-published immutable state. They never:

- contact a provider
- schedule a refresh
- write SQLite
- access radio or hardware
- perform CAT or tuning

### Health response

`GET /api/v1/health` contains:

- `api_schema_version`
- `service_status`
- `snapshot_revision`
- `snapshot_generated_at`
- `active_spot_count`
- `providers`
- `startup_storage_error`
- `persistence_error`

Overall service status is derived as:

- `starting` when all configured providers are starting and storage is clean
- `healthy` when all configured providers are healthy and storage is clean
- `unavailable` when no durable/live data exists and configured providers are
  unavailable
- `degraded` for retained data, partial provider failure, or storage errors

### Spot response

`GET /api/v1/spots` contains:

- `api_schema_version`
- `snapshot_revision`
- `generated_at`
- complete canonical `spots`
- provider health and age metadata

Shared value-type serialization is preserved. Frequencies are serialized as
plain integer hertz, not nested objects or floating-point kilohertz.

## Logging and Failure Boundaries

The process logs lifecycle, HTTP access, provider, validation, persistence, and
scheduler failures through the `rolling_thunder.forge_spots` logger.

Externally derived error text exposed in state is trimmed and bounded. The
service does not log complete provider payloads, credentials, secrets, or
authentication responses.

Provider and persistence failures do not replace active data. A safe process
configuration or repository initialization failure prevents startup and returns
a nonzero exit code.

## Security Posture

The default HTTP bind is loopback-only. This checkpoint does not provide or
claim:

- public network exposure
- TLS
- authentication
- reverse-proxy configuration
- firewall rules
- systemd installation
- production deployment hardening

Those concerns must be implemented as a separate deployment checkpoint before
the API is exposed beyond a trusted local boundary.

## Explicit Safety Boundary

The Forge spot service performs no:

- CAT commands
- radio connection or polling
- band, frequency, or mode changes
- receive tuning
- PTT, MOX, keying, tuner, power, or transmission control
- Tkinter work
- contact logging
- modification of the Pi contact database

`ReceiveTuningService` remains the only receive-tuning authority in the Pi
application.

## Scope Exclusions

Checkpoint 4 intentionally excludes:

- DXSpider provider implementation
- Forge-side QRZ enrichment or caching
- Pi Forge HTTP client
- Pi durable shared-spot snapshots
- migration of the running POTA panel
- a unified POTA/DX panel
- two-press runtime tuning
- authentication, TLS, reverse proxy, firewall, systemd, or deployment
- Wavelog changes
- dashboard or live-map changes
- any radio or transmit authority

## Automated Validation

The checkpoint is covered without public internet, credentials, hardware,
production paths, or real clock sleeps.

Tests cover:

- typed Forge configuration
- provider slices and deterministic fakes
- POTA normalization and typed failures
- transactional snapshot replacement and revision
- durable startup reconstruction and malformed-data rejection
- multi-provider composition
- persistence-before-activation
- retained slices on provider and persistence failure
- successful empty slices
- non-overlapping refresh behavior
- polling start, stop, cancellation, and recovery
- health transitions
- deterministic REST serialization
- unsupported methods and unknown paths
- process composition without real sockets or provider traffic
