# Callsign Information Overlay

## Purpose

The callsign-information overlay answers four operator questions without replacing the active operating page:

1. Who is this station?
2. Where are they operating?
3. What is the current weather there?
4. Have I worked them before?

The overlay is optional, appears promptly over the lower-right portion of the live
map from the locally available callsign and valid FT8 grid, uses deliberately
oversized in-car typography, and never participates in durable contact Commit.
Forge identity, history, and weather replace the local-only pending presentation
asynchronously if they arrive while that target is still relevant. The compact
layout uses a map across the top, a protected-width weather column beside contact
identity details, and a full-width two-line contact-history strip across the
bottom. The weather column keeps a minimum readable width; long
callsign/name/address text wraps on the identity side instead of shrinking
weather. Only the map row expands vertically, preventing unused black space from
opening beneath the contact details.

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

- pending-callsign and current FT8-target observation
- explicit station-selection presentation rearm and durable navigation dismissal
- one background lookup per pending callsign
- generation-based stale-response rejection
- the 120-second maximum overlay lifetime
- the operator ON/OFF preference
- POTA-current-location priority
- overlay and mini-map presentation

The Pi does not receive QRZ or Wavelog credentials.

The contact mini-map deliberately uses a dedicated online tile cache and does not
blend installed regional MBTiles into that viewport. This keeps worldwide contact
maps visually consistent and avoids a viewport straddling the edge of a regional
night-map package showing dark installed tiles beside light online tiles.

The primary live map is the authoritative DAY/NIGHT style target. Solar changes
and the Settings style button fan out each accepted primary-map style to the
mini-map; the mini-map has no separate timer or style control. A style change
invalidates its base-map snapshot so an open or subsequently opened overlay loads
the new pixels.

The dedicated cache stores identical tile coordinates in separate `day/` and
`night/` partitions under `cache_directory/callsign-info`. Its retention,
validation, and maximum-tile policy are unchanged and apply across both
partitions. `map.callsign_tile_url_template` may point at the existing private
Forge route `/api/v1/map/tiles/{style}/{z}/{x}/{y}.png`; when omitted, the main
worldwide online tile URL is reused. If that inherited source has no `{style}`
token, the callsign client leaves DAY responses byte-for-byte unchanged and
deterministically transforms each validated NIGHT response into a validated dark
PNG while preserving alpha and map detail. Only the transformed bytes are stored
under `night/`; the raw response is not cached as NIGHT. An explicit
`callsign_tile_url_template` containing `{style}` remains preferred and uses the
provider's real style endpoint without a local transform. An explicitly configured
callsign source without `{style}` remains fail-closed for NIGHT.

The optional Forge route is a worldwide dependency only when its renderer has
worldwide coverage. The existing I-71 corridor TileServer/Protomaps dataset does
not, so it is not a valid callsign mini-map source.

## Location priority

For the current contact:

1. If the pending callsign came from a selected POTA spot with park coordinates, use the park coordinate for the overlay pin and weather.
2. Otherwise use QRZ latitude/longitude when available.
3. QRZ coordinates whose source is only a state or DXCC center may center a country/region map, but do not receive a station pin or target weather.
4. Grid-center fallback is explicitly labeled approximate.
5. Missing coordinates never invent a pin.

For FT8, a valid grid from the current selected CQ, live preparation, or active
QSO may provide that approximate grid-center presentation before Forge responds.
Terminal QSO state, abort, selection dismissal/expiry, and non-live preparation
status immediately invalidate that FT8 target. A malformed or missing local grid
still permits callsign/status presentation but never creates a location or pin.

The profile may still display textual information when no reliable coordinate exists.

## Weather

The QRZ photograph is deliberately not used by this feature. The contacted
station/target's current local time is rendered in the upper-right of the mini-map
rather than consuming identity-panel space. Black text has a compact white backing
fitted to the rendered label with padding, above the map tiles. No clock or backing
is drawn when the time is unavailable. It is derived with the IANA timezone
returned by the same target-weather response, so daylight-saving transitions remain
correct. When that timezone is unavailable or invalid, the field is blank; the Pi's
operator timezone is never presented as the target's time.

Instead the overlay shows simple current weather:

- temperature in Fahrenheit
- a compact condition such as SUNNY, CLOUDY, RAIN, SNOW, or THUNDERSTORMS
- small provider attribution required by the existing Open-Meteo integration

Open-Meteo is normalized on Forge. Weather failure is optional enrichment failure and must not suppress otherwise useful callsign/history information.

Target weather is cached for 15 minutes by default.

The compact response also carries the provider-neutral normalized observation used
to render that target weather (timestamps, coordinates, condition, temperature,
humidity, and provider identity). The Pi may freeze that already-resolved value into
a contact only while the published callsign and target still match and the observation
is fresh. No Commit-time provider request is made.

The optional `timezone` and `observation` members require Pi-first deployment. New Pi
readers accept older responses without them, but the shared strict response models
reject unknown fields, so an older Pi must not receive the expanded Forge response.

## Previous contact

