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
  zoom: 17
  request_timeout_s: 4.0
  gps_stale_after_s: 10.0
  cache_directory: data/map-tiles
  cache_retention_days: 7
  maximum_cached_tiles: 2048
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

The ordinary cache is degradation support, not a complete offline map. A future
packaged offline implementation must use a source and format that explicitly
permit that use.

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

1. Enable the `map` section in the active local YAML.
2. Start the full-screen dashboard with the installed GPS and normal network.
3. Confirm the right side displays local map tiles rather than the placeholder.
4. Confirm the vehicle marker is centered and the displayed grid and coordinates
   agree with the dashboard GPS state.
5. Drive above approximately 2 mph and confirm the vehicle marker follows the
   course of travel, then retains its last reliable heading when stopped.
7. Leave the dashboard running long enough to confirm ordinary GPS updates do not
   cause visible flicker or UI stalls.
6. Open a POTA detail overlay and confirm it appears above the persistent map.
8. Confirm the global ticker still spans both columns.
9. Confirm a retained ATAS-120 warning still overrides routine ticker text.
10. Remove public-internet access after tiles have been cached and confirm cached
   map data remains visible with an offline/cache status.
11. Restore connectivity and confirm normal map state recovers.
12. Stop or disconnect GPS and confirm the marker is explicitly labeled
    last-known rather than current.
13. Confirm logging, POTA selection, controls, and radio polling remain usable
    throughout map and network degradation.

Record the visible results in the draft pull request before approval.
