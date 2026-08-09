# Pi Retained Forge Weather

Checkpoint #164 adds the Raspberry Pi client/state layer for weather already retained by Forge. This checkpoint deliberately adds no weather panel, map-temperature presentation, repeater behavior, CAT behavior, or radio authority.

## Boundary

The Pi consumes only the Rolling Thunder Forge API:

`GET /api/v1/weather`

The Pi does not contact Open-Meteo or any other public weather provider through this retained-weather path. Provider selection, provider-specific fields, public-network retrieval, normalization, and Forge-side retention remain Forge responsibilities.

## Runtime flow

1. Forge maintains its retained provider-neutral weather state.
2. The Pi weather poller schedules approximately every 15 minutes by default.
3. A dedicated bounded background worker calls the typed Forge weather client.
4. The client validates API schema version, revision/stale consistency, remote health, and the complete `WeatherSnapshot` domain.
5. A newly accepted snapshot is written transactionally to the existing Pi application SQLite database.
6. Only after that write succeeds is the new immutable state published as `LIVE`.
7. Tkinter and later checkpoint #165 consumers read only the already-published immutable state; they perform no weather network or storage I/O.

## Pi state model

The application-facing state distinguishes availability/origin from local failure cause.

Availability/origin:

- `disabled` — `forge.weather.enabled` is false; no Pi weather worker exists.
- `no_data` — no usable retained snapshot exists yet.
- `live` — the latest accepted Forge snapshot was persisted and published successfully.
- `retained` — a previously accepted last-good snapshot is being retained, including after process restart or a later failure.

Local failure causes are independently represented as:

- `transport`
- `validation`
- `storage_read`
- `storage_write`

A failure does not require discarding still-usable weather. For example, a transport failure may publish `retained` plus `transport` while preserving the prior snapshot and its original source time.

## Freshness

Weather age is never reset merely because anvilmobile restarts or refreshes the UI.

The durable cache retains the complete normalized result, including:

- Forge weather revision;
- provider `source_at` time;
- Forge/provider `fetched_at` time embedded in the snapshot;
- Pi `received_at` time;
- remote Forge weather health.

The Pi evaluates staleness using provider `source_at` in addition to Forge's own stale flag. The default local stale threshold is 1,800 seconds. A process restart therefore cannot turn old retained weather into apparently fresh weather.

## Persistence-before-publication

The Pi uses schema version 9 and a singleton `forge_weather_cache` table in the existing Rolling Thunder application database.

The repository stores a fully serialized `ForgeWeatherClientResult` together with explicit revision, source time, and receive time metadata. Reads revalidate both the typed payload and those metadata cross-checks.

For a newly fetched snapshot:

1. validate the full response;
2. transactionally replace the durable cache;
3. publish the new immutable `LIVE` state.

If step 2 fails, the candidate snapshot is not published. The prior last-good snapshot remains authoritative and the state reports a `storage_write` error.

## Polling and concurrency

Default Pi retained-weather configuration:

```yaml
forge:
  enabled: true
  api_url: http://forge:8766
  weather:
    enabled: true
    refresh_interval_s: 900.0
    refresh_on_start: true
    stale_after_s: 1800.0
```

The weather poller owns a dedicated single-worker executor. Repeating callbacks coalesce while a refresh is already pending/running; slow network responses cannot create overlapping or unbounded weather jobs.

Weather polling is independent from Forge spot polling and Pi-to-Forge GPS location publication.

## Failure isolation

Retained weather failure must not change or block:

- local contact logging;
- GPS acquisition or Pi-to-Forge location publishing;
- base-map or radar operation;
- physical controls;
- radio polling or receive tuning authority;
- POTA/DX shared spots;
- contact synchronization or local storage outside the weather-cache transaction.

No #164 component has PTT, MOX, keying, tuner, transmit-power, or unattended-transmit authority.

## Acceptance for checkpoint #164

Before merge, the exact PR head must satisfy:

- Ruff;
- strict MyPy;
- full pytest;
- valid migration from the existing Pi database schema to schema 9;
- controlled anvilmobile fetch from the real production Forge `/api/v1/weather` endpoint;
- proof that the fetched snapshot is persisted before publication;
- proof that a new process/runtime instance starts from the durable snapshot as `retained` without changing provider source age;
- proof that normal Forge spots, GPS/map operation, local SQLite integrity, and the dashboard remain unaffected;
- Draft PR remains unmerged until explicit repository-owner authorization.

Checkpoint #165 owns the actual weather panel and map-temperature presentation.