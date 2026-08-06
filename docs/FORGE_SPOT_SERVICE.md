# Forge Spot Aggregation Service

## Purpose

The Forge spot aggregation service is an independent process that prepares
provider-neutral POTA and DX spot snapshots for later Rolling Thunder clients.

It is not part of the Raspberry Pi `ApplicationRuntime`. It performs no radio,
CAT, receive-tuning, contact-logging, Tkinter, or transmit-control work. The Pi
remains local-first and continues to operate when Forge, WireGuard, cellular
service, a DX cluster, QRZ, or the public internet is unavailable.

Checkpoint 4 of GitHub issue #129 established the independent process, typed
configuration, complete provider slices, transactional SQLite snapshots,
retained startup state, background refresh, and versioned read-only REST.

Checkpoint 5 adds:

- a configurable bounded DXSpider snapshot provider
- deterministic DX line parsing and mode inference
- optional provider-neutral QRZ name and grid enrichment
- bounded positive and negative QRZ caching
- QRZ lookup spacing and per-provider-refresh lookup budgets
- POTA-only, DX-only, and combined process composition
- environment-only QRZ credentials
- combined persistence, startup reconstruction, health, and REST behavior

## Process Boundary

The service runs through the separate console entry point:

```text
rolling-thunder-forge-spots --config config/forge-spots.yaml
```

The composition root is `rolling_thunder.forge_spot_main`. It owns:

1. Forge YAML loading and validation
2. environment-backed QRZ secret loading
3. Forge-specific SQLite initialization
4. enabled POTA and DXSpider provider composition
5. optional QRZ provider decoration
6. aggregation and publication state
7. background refresh scheduling
8. the read-only HTTP listener
9. orderly shutdown

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

### Server, storage, and lifecycle

The typed configuration includes:

- `server.bind_host`
- `server.bind_port`
- `storage.database_path`
- `aggregation.refresh_interval_s`
- `aggregation.refresh_on_start`
- `logging_level`

The default bind address is `127.0.0.1`. The default database is a relative
Forge-only path resolved relative to the YAML file.

### POTA provider

The `pota` section includes:

- `enabled`
- `base_url`
- `request_timeout_s`

POTA remains enabled by default.

### DXSpider provider

The `dxspider` section includes:

- `enabled`
- `host`
- `port`
- `login_callsign`
- `connect_timeout_s`
- `read_timeout_s`
- `max_response_bytes`
- `max_spots`
- `max_spot_age_s`

DXSpider is disabled by default. The initial adapter targets public
DXSpider-compatible nodes that accept callsign-only login. Password-authenticated
or private cluster nodes are outside this checkpoint.

### QRZ enrichment

The `qrz` section includes:

- `enabled`
- `request_timeout_s`
- `minimum_request_interval_s`
- `max_lookups_per_refresh`
- `positive_ttl_s`
- `negative_ttl_s`
- `max_cache_entries`

QRZ enrichment is disabled by default.

Credentials are never stored in YAML. When QRZ enrichment is enabled, both of
the existing environment variables are required at startup:

```text
ROLLING_THUNDER_QRZ_USERNAME
ROLLING_THUNDER_QRZ_PASSWORD
```

Missing or incomplete enabled QRZ credentials are a configuration error. QRZ
runtime outages after startup are nonfatal enrichment degradation.

### Validation

Configuration rejects:

- blank bind or DXSpider hosts
- ports outside 1 through 65535
- blank or current-directory-only database paths
- invalid DXSpider login callsigns
- nonpositive or excessive refresh and network timeouts
- unsafe response-byte, spot-count, or spot-age bounds
- malformed public HTTP URLs
- invalid QRZ cache, TTL, spacing, or refresh-budget values
- unsupported logging levels
- unknown keys

At least one of POTA or DXSpider must be enabled. POTA-only, DX-only, and
combined operation are valid.

## Provider Boundary

`ForgeSpotProvider` is a synchronous provider-neutral protocol used only by the
Forge refresh core. A provider exposes:

- one `SpotProvider` family
- one `fetch_slice()` operation
- a complete immutable `ForgeProviderSlice`
- a timezone-aware fetch timestamp
- typed connection, response, and normalization failures

A provider slice contains one provider family only. Its records must already be
canonical, duplicate-free, and deterministically ordered through the shared spot
domain.

`MockForgeSpotProvider` provides deterministic provider behavior for tests and
development.

## POTA Provider

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

A successful empty public provider result is a valid complete empty slice. A
nonempty public response that produces no usable typed records is treated as a
provider failure rather than silently activating an empty result.

