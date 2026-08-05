# Live GPS Map

## Purpose

The first Milestone 10 Phase C map slice provides continuous location awareness
in the dashboard's right-side situational area. It is presentation-only and adds
no radio-control or transmit authority.

## Configuration

```yaml
map:
  enabled: true
  tile_url_template: https://tile.openstreetmap.org/{z}/{x}/{y}.png
  zoom: 15
  request_timeout_s: 4.0
  gps_stale_after_s: 10.0
  cache_directory: data/map-tiles
  cache_retention_days: 7
  maximum_cached_tiles: 2048
  installed_packages:
    - ../data/maps/rolling-thunder-i71-corridor-night-z0-z15-v1.mbtiles
  style: night
  online_attribution: © OpenStreetMap contributors
```

The cache directory is resolved relative to the active YAML file unless an
absolute path is supplied.

`cache_retention_days` cannot be less than seven days. The URL template must be
an absolute HTTP or HTTPS URL containing `{z}`, `{x}`, and `{y}`.

## Runtime Boundaries

`LiveMapController` consumes existing immutable GPS snapshots and retains only
the last valid position needed for truthful stale and last-known presentation.

`LiveMapService` owns one background worker. It calculates the visible viewport,
loads cached tiles, retrieves missing visible tiles, and publishes immutable
snapshots. Identical loaded viewport requests are no-ops.

`MapTileClient` and `MapTileCache` perform all HTTP and disk work. Tkinter only
renders immutable state and never contacts the provider or cache directly.

## Operator Presentation

A fresh fix displays GPS readiness, map readiness, Maidenhead grid, and current
coordinates. An old connected fix is marked stale and is not described as
current.

The installed serial adapter combines GGA position data with RMC
course-over-ground and speed. The prominent top-down vehicle marker rotates to
the latest reliable course while moving at least 0.9 metres per second
(approximately 2 mph). Below that threshold it retains the last reliable
heading to avoid stoplight jitter. Before the first reliable movement reading,
the marker points north.

Loss after a prior valid fix retains the map and marker but displays
`LAST KNOWN POSITION`.

Without any valid fix since startup, the map requests no tiles and displays
`WAITING FOR GPS FIX`.

Map degradation is independent from GPS:

- fresh cache or successful network retrieval: `MAP READY`
- expired cached tiles after network failure: `MAP DATA OFFLINE — USING CACHE`
- mixed available and missing tiles: `MAP DATA PARTIAL`
- no visible tiles available: `MAP DATA UNAVAILABLE`

The marker remains visible over the neutral reference grid when base-map data is
unavailable.

## Provider and Cache Rules

The default OpenStreetMap provider is used only for ordinary on-screen,
human-requested viewing.

Rolling Thunder:

- sends a distinct application user agent
- displays `© OpenStreetMap contributors`
- requests only tiles required by the current visible viewport
- retains tiles for at least seven days
- performs no route prefetching
- performs no regional bulk downloading
- performs no background offline seeding

The ordinary runtime cache is degradation support, not a complete offline map.
Offline regional coverage is supplied through separately generated, licensed
MBTiles packages. Missing tiles inside installed coverage are never filled from
the ordinary online provider.

## Installed Offline Package

The first supported offline package is the dark I-71 corridor map used for the
normal Waynesville-to-Delaware drive.

- package ID: `i71-corridor-night`
- version: `1.0.0`
- style: `night`
- bounds: `-84.18,39.43,-82.82,40.42`
- zoom range: `0–15`
- tile count: `19,880`
- installed size: approximately `206 MB`
- SHA-256: `13ae1cf9c171b005f827710a2cc10034f71d4695ab33b6194e05b0a7c2ddfd41`

Expected installation path:

```text
/home/geoff/projects/rolling-thunder-v4/data/maps/rolling-thunder-i71-corridor-night-z0-z15-v1.mbtiles
```

Installed packages must contain PNG raster tiles stored with TMS tile rows and
must provide valid bounds, minimum and maximum zoom, attribution, and version
metadata. When `scheme` is present, it must be `tms`.

An installed package is authoritative inside its declared bounds and zoom
range. A missing or invalid tile inside that coverage does not authorize an
online request. Outside installed coverage, cache and online fallback remain
available.

Generated MBTiles files are runtime data and must not be committed to Git.

## Safety and Failure Isolation

The live map does not:

- issue CAT commands
- change band, frequency, or mode
- provide PTT, MOX, keying, tuner, or power control
- access the Standard Com Port
- require the Home Station Platform
- alter physical-control authority
- replace or suppress the global ATAS-120 warning

Tile, cache, or provider failure must not stop GPS polling, contact logging,
POTA operation, physical controls, or radio state polling.

## Manual Acceptance on anvilmobile

1. Confirm the active configuration uses zoom 15, style `night`, and the
   installed I-71 corridor package path.
2. Start the full-screen dashboard with GPS and normal network access.
3. Confirm the dark local map, vehicle marker, grid, coordinates, and
   attribution are displayed correctly.
4. Disable public-internet access while remaining inside package coverage.
5. Move to a previously unseen viewport and confirm the map remains available
   without online tile requests.
6. Confirm the marker follows course while moving and retains its heading when
   stopped.
7. Confirm GPS updates do not cause visible flicker or UI stalls.
8. Confirm POTA cards, the global ticker, and ATAS-120 warnings still work.
9. Restore connectivity and confirm online fallback works outside package
   coverage.
10. Disconnect GPS and confirm the marker is labeled last-known rather than
    current.
11. Confirm logging, POTA selection, physical controls, and radio polling remain
    usable throughout map and network degradation.

Record the visible results in the draft pull request before approval.