Forge requests the newest exact-callsign QSO from Wavelog v2 with `limit=1`.
The same response's `meta.total` is the full filtered total, not `meta.count` or the
one-row page length. The deployed Wavelog Qso_resource::index/list_meta contract
was inspected: JSON is newest-first, the exact callsign filter is applied before
counting, and absent band/mode/station filters include all token-visible history.
No second request, unbounded pagination or Tk I/O is added. One 60-second cache
entry contains both latest record and total; its existing invalidation applies.

The heading reads `WORKED 12 TIMES — LAST CONTACT` (singular `TIME` for one).
The detail keeps the last date/time, location/POTA context and `Band: 20m`.
Comments and notes are no longer displayed, but existing log text is untouched.
Missing count/band from an older provider is explicitly unavailable; never infer
one from a one-row response. Contradictory/invalid totals fail as unavailable
lookup rather than falsely reporting FIRST CONTACT.

When no prior QSO exists the overlay displays:

```text
FIRST CONTACT
```

rather than rendering an empty prior-contact section.

When a prior QSO exists the compact response may include:

- previous date/time, flattened with the station-location name onto one summary line
- station-location name
- total exact-callsign logged QSOs across all token-visible stations, bands and modes
- the last QSO band (not the currently selected radio band)
- mobile indication when reliably inferred from station-location identity
- contacted POTA reference
- operator's prior POTA reference when Wavelog returns `my_pota_ref`

No giant raw Wavelog record is returned to the Pi. Optional strict `worked_count`
and `band` fields extend the existing last_qso model. Upgrade Pi readers before
callsign-info, because older strict clients reject the expanded response. New Pi
readers accept older responses with unknown count/band. Rollback callsign-info
before rolling back Pi. Contact-sync can be upgraded first independently. No
schema migration or historical QSO update is needed. See
`engineering/issue-246-notes-and-contact-history.md`.

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

Each explicitly armed, observed relevant callsign increments a generation.

A response is accepted only if:

- the request generation is still current,
- the callsign still matches,
- the feature is still enabled,
- the service has not stopped.

Commit, discard, callsign replacement, FT8 terminal/abort/dismissal transitions,
timeout, and feature disable invalidate presentation state. Cancelling the
underlying HTTP future is only an optimization; correctness does not depend on
cancellation. Only `PREPARING` FT8 start status is a live pre-QSO target; stale
`STARTED`, `FAILED`, or restored status cannot resurrect an overlay.

For the POTA, DX, and FT8 station browsers, an encoder/keyboard browse command
dismisses the overlay even when a one-row/edge/active state cannot move the
highlight, and suppresses further popup observation. The
suppression survives timer refresh, a newly highlighted callsign, retained FT8
active-target state, and late lookup completion. An accepted band change and
leaving one of those station contexts apply the same dismissal. Periodic refresh
does not start a lookup or request/render the contact mini-map while suppression
is active.

An accepted explicit station activation rearms the lifecycle before the next
refresh, including selection of the same callsign after dismissal, lookup failure,
or the one-shot timeout. Rearm does not authorize or perform tuning or transmit:
the existing POTA/DX receive-tuning and FT8 one-QSO command must first accept the
operator action. Rejected/blocked commands do not rearm or execute a fallback
selection. Browse voice/manual pending-callsign behavior outside these station
browsers is unchanged.

A failed or timed-out lookup is not repeatedly retried while the same callsign remains pending.

## Settings

Settings includes:

```text
CALLSIGN INFO
Button #2 OFF / Button #3 ON when selected
```

The operator preference is stored in the application SQLite database as:

```text
callsign.info.enabled
```

Turning the setting OFF immediately invalidates/hides an active overlay and prevents new lookups. Turning it back ON allows the next/current pending callsign to initiate a new lookup.

## Offline behavior

If Forge, WireGuard, cellular service, QRZ, Wavelog, or the weather provider is unavailable:

- no modal dialog appears,
- the optional overlay retains locally known callsign/grid context,
- a large high-contrast status says `NETWORK UNAVAILABLE` only when the already-
  published network state proves the network is down,
- it says `FORGE SERVICE NOT RESPONDING` only when that state proves the network
  is available and the Forge request failed,
- all other lookup failures say `LOCATION SERVICE UNAVAILABLE`,
- radio/map controls continue,
- durable local logging continues,
- provider failure never enters the Commit path.

Failure classification performs no additional connectivity probe and never shows
raw exception text. The HTTP request remains bounded and runs only on the existing
background lookup executor.

## Privacy and data-source limitations

The overlay displays only data returned by configured QRZ/Wavelog integrations.

QRZ fields are optional. The UI omits missing values rather than manufacturing data.

QRZ's `born` field is treated as a birth year only. The UI does not calculate an exact age from a year-only value.

Wavelog history depends on the configured token having `qso:read` permission and on the deployed Wavelog v2 endpoint supporting filtered QSO reads.


## Known/friend callsigns

The same Forge service optionally serves `/admin/known-callsigns` and
`/api/v1/known-callsigns`. The Pi uses independent background snapshot polling
for gold friend stars, including this overlay. Directory comments never enter
contact-intelligence responses. See `KNOWN_CALLSIGNS.md` for configuration,
private-network administration, cache failure behavior, and owner acceptance.