## DXSpider Snapshot Session

`ForgeDxSpiderSpotProvider` preserves the complete-slice boundary by opening one
short-lived bounded TCP session per DX refresh. It does not maintain a long-lived
stream or a second independent spot authority.

The adapter performs this sequence:

1. open a standard-library TCP connection under the configured connect timeout
2. apply the configured read timeout
3. send the configured amateur callsign
4. send `set/page 0`
5. send `show/fdx`
6. send `bye`
7. read until orderly server closure under the response-byte limit
8. strip common telnet negotiation sequences
9. parse the complete bounded response
10. close the session on every success or failure path

Banners, prompts, and unrelated cluster lines are ignored. Complete server
responses and credentials are never logged.

The response is bounded by:

- connect timeout
- read timeout
- maximum response bytes
- maximum parsed spots
- maximum accepted spot age

A clean response with no `DX de` lines is a valid empty DX slice. A response
containing spot-like lines but no usable records is a typed provider failure.

## DX Parsing and Mode Resolution

Canonical realtime records beginning with `DX de` are normalized into shared
`SpotRecord` values.

The parser preserves:

- normalized DX callsign
- stable DX identity based on callsign and integer frequency
- exact decimal-kilohertz to integer-hertz conversion
- UTC source time reconstructed from `HHMMZ`
- deterministic previous-day rollover around UTC midnight
- spotter callsign as bounded source metadata
- bounded provider comment as source metadata
- mode-resolution provenance as bounded source metadata

DX records contain no POTA metadata.

Mode resolution is deterministic:

1. recognized explicit comment tokens take precedence
2. `FT8`, `FT4`, `RTTY`, `PSK`, `JT65`, `JS8`, and `DATA` map to `DATA`
3. explicit `SSB` maps to LSB below 10 MHz and USB at or above 10 MHz
4. explicit `CW`, `AM`, `FM`, `LSB`, and `USB` map directly
5. otherwise a documented amateur-band and sub-band fallback is used

The shared normalized radio mode drives future action staging. The original or
inferred display mode remains available for presentation, and metadata records
whether the result came from an explicit token or fallback.

This checkpoint does not tune a radio from a DX spot.

## Forge-Side QRZ Enrichment

`ForgeQrzEnricher` runs after a provider returns a complete validated slice and
before aggregation persistence. `ForgeQrzEnrichedSpotProvider` applies the
enricher without changing the underlying provider family or failure semantics.

QRZ may fill only missing:

- operator name
- Maidenhead grid

Provider values always win. Enrichment never changes:

- provider
- stable identity
- callsign
- frequency
- normalized mode
- display mode
- source timestamp
- source metadata
- POTA park metadata

Lookups are deduplicated by normalized callsign within each provider refresh.
The existing QRZ XML adapter supplies authenticated sessions, bounded HTTP
timeouts, session renewal, not-found handling, name normalization, and validated
optional grids.

### Cache and rate limits

The thread-safe in-memory QRZ cache provides:

- normalized callsign keys
- positive entries for usable profiles
- negative entries for not-found results
- independent positive and negative TTLs
- deterministic maximum size
- LRU-style eviction
- no credentials, passwords, or session keys in cache values

Cache hits do not consume live-lookup spacing. Live calls obey the configured
minimum interval and maximum lookup count for each provider refresh. When the
budget is exhausted, remaining records stay valid and unenriched.

### Failure behavior

QRZ connection, timeout, authentication, response, validation, not-found, and
other lookup failures do not convert provider success into provider failure.
The original complete provider slice remains usable. Per-attempt diagnostics are
bounded and contain counts, budget state, and at most one bounded error string;
they contain no credentials or session keys.

The Pi-side contact QRZ fallback remains independent and unchanged.

## Persistence-Before-Activation Rule

A provider refresh follows this order:

1. fetch one complete provider slice outside request handling
2. validate and canonicalize the provider slice
3. apply bounded best-effort QRZ enrichment when enabled
4. combine it with previously active slices from other providers
5. build and validate one complete candidate `SpotSnapshot`
6. transactionally persist the complete snapshot and provider-slice metadata
7. receive the new durable revision from the repository
8. atomically publish the new immutable aggregation state

The in-memory active snapshot is never changed before persistence succeeds.

If provider fetch, parsing, normalization, candidate validation, or persistence
fails:

- the previous slice for that provider remains active
- successful slices from other providers remain active
- the previous aggregate snapshot remains active until a durable replacement
- the previous revision remains active on the failed attempt
- health records the provider-specific failure
- future scheduled refreshes continue

