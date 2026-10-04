# Forge Spot Aggregation Service

## Purpose

The Forge spot aggregation service is the independent Rolling Thunder process that prepares provider-neutral POTA and DX spot snapshots for mobile clients.

It is deliberately separate from the Raspberry Pi `ApplicationRuntime`. Forge performs no radio, CAT, receive tuning, contact logging, Tkinter, PTT, MOX, keying, tuner, power, or transmit-control work.

The Pi remains local-first. Loss of Forge, WireGuard, cellular service, POTA, DX Summit, DXSpider, QRZ, or the public Internet must not prevent local contact logging or replacement of the Pi's last durable valid shared-spot snapshot with malformed/incomplete data.

Checkpoint 8 of GitHub issue #148 completes the production deployment boundary and the Pi-side two-press shared-spot workflow while preserving `ReceiveTuningService` as the sole radio tuning authority.

## Process boundary

The independent console entry point is:

```text
rolling-thunder-forge-spots --config <path>
```

The composition root is `rolling_thunder.forge_spot_main`. It owns:

1. Forge YAML loading and validation
2. environment-backed QRZ secret loading
3. Forge SQLite initialization and retained snapshot reconstruction
4. enabled POTA and exactly one DX source (DX Summit preferred; DXSpider legacy)
5. optional QRZ enrichment
6. provider refresh scheduling
7. transactional aggregate persistence
8. immutable published aggregation state
9. the read-only HTTP listener
10. orderly shutdown

The HTTP listener starts before optional refresh-on-start work. A retained SQLite snapshot can therefore be served immediately while the first live provider refresh is still running.

Forge is not composed into the Pi UI and is not a radio-control service.

## Configuration

Safe development example:

```text
config/forge-spots.example.yaml
```

Production-oriented example:

```text
config/forge-spots.production.example.yaml
```

Supported production deployment config:

```text
/etc/rolling-thunder/forge-spots.yaml
```

### Server, storage, and lifecycle

Typed configuration includes:

- `server.bind_host`
- `server.bind_port`
- `storage.database_path`
- `aggregation.refresh_interval_s`
- `aggregation.refresh_on_start`
- `logging_level`

Development defaults remain conservative. The accepted production deployment binds only to Forge's RadioLAN address on TCP 8766 and stores durable state outside the application checkout.

### POTA provider

The `pota` section includes:

- `enabled`
- `base_url`
- `request_timeout_s`

`ForgePotaSpotProvider` reuses the typed public POTA HTTP source and maps provider records into shared `SpotRecord` values.

The mapping preserves normalized activator callsign, integer-hertz frequency, normalized radio mode, provider display mode, source timestamp, stable POTA identity, park reference, optional park name/location/grid coordinates, and bounded source comments.

A successful empty provider result is a valid complete empty slice. A nonempty public response that yields no usable typed records is a provider failure rather than silently replacing active data with an empty slice.

### DX sources

Forge permits at most one DX source at a time.

#### DX Summit IRC

The preferred source is the persistent read-only DX Summit IRC feed. Forge opens one connection, registers once, joins `#CQDX` once, answers IRC `PING` with `PONG`, and continuously ingests `dxs` spot messages into a bounded in-memory cache.

Normal Forge aggregation refreshes read that cache only. They never reconnect upstream or issue IRC commands. Connection age alone never causes recycling; a healthy socket may remain connected for the entire 30–90 day Forge process lifetime. Reconnection occurs only after a genuine connection failure or an extended no-traffic timeout, using bounded exponential backoff.

#### DXSpider fallback

DXSpider remains available only as a legacy fallback and is disabled in the production example. If explicitly enabled, it follows the same etiquette-safe lifecycle: Forge connects once, logs in once, sends `set/page 0` and one `show/fdx` seed per real connection, then remains connected and consumes live `DX de` lines.

Normal aggregation refreshes read the DXSpider cache only and perform no network I/O. Forge sends `bye` only during intentional service shutdown. A failed connection reconnects with bounded exponential backoff; connection age alone never triggers reconnect.

DX Summit and DXSpider cannot be enabled simultaneously because both represent the single shared DX provider family.

## DX normalization and mode resolution

Canonical realtime DX records are normalized into shared `SpotRecord` values.

