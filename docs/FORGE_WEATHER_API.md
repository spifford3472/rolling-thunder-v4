# Forge Retained Weather API

## Purpose

Checkpoint #162 adds provider-neutral retained weather intelligence to the existing Forge process. Weather uses the latest accepted mobile location already retained by Forge, refreshes outside HTTP request handlers, persists the last complete valid snapshot in the existing Forge SQLite database, and is exposed read-only on the existing private listener.

Weather is optional intelligence. A weather-provider, network, validation, or weather-specific persistence failure must not prevent Forge spot aggregation, mobile-location retention, or the Pi's local core functions from operating.

The versioned endpoint is:

```text
GET /api/v1/weather
```

Production remains on the existing private listener:

```text
192.168.9.170:8766
```

No second daemon, port, or database file is introduced.

## Provider boundary

The initial provider is Open-Meteo, isolated behind the typed `WeatherProvider` boundary. Provider-specific WMO weather codes are not part of the Rolling Thunder API contract. Forge normalizes them into Rolling Thunder-owned condition and icon tokens before persistence or publication.

The Open-Meteo request is intentionally bounded to the fields needed by the current design:

- current temperature at 2 m
- current relative humidity at 2 m
- current weather code
- current day/night flag
- hourly temperature at 2 m
- hourly precipitation probability
- daily sunrise
- daily sunset

Forge requests UTC timestamps and retains up to six future hourly points, with a minimum of three required for a valid complete snapshot.

## Open-Meteo attribution

Open-Meteo API data are licensed under CC BY 4.0 and require attribution. The retained snapshot therefore carries explicit source metadata so downstream UI work can satisfy attribution without knowing provider-specific details.

The normalized source metadata currently is:

```json
{
  "provider_id": "open_meteo",
  "provider_name": "Open-Meteo",
  "attribution_text": "Weather data by Open-Meteo.com",
  "attribution_url": "https://open-meteo.com/",
  "license_name": "CC BY 4.0",
  "license_url": "https://creativecommons.org/licenses/by/4.0/"
}
```

Provider reference documentation:

- Forecast API: `https://open-meteo.com/en/docs`
- Licence and attribution: `https://open-meteo.com/en/license`

Any UI that displays Open-Meteo-derived weather must preserve a visible provider attribution link consistent with those terms.

## Provider-neutral snapshot

The retained snapshot owns its semantics independently of Open-Meteo:

```json
{
  "latitude": 39.524492,
  "longitude": -84.062475,
  "source_at": "2026-08-09T00:30:00Z",
  "fetched_at": "2026-08-09T00:35:00Z",
  "current": {
    "temperature_c": 22.4,
    "relative_humidity_percent": 78.0,
    "condition": "partly_cloudy",
    "icon": "partly_cloudy_night",
    "is_day": false
  },
  "hourly": [
    {
      "forecast_at": "2026-08-09T01:00:00Z",
      "temperature_c": 22.1,
      "precipitation_probability_percent": 10.0
    },
    {
      "forecast_at": "2026-08-09T02:00:00Z",
      "temperature_c": 21.7,
      "precipitation_probability_percent": 20.0
    },
    {
      "forecast_at": "2026-08-09T03:00:00Z",
      "temperature_c": 21.0,
      "precipitation_probability_percent": 30.0
    }
  ],
  "solar": {
    "sunrise_at": "2026-08-09T10:42:00Z",
    "sunset_at": "2026-08-10T00:41:00Z"
  },
  "source": {
    "provider_id": "open_meteo",
    "provider_name": "Open-Meteo",
    "attribution_text": "Weather data by Open-Meteo.com",
    "attribution_url": "https://open-meteo.com/",
    "license_name": "CC BY 4.0",
    "license_url": "https://creativecommons.org/licenses/by/4.0/"
  }
}
```

### Condition tokens

Supported provider-neutral condition tokens are:

```text
clear
partly_cloudy
cloudy
fog
drizzle
rain
freezing_rain
snow
showers
thunderstorm
unknown
```

### Icon tokens

Supported provider-neutral icon tokens are:

```text
clear_day
clear_night
partly_cloudy_day
partly_cloudy_night
cloudy
fog
drizzle
rain
freezing_rain
snow
showers
thunderstorm
unknown
```

The Pi UI should render these owned tokens rather than interpreting Open-Meteo/WMO codes itself.

## GET response

A retained weather response uses API schema version 1:

```json
{
  "api_schema_version": "1",
  "revision": 3,
  "stale": false,
  "snapshot": {
    "latitude": 39.524492,
    "longitude": -84.062475,
    "timezone": "America/New_York",
    "source_at": "2026-08-09T00:30:00Z",
    "fetched_at": "2026-08-09T00:35:00Z",
    "current": {
      "temperature_c": 22.4,
      "relative_humidity_percent": 78.0,
      "condition": "partly_cloudy",
      "icon": "partly_cloudy_night",
      "is_day": false
    },
    "hourly": [],
    "solar": {
      "sunrise_at": "2026-08-09T10:42:00Z",
      "sunset_at": "2026-08-10T00:41:00Z"
    },
    "source": {
      "provider_id": "open_meteo",
      "provider_name": "Open-Meteo",
      "attribution_text": "Weather data by Open-Meteo.com",
      "attribution_url": "https://open-meteo.com/",
      "license_name": "CC BY 4.0",
      "license_url": "https://creativecommons.org/licenses/by/4.0/"
    }
  },
  "health": {
    "status": "healthy",
    "stale": false,
    "revision": 3,
    "last_attempt_at": "2026-08-09T00:35:00Z",
    "last_success_at": "2026-08-09T00:35:00Z",
    "last_error": null,
    "startup_storage_error": null,
    "persistence_error": null
  }
}
```

The abbreviated `hourly` array above is illustrative; a persisted valid snapshot always contains at least three hourly points.
`timezone` is the provider-returned IANA identifier for the requested coordinates. It
is optional for new readers and lets downstream target-time presentation preserve
daylight-saving behavior without guessing offsets or mapping states. Because shared
wire models reject unknown fields, deployment compatibility is Pi-first: upgrade the
reader before a Forge response begins including this additive field.

When weather is enabled but no complete snapshot is yet available, the endpoint still returns HTTP 200 with `snapshot: null`, `stale: true`, revision 0, and truthful health such as `starting` or `unavailable`. When weather is disabled entirely, the endpoint returns HTTP 503 with a versioned `weather_unavailable` error.

Only GET is supported. Other methods return HTTP 405 with `Allow: GET`.

## Weather health

Weather provider health is independent from the core spot-service health:

- `starting`: configured but no refresh outcome yet
- `healthy`: latest required refresh succeeded and was durably retained
- `degraded`: a prior valid forecast is retained, but the latest required refresh failed
- `unavailable`: no valid retained forecast is available and refresh cannot currently provide one

`/api/v1/health` includes the same weather health as an additive `weather` object. Weather degradation does not by itself change the existing spot `service_status`; weather is optional intelligence rather than a prerequisite for POTA/DX service health.

## Refresh policy

Weather provider work never runs in an HTTP request handler. A lifecycle-managed background worker checks on a bounded schedule and permits only one in-flight refresh.

A refresh is required when any of the following is true:

- no retained complete forecast exists
- the retained forecast is at least `max_forecast_age_s` old
- the latest retained vehicle location is at least `movement_refresh_km` from the forecast coordinates

Current defaults are:

```text
check_interval_s: 60
max_forecast_age_s: 1800
movement_refresh_km: 10
refresh_on_start: true
```

A fresh nearby retained forecast causes no provider request.

If no retained mobile location is available, Forge does not call the weather provider. Weather reports unavailable/degraded status while the rest of Forge continues normally.

## Persistence and failure retention

Weather is stored in the same configured Forge SQLite database used by spots and mobile location, using independent tables:

```text
forge_weather_schema_metadata
forge_weather_snapshot
```

The snapshot table is a singleton row containing a monotonically increasing revision and the complete validated provider-neutral snapshot JSON.

Replacement uses a SQLite transaction. The candidate is persisted and committed before the new in-memory weather state is published.

A provider, transport, validation, or weather-persistence failure does not delete or replace the previous complete valid forecast. If one exists, Forge continues serving it with `stale: true` when the refresh policy requires newer/location-appropriate data and health explains the failed attempt.

A weather-specific schema/persistence initialization failure is isolated: the core Forge process still starts and exposes weather as unavailable.

## Configuration

Example:

```yaml
weather:
  enabled: true
  endpoint: https://api.open-meteo.com/v1/forecast
  request_timeout_s: 5.0
  check_interval_s: 60.0
  max_forecast_age_s: 1800.0
  movement_refresh_km: 10.0
  refresh_on_start: true
```

No provider credential is stored in Forge YAML for the initial Open-Meteo integration.

## Production acceptance

Checkpoint #162 production acceptance must use the existing Forge process and listener. Do not launch a second process against the production SQLite database.

Acceptance requires:

1. exact accepted commit running under `rollingthunder`
2. only the existing production listener `192.168.9.170:8766`
3. existing `/api/v1/health`, `/api/v1/spots`, and mobile-location behavior remain healthy
4. the already retained mobile location drives a real Open-Meteo refresh
5. `GET /api/v1/weather` returns a positive revision and complete current/hourly/solar snapshot
6. response uses Rolling Thunder-owned condition/icon tokens rather than raw provider codes
7. source attribution metadata is present
8. weather state survives Forge restart from the same SQLite database
9. `PRAGMA integrity_check` remains `ok`
10. no new daemon, port, database file, Pi authority, or radio authority is introduced

A side-by-side pre-production smoke test must use a copied SQLite database and a separate temporary listener.

## Scope and safety boundary

Checkpoint #162 does not add radar, Pi weather state/UI, map rendering, repeater data, or CAT behavior. Those remain later checkpoints.

Forge weather has no radio authority. It cannot tune, change mode, key PTT/MOX, control a tuner, change power, or initiate transmission. The Pi's local database and local core functions remain independent of Forge weather availability.
