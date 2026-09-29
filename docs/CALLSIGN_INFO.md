# Callsign Information Overlay

## Purpose

The callsign-information overlay answers four operator questions without replacing the active operating page:

1. Who is this station?
2. Where are they operating?
3. What is the current weather there?
4. Have I worked them before?

The overlay is optional, appears over the lower-right portion of the live map only after a complete useful lookup has loaded, and never participates in durable contact Commit.

## Architecture

### Forge

Callsign intelligence runs as an independent Forge process:

```text
pending callsign
      |
      v
anvilmobile background client
      |
      v
rolling-thunder-forge-callsign-info
      |
      +--> QRZ XML
      +--> Wavelog v2 latest-QSO lookup
      +--> Open-Meteo current weather
      +--> bounded caches
```

This keeps the retained Forge spot API free of live provider work and keeps QRZ/Wavelog credentials on Forge.

The endpoint is:

```text
GET /api/v1/contact-intelligence/{callsign}
```

For a known current POTA activation the Pi adds:

```text
?latitude=<park-lat>&longitude=<park-lon>&source=pota
```

The POTA coordinate override affects target weather and map presentation. QRZ identity/QTH data remains the contacted operator profile.

### Pi

The Pi owns:

- pending-callsign observation
- one background lookup per pending callsign
- generation-based stale-response rejection
- the 120-second maximum overlay lifetime
- the operator ON/OFF preference
- POTA-current-location priority
- overlay and mini-map presentation

The Pi does not receive QRZ or Wavelog credentials.

## Location priority

For the current contact:

1. If the pending callsign came from a selected POTA spot with park coordinates, use the park coordinate for the overlay pin and weather.
2. Otherwise use QRZ latitude/longitude when available.
3. QRZ coordinates whose source is only a state or DXCC center are not used for weather.
4. Missing coordinates never invent a pin.

The profile may still display textual information when no reliable coordinate exists.

## Weather

The QRZ photograph is deliberately not used by this feature.

Instead the overlay shows simple current weather:

- temperature in Fahrenheit
- a compact condition such as SUNNY, CLOUDY, RAIN, SNOW, or THUNDERSTORMS
- small provider attribution required by the existing Open-Meteo integration

Open-Meteo is normalized on Forge. Weather failure is optional enrichment failure and must not suppress otherwise useful callsign/history information.

Target weather is cached for 15 minutes by default.

## Previous contact

Forge requests the newest exact-callsign QSO from Wavelog v2.

When no prior QSO exists the overlay displays:

```text
FIRST CONTACT
```

rather than rendering an empty prior-contact section.

When a prior QSO exists the compact response may include:

- previous date/time
- station-location name
- comment or notes
- mobile indication when reliably inferred from station-location identity
- contacted POTA reference
- operator's prior POTA reference when Wavelog returns `my_pota_ref`

No giant raw Wavelog record is returned to the Pi.

## Cache policy

Default Forge cache lifetimes:

| Data | TTL |
| --- | ---: |
| Positive QRZ profile | 60 days |
| Negative QRZ result | 24 hours |
| Wavelog last-QSO | 60 seconds |
| Wavelog station profile names | 6 hours |
| Target current weather | 15 minutes |

Mutable Wavelog history is intentionally short-lived.

## Overlay lifecycle and stale responses

Each pending callsign increments a generation.

A response is accepted only if:

- the request generation is still current,
- the callsign still matches,
- the feature is still enabled,
- the service has not stopped.

Commit, discard, callsign replacement, timeout, and feature disable invalidate presentation state. Cancelling the underlying HTTP future is only an optimization; correctness does not depend on cancellation.

A failed or timed-out lookup is not repeatedly retried while the same callsign remains pending.

## Settings

Settings includes:

```text
CALLSIGN INFO
Context Button #3
```

The operator preference is stored in the application SQLite database as:

```text
callsign.info.enabled
```

Turning the setting OFF immediately invalidates/hides an active overlay and prevents new lookups. Turning it back ON allows the next/current pending callsign to initiate a new lookup.

## Offline behavior

If Forge, WireGuard, cellular service, QRZ, Wavelog, or the weather provider is unavailable:

- no modal dialog appears,
- no large error overlay appears,
- radio/map controls continue,
- durable local logging continues,
- provider failure never enters the Commit path.

## Privacy and data-source limitations

The overlay displays only data returned by configured QRZ/Wavelog integrations.

QRZ fields are optional. The UI omits missing values rather than manufacturing data.

QRZ's `born` field is treated as a birth year only. The UI does not calculate an exact age from a year-only value.

Wavelog history depends on the configured token having `qso:read` permission and on the deployed Wavelog v2 endpoint supporting filtered QSO reads.