The parser preserves:

- normalized DX callsign
- stable DX identity based on callsign and integer frequency
- exact decimal-kilohertz to integer-hertz conversion
- UTC source time reconstructed from `HHMMZ`
- deterministic previous-day rollover near UTC midnight
- bounded spotter metadata
- bounded provider comment
- mode-resolution provenance

DX records contain no POTA metadata.

Mode resolution is deterministic:

1. recognized explicit comment tokens take precedence
2. `FT8`, `FT4`, `RTTY`, `PSK`, `JT65`, `JS8`, and `DATA` normalize to data-family modes
3. explicit `SSB` resolves to LSB below 10 MHz and USB at or above 10 MHz
4. explicit `CW`, `AM`, `FM`, `LSB`, and `USB` map directly
5. otherwise the documented amateur-band/sub-band fallback is used

The normalized mode is action-critical on the Pi. Provider display mode remains available for presentation.

## QRZ enrichment

Forge-side QRZ enrichment is optional.

QRZ may fill only missing operator name and Maidenhead grid values. Provider values always win.

Enrichment never changes:

- provider
- stable identity
- callsign
- frequency
- normalized mode
- display mode
- source timestamp
- source metadata
- POTA park metadata

The cache is thread-safe and bounded, with normalized callsign keys, positive and negative entries, independent TTLs, deterministic maximum size, and LRU-style eviction.

Live lookups obey the configured minimum spacing and lookup budget per provider refresh. Cache hits do not consume live-lookup spacing.

QRZ lookup failures do not convert provider success into provider failure. The complete original provider slice remains usable.

### Secret boundary

Credentials are never stored in YAML. When QRZ enrichment is enabled, both environment variables are required:

```text
ROLLING_THUNDER_QRZ_USERNAME
ROLLING_THUNDER_QRZ_PASSWORD
```

The production environment file is:

```text
/etc/rolling-thunder/forge-spots.env
```

Missing enabled QRZ credentials are a startup configuration error. Runtime QRZ outages after startup are nonfatal enrichment degradation.

## Provider and aggregation boundary

`ForgeSpotProvider` is a synchronous provider-neutral protocol used only by the Forge refresh core.

A provider returns one complete immutable provider slice. Records must already be canonical, duplicate-free, provider-consistent, and deterministically ordered.

A successful refresh follows this order:

1. fetch one complete provider slice outside request handling
2. validate and canonicalize the slice
3. apply bounded best-effort QRZ enrichment when enabled
4. combine it with retained active slices from other providers
5. build and validate one complete candidate `SpotSnapshot`
6. transactionally persist the candidate and provider metadata
7. receive the new durable revision
8. atomically publish the immutable aggregation state

The in-memory active snapshot is never replaced before persistence succeeds.

If fetch, parsing, normalization, validation, or persistence fails:

- the previous active slice for that provider remains active
- successful slices from other providers remain active
- the previous aggregate snapshot remains active until a durable replacement exists
- the prior revision remains active for the failed attempt
- provider health records the failure
- future scheduled refreshes continue

One provider's success never hides another provider's failure.

## Dedicated SQLite storage

`SqliteForgeSnapshotRepository` owns a Forge-specific SQLite schema separate from the Pi contact database.

The repository refuses to initialize Forge snapshot tables in a database that appears to contain the Rolling Thunder application contact schema.

One transaction replaces aggregate metadata, revision, provider fetch metadata, and all canonical spot rows.

Loading reconstructs provider slices and the complete `SpotSnapshot`, then revalidates identities, ordering, duplicate collapse, timestamps, and provider composition before publishing retained state.

Production database:

```text
/var/lib/rolling-thunder/forge-spots.db
```

A restored or migrated database must pass SQLite integrity validation. Live databases must be copied with SQLite backup semantics rather than an uncoordinated file copy.

## Startup and degradation behavior

On startup:

- the last durable snapshot is loaded and revalidated when available
- its revision/provider slices become the initial published state
- retained provider health begins degraded until live refresh succeeds
- the REST API can serve retained data immediately
- each provider independently becomes healthy after a successful live refresh

If no durable snapshot exists, the process starts with revision 0 and an empty snapshot.