A QRZ-only failure does not trigger this provider-failure path.

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
- optional enriched or provider-supplied operator name
- optional enriched or provider-supplied grid
- integer frequency
- normalized radio mode
- display mode
- UTC source timestamp
- bounded source metadata
- optional POTA park metadata

Loading reconstructs provider slices and the complete `SpotSnapshot`, then
revalidates canonical ordering, duplicate collapse, identities, timestamps, and
provider composition before returning durable state.

Existing checkpoint-4 databases use the same canonical spot fields and require
no destructive migration for DX or QRZ data.

## Startup and Degradation Behavior

On process composition:

- the last durable snapshot is loaded and revalidated when available
- its revision and complete provider slices become the initial published state
- retained provider health is marked degraded until a live refresh succeeds
- the HTTP listener can serve retained combined POTA and DX state immediately
- successful live refreshes clear degradation for their provider independently

When no durable snapshot exists, the process starts with revision `0` and an
empty snapshot.

If DX fails while POTA succeeds, the prior DX slice remains active and DX health
is degraded or unavailable while POTA health is healthy. The reverse is also
true. One provider's success never hides the other provider's failure.

A storage-load error is exposed through bounded health state instead of
silently publishing malformed data. Repository initialization failure remains a
process-start failure because no safe durability boundary exists.

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

Providers refresh in deterministic provider order. The aggregation service
serializes refreshes. If a refresh is already executing, an overlapping request
returns the currently published state rather than starting another provider
operation.

The production `ThreadedPollScheduler` uses a cancellable daemon thread. Its
callback boundary catches and logs unexpected exceptions so one unanticipated
failure cannot silently terminate future refresh attempts.

## Published Immutable State

The aggregation service publishes one immutable `ForgeAggregationState` behind
a small lock.

It contains:

- snapshot revision
- complete canonical `SpotSnapshot`
- deterministic provider-health entries for all enabled provider families
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

- contact POTA, DXSpider, or QRZ
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
- deterministic health entries for every enabled provider
- `startup_storage_error`
- `persistence_error`

Overall service status is:

- `starting` when all configured providers are starting and storage is clean
- `healthy` when all configured providers are healthy and storage is clean
- `unavailable` when no durable/live data exists and all configured providers
  are unavailable
- `degraded` for retained data, partial provider failure, or storage errors

### Spot response

`GET /api/v1/spots` contains:

- `api_schema_version`
- `snapshot_revision`
- `generated_at`
- complete canonical combined POTA and DX `spots`
- provider health and age metadata

Shared value-type serialization is preserved. Frequencies are serialized as
plain integer hertz, not nested objects or floating-point kilohertz. Stable
identity serialization distinguishes `pota` and `dx` records.

## Logging and Secret Boundaries

The process logs lifecycle, HTTP access, provider, validation, persistence, and
scheduler failures through the `rolling_thunder.forge_spots` logger.

Externally derived error text exposed in state is trimmed and bounded. The
service does not log:

- complete provider responses
- QRZ credentials or passwords
- QRZ session keys
- authentication responses

Provider and persistence failures do not replace active data. Unsafe process
configuration or repository initialization prevents startup and returns a
nonzero exit code.

## Security Posture

The default HTTP bind is loopback-only. This checkpoint does not provide or
claim:

- public network exposure
- TLS
- authentication for the Forge REST API
- reverse-proxy configuration
- firewall rules
- systemd installation
- production deployment hardening

Those concerns remain a separate deployment checkpoint before the API is
exposed beyond a trusted local boundary.

## Explicit Radio-Safety Boundary

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

Checkpoint 5 intentionally excludes:

- long-lived DXSpider streaming
- private or password-authenticated DX cluster nodes
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

The checkpoint is covered without public internet, real credentials, hardware,
production paths, or real sleeps.

Tests cover:

- typed POTA, DXSpider, and QRZ configuration
- telnet negotiation stripping
- bounded fake DXSpider login and command exchange
- connect/read timeout and response-size failures
- exact DX frequency conversion and UTC rollover
- malformed line rejection
- deterministic mode resolution and provenance
- valid empty and unusable nonempty DX responses
- canonical DX identity and duplicate collapse
- positive and negative QRZ caches
- independent TTL expiration and deterministic eviction
- QRZ lookup spacing and refresh budgets
- duplicate callsign lookup collapse
- provider-value precedence
- QRZ failure preserving provider success
- POTA-only, DX-only, and combined composition
- transactional combined snapshot persistence
- retained enriched startup reconstruction
- provider-specific degradation and retained slices
- deterministic combined REST serialization
- request handlers performing no provider, enrichment, or storage work