If DX fails while POTA succeeds, retained DX data remains active when available and DX is degraded/unavailable while POTA can remain healthy. The reverse is also true.

A storage-load error is exposed through health state. Repository initialization failure remains a process-start failure because there is no safe durability boundary.

## Refresh lifecycle

`ForgeSpotPollingService` owns two distinct local publication cadences:

- the normal provider refresh cadence, which remains 60 seconds by default and may perform external provider work such as POTA HTTP retrieval
- an optional fast DX-cache publication cadence, 5 seconds by default, enabled only when a persistent DX Summit or DXSpider source is configured

The fast DX cadence calls only the persistent provider's in-memory `fetch_slice()`. It never opens, closes, refreshes, or otherwise touches the upstream IRC/DXSpider socket. This keeps live DX publication responsive without increasing external connection or command frequency.

At process startup the first complete refresh can occur while the persistent DX source is still connecting. In that case retained DX data remain available as degraded when present, and the fast local DX publication cadence promotes the live cache as soon as the source is ready rather than waiting for the next full provider interval.

`ForgeSpotPollingService` otherwise supports:

- positive bounded refresh interval
- optional immediate refresh on start
- deterministic injected scheduling in tests
- explicit start/stop
- cancellation of future callbacks
- continued attempts after provider/persistence failures

Providers refresh in deterministic provider order. Aggregation refreshes are serialized. If a refresh is already running, an overlapping request observes current published state rather than starting a second provider operation.

The production scheduler uses a cancellable daemon thread and catches/logs unexpected callback exceptions so one unanticipated provider failure cannot silently terminate future refresh attempts.

## Published immutable state

The aggregation service publishes one immutable `ForgeAggregationState` behind a small lock.

It contains:

- snapshot revision
- complete canonical `SpotSnapshot`
- deterministic health entries for all enabled providers
- optional startup-storage error
- optional persistence error

Provider health includes:

- provider family
- `starting`, `healthy`, `degraded`, or `unavailable`
- active spot count
- last attempt timestamp
- last success timestamp
- bounded last error

A failed provider with retained active data is degraded. A failed provider without retained data is unavailable.

## Versioned REST API

The service exposes two read-only endpoints:

```text
GET /api/v1/health
GET /api/v1/spots
```

Responses are deterministic UTF-8 JSON with `Cache-Control: no-store`.

Unknown paths return 404. Unsupported methods return 405 with `Allow: GET`.

Request handlers only read already-published immutable state. They never:

- contact POTA, DX Summit, DXSpider, or QRZ
- schedule a refresh
- write SQLite
- access radio/hardware
- perform CAT or tuning

### Health response

The health endpoint exposes API schema version, service status, revision, generation time, active spot count, provider health, startup-storage error, and persistence error.

When a persistent DX source is configured, health also exposes a read-only `dx_connection` object with the source name, lifecycle state, host/port, optional channel/nickname, connection start time, last received traffic, last accepted spot, reconnect count, current bounded cache size, and last connection error. Reading this telemetry performs no provider network I/O and does not reset or refresh the upstream connection.

Overall status is:

- `starting` while configured providers are starting and storage is clean
- `healthy` when configured providers are healthy and storage is clean
- `unavailable` when no durable/live data exists and providers are unavailable
- `degraded` for retained data, partial provider failure, or storage errors

### Spot response

The spot endpoint exposes API schema version, snapshot revision, generation time, the complete canonical combined POTA/DX spot set, and provider health/age metadata.

Frequencies are serialized as integer hertz. Stable identity serialization distinguishes POTA and DX records.

## Logging and diagnostics

The process logs lifecycle, HTTP access, provider, validation, persistence, and scheduler failures through `rolling_thunder.forge_spots`.

Externally derived error strings are bounded. The service does not log complete provider responses, QRZ passwords, QRZ usernames as secrets, session keys, or authentication responses.

Production logging is captured by journald through systemd.

See `docs/FORGE_DEPLOYMENT.md` for lifecycle and diagnostic commands.

## Production deployment

Checkpoint 8 formalizes the supported Forge deployment.

Production runs:

- on host `forge`
- as system account `rollingthunder`
- from `/opt/rolling-thunder-forge`
- with venv `/opt/rolling-thunder-forge/.venv`
- with config `/etc/rolling-thunder/forge-spots.yaml`
- with database `/var/lib/rolling-thunder/forge-spots.db`
- through `rolling-thunder-forge-spots.service`
- on `192.168.9.170:8766`

The service uses `Restart=on-failure` and is enabled at boot after production acceptance.

The complete installation, update, smoke-test, lifecycle, security, recovery, and rollback procedure is authoritative in:

```text
docs/FORGE_DEPLOYMENT.md
```

## Security posture

The REST API does not currently provide TLS or application-layer authentication.

That is an explicit checkpoint-8 trust-boundary decision, not an implied security feature. Production binds only to the Forge RadioLAN address rather than every interface and is intended to be reachable only through the trusted private routed RadioLAN/CarLAN-over-WireGuard environment.

The deployment assumes:

- no public Internet port forwarding to TCP 8766
- no UPnP exposure
- OPNsense remains the routed security boundary
- mobile access occurs through WireGuard
- intended private networks only can reach the Forge API

Anyone who can reach TCP 8766 can read the health and spot endpoints. The API exposes no radio-control operations or credentials, but the lack of API authentication is an explicit residual risk.

If the API is ever exposed outside the trusted private network, TLS and authentication must be implemented first.

## Pi client and offline behavior

When Forge mode is enabled, the Pi polls Forge rather than also establishing a second direct public POTA authority.

The Pi validates the complete response before atomically replacing its shared-spot snapshot and persists the latest valid snapshot locally.

If Forge or transport fails, the Pi retains the previous durable valid snapshot and reports truthful age/error state. Local contact logging remains authoritative and available.

## Shared POTA/DX operator workflow

Checkpoint 8 completes the shared Pi-side operator workflow for both provider families.

POTA and DX use the same shared selection/staging architecture with independent provider filter state.

Supported mobile band filters include 80, 40, 20, 17, 15, 12, and 10 meters. Entering a provider context prefers the current supported FT-891 band and otherwise falls back safely to 20 meters.

Supported mode groups are SSB, CW, FT4, FT8, DATA, and ALL. DX initially uses ALL mode while preserving its own filter state independently from POTA.

Every action-critical context/filter/selection mutation clears staging when the staged exact target is no longer valid. A neighboring row is never substituted automatically.

### Two-press contract

The operator workflow is:

```text
navigate / selection changes
    -> staging clears

first activation
    -> stage exact identity/callsign/frequency/mode
    -> no CAT command

second activation of the same still-valid target
    -> submit exact staged action
    -> ReceiveTuningService performs ordered receive tuning
    -> staging clears on success or failure
```

Staging is invalidated by selection changes, provider/context changes, band/mode filters, identity disappearance, action-critical mutation, Back/Cancel, unusable radio state, tuning success, or tuning failure.

## Explicit radio-safety boundary

Forge performs no CAT and has no receive or transmit authority.

On the Pi, `ReceiveTuningService` remains the sole receive-tuning authority. Shared spot UI/controllers, physical-control adapters, and background boundaries may stage/submit an exact receive action but may not issue CAT directly.

The service/workflow must not add:

- PTT or MOX
- keying
- tuner control
- power control
- transmit automation
- unattended tuning
- voice-originated tuning

Receive tuning preserves the existing band-before-frequency ordering and ATAS warning behavior.

## Checkpoint-8 production acceptance

The first checkpoint-8 production deployment was accepted on Forge from application commit:

```text
9300cbc3cd8aa4335ca6071d6d8cfa80d267b8c0
```

Infrastructure acceptance demonstrated:

- dedicated `rollingthunder` process identity
- working directory `/opt/rolling-thunder-forge`
- production config `/etc/rolling-thunder/forge-spots.yaml`
- persistent SQLite integrity validation
- side-by-side smoke execution on an isolated port/database
- successful live DXSpider refresh
- successful live POTA refresh
- healthy production REST on `192.168.9.170:8766`
- old interactive `geoff` process retired
- `Restart=on-failure`
- five-second restart delay
- service active and enabled at boot
- real Pi requests reaching `/api/v1/spots` over the private routed path

Final FT-891 end-to-end operator acceptance remains a separate checkpoint-8 gate until the physical two-press receive-only bench is completed.
