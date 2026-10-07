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
  # Optional preferred style-aware worldwide source for the callsign mini-map.
  callsign_tile_url_template: http://forge:8766/api/v1/map/tiles/{style}/{z}/{x}/{y}.png
  zoom: 15
  request_timeout_s: 4.0
  gps_stale_after_s: 10.0
  cache_directory: data/map-tiles
  cache_retention_days: 7
  maximum_cached_tiles: 2048
  installed_packages:
    # Production uses regional DAY and NIGHT packages on the RT_DATA SSD.
    - /mnt/rolling-thunder-data/maps/packages/day/oh-day-z6-z17.mbtiles
    - /mnt/rolling-thunder-data/maps/packages/night/oh-night-z6-z17.mbtiles
    # Additional installed packages cover IN, KY, MI, PA, and WV.
  style: night
  online_attribution: © OpenStreetMap contributors
```

The cache directory is resolved relative to the active YAML file unless an
absolute path is supplied.

For provider-rendered callsign mini-map DAY/NIGHT pixels, the Pi may set
`map.callsign_tile_url_template` to
`http://forge:8766/api/v1/map/tiles/{style}/{z}/{x}/{y}.png` or the equivalent
trusted RadioLAN address. This is the optional route on the existing Forge
spot/weather/radar listener, not a separate production map service. Forge map
serving remains disabled by default and is not automatically enabled by the Pi
setting. That route is suitable for this worldwide mini-map only when its backing
renderer contains worldwide data. The existing I-71 corridor TileServer/Protomaps
dataset is regional and must not be configured as the callsign-map dependency.

### Automatic DAY/NIGHT selection

When the live map is enabled, Rolling Thunder uses the existing GPS snapshots to
choose the map style from the apparent local sunrise/sunset at the current
latitude/longitude. The configured `map.style` remains only the safe startup
fallback until a current GPS fix is available.

The policy:

- performs no network lookup for sunrise/sunset;
- schedules only the next solar transition rather than polling the clock;
- re-evaluates when normal GPS updates show approximately 25 miles of movement;
- leaves the configured style unchanged when GPS is unavailable at startup;
- uses the existing `LiveMapService.set_style()` boundary, so tile/package
  source priority is unchanged.

For fully offline automatic switching, configure installed DAY and NIGHT
packages that cover the operating area. If the requested style is not available
from the installed package set, the existing map-style boundary rejects the
switch rather than weakening installed-package authority.

Settings Context Button #2 remains an immediate manual DAY/NIGHT override. Both
automatic and manual changes use one shared style target: the primary live map
is authoritative, and the callsign mini-map mirrors every accepted style. Zoom
commands still affect only the primary map. A manual choice is retained through
intermediate GPS movement and automatic mode resumes at the next real sunrise
or sunset.

`cache_retention_days` cannot be less than seven days. The URL template must be
an absolute HTTP or HTTPS URL containing `{z}`, `{x}`, and `{y}`.

## Runtime Boundaries

`LiveMapController` consumes existing immutable GPS snapshots and retains only
the last valid position needed for truthful stale and last-known presentation.

`LiveMapService` owns one background worker. It calculates the visible viewport,
loads cached tiles, retrieves missing visible tiles, and publishes immutable
snapshots. Identical loaded viewport requests are no-ops.

`LiveMapInfoController` is a pure presentation projection. It consumes the
already-published GPS/map state, retains only the timestamp of the last usable
map publication, and produces immutable local-time, UTC, grid, temperature,
MAP-health, and GPS-health state. It performs no network, disk, serial, CAT, or
SQLite work.

`MapTileClient` and `MapTileCache` perform all HTTP and disk work. Tkinter only
renders immutable state and never contacts the provider or cache directly.

The callsign mini-map remains worldwide and online-only, with no installed
regional packages. Its cache is isolated under `callsign-info` and partitions
tile paths by `day` and `night`, while the primary map retains its existing
cache layout. A configured callsign tile URL containing `{style}` can use the
existing private Forge map route for provider-rendered DAY/NIGHT tiles and is
preferred when it has worldwide coverage. When
`map.callsign_tile_url_template` is omitted and the inherited worldwide online
source has no `{style}` token, DAY bytes remain unchanged and the callsign-only
client deterministically creates a validated dark PNG for NIGHT. Only the dark
result enters the `night/` cache partition; raw DAY bytes are never relabeled or
stored there. An explicitly configured non-style-aware callsign source remains
fail-closed for NIGHT. None of this changes the primary live-map source path.

The optional radar service is separately lifecycle-owned. The current visible
map viewport is a moving window into a larger immutable radar coverage buffer;
radar network and PNG processing remain outside Tkinter. See
`docs/WEATHER_RADAR.md` for the complete buffering and freshness contract.

## Operator Presentation

The live-map overlay is split into two independent areas rather than using one
combined GPS/map status color.

The glance-readable information box at the upper left shows:

- local system time
- UTC
- current/last-known Maidenhead grid when available
- retained weather temperature in Fahrenheit and Celsius, or explicit
  unavailable placeholders

The information text is intentionally large for in-vehicle use. Its box is sized
to keep all four lines visible, while the independent MAP/GPS/RADAR health box
remains aligned to the upper right with a protected horizontal gap so the two
overlays do not overlap at the installed dashboard geometry.

The separate MAP/GPS health box is a fixed-width panel aligned to the upper
right so the status presentation does not consume most of the top of the map.
It uses typed state and timestamps rather than parsing rendered status strings:

- **light blue** — the subsystem is usable now
- **yellow** — degraded, or a previously usable subsystem has been unavailable
  for less than 30 seconds
- **gray** — unavailable for 30 seconds or more, disabled, or never usable since
  application start

A complete map supplied from stale runtime cache is still considered usable for
MAP health because Rolling Thunder is local-first. `MAP OFFLINE CACHE` therefore
remains light blue. Partial map data and map loading with already-visible tiles
are yellow.

For MAP health, a fresh `LiveMapSnapshot.updated_at` on an unavailable/error
publication does not reset health. `LiveMapInfoController` retains the timestamp
of the last publication that actually contained usable map data. This prevents a
stream of fresh failure snapshots from being mistaken for a healthy map.

For GPS health, `LiveMapPresentation.fix_time` is the last usable fix timestamp.
A stale or last-known fix remains yellow for less than 30 seconds, then becomes
gray. GPS startup with no valid fix yet is gray rather than falsely healthy.

A fresh GPS fix still displays and centers the current position. An old connected
fix is marked stale and is not described as current.

The installed serial adapter combines GGA position data with RMC
course-over-ground and speed. The prominent top-down vehicle marker rotates to
the latest reliable course while moving at least 0.9 metres per second
(approximately 2 mph). Below that threshold it retains the last reliable
heading to avoid stoplight jitter. Before the first reliable movement reading,
the marker points north.

Loss after a prior valid fix retains the map and marker but displays last-known
state through the typed GPS presentation.

Without any valid fix since startup, the map requests no tiles and waits for a
GPS fix.

Map degradation remains independent from GPS:

- fresh cache or successful network retrieval: `MAP READY`
- expired cached tiles after network failure: `MAP DATA OFFLINE — USING CACHE`
- mixed available and missing tiles: `MAP DATA PARTIAL`
- no visible tiles available: `MAP DATA UNAVAILABLE`

The marker remains visible over the neutral reference grid when base-map data is
unavailable.

## POTA Park Marker Layer

Rolling Thunder uses the offline POTA catalog's approximate coordinates as a
lightweight situational-awareness overlay. It does not load or render park
boundary polygons.

POTA catalog SQLite queries run on a dedicated background worker and are limited
to the current visible map viewport. Tkinter receives only immutable marker
snapshots.

Presentation rules:

- zoom 14 and above: yellow, black-outlined rectangles with the POTA reference on
  line one and the full park name on line two
- below zoom 14: 24-pixel yellow dots with black outlines and no text
- overlapping high-zoom labels are suppressed rather than truncated
- a 60-second last-valid-GPS grace period keeps markers stable through brief GPS
  dropouts
- stationary operation does not clear parks while valid GPS fixes continue
- after the grace period expires, park markers clear until a valid fix returns
- an empty marker viewport is a normal state and must not interrupt the Tk refresh
  loop
- radar may be disabled or empty without creating an invalid canvas-layer
  dependency

The layer order is base map -> POTA markers -> radar -> vehicle/status overlays
when all layers exist. Missing optional layers are skipped safely.

POTA catalog coordinates are approximate pins only. They are not navigation
destinations, property boundaries, or activation-boundary evidence. The former
PAD-US/polygon plan is intentionally not part of the current roadmap.

## Radar Layer Motion

When radar is enabled, the visual stacking order is:

```text
BASE MAP
    -> RADAR
    -> VEHICLE / STATUS OVERLAYS
```

The base map and radar have separate spatial lifecycles. Base-map viewport
movement continues to use the existing local-first tile resolver and generation
logic. Radar normally keeps six tiles of extra coverage on every side of the
visible map and begins background recentering when the minimum reserve reaches
three tiles.

While the map moves inside the current radar coverage, the radar service
publishes a new immutable visible crop using already-prepared FRONT-buffer PNG
bytes. Crossing an ordinary map tile boundary therefore does not itself cause a
radar manifest or radar-tile request.

Tkinter retains same-frame radar canvas image objects when their image bytes are
unchanged. If only placement changed, the canvas item is moved rather than
removed, decoded, and recreated. A complete new weather frame is redrawn only
when the BACK coverage buffer becomes the new FRONT buffer.

A radar buffer belongs to exactly one zoom. On a zoom change, incompatible
old-zoom radar is removed instead of being stretched or shifted while the
correct new-zoom coverage loads in the background.

Radar failure never changes base-map source priority or blocks the base map. A
still-eligible FRONT radar buffer may remain visible while a replacement fails,
but only while it truthfully contains the current visible viewport. No old radar
is stretched beyond its geographic coverage.

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

## Installed Offline Packages

The production mobile deployment uses regional DAY and NIGHT MBTiles stored on
the external `RT_DATA` SSD mounted at:

```text
/mnt/rolling-thunder-data/maps/packages
```

Current regional coverage includes Ohio, Indiana, Kentucky, Michigan,
Pennsylvania, and West Virginia. Each state has both DAY and NIGHT packages with
zoom range 6–17. These packages are runtime data and are not committed to Git.

The earlier approximately 206 MB I-71 corridor NIGHT package remains a useful
small fallback artifact, but it is no longer the primary production map source.

Installed packages must contain PNG raster tiles stored with TMS tile rows and
must provide valid bounds, minimum and maximum zoom, attribution, and version
metadata. When `scheme` is present, it must be `tms`.

An installed package is authoritative inside its declared bounds and zoom
range. A missing or invalid tile inside that coverage does not authorize an
online request. Outside installed coverage, cache and online fallback remain
available.

Rolling Thunder startup/deployment should treat the external SSD mount as a
dependency before relying on the regional package paths.

## Safety and Failure Isolation

The live map does not:

- issue CAT commands
- change band, frequency, or mode
- provide PTT, MOX, keying, tuner, or power control
- access the Standard Com Port
- require the Home Station Platform
- alter physical-control authority
- replace or suppress the global ATAS-120 warning

Tile, cache, provider, radar, or health-presentation failure must not stop GPS
polling, contact logging, POTA/DX operation, DMR, repeaters, physical controls,
or radio state polling.

## Manual Acceptance on anvilmobile

1. Confirm the active configuration uses zoom 15, style `night`, and the
   installed I-71 corridor package path.
2. Start the full-screen dashboard with GPS and normal network access.
3. Confirm the upper-left information box shows correct local time, UTC,
   Maidenhead grid, and temperature, with all four lines fully visible.
4. Confirm the MAP/GPS/RADAR health panel remains aligned to the upper right and
   does not overlap the information box.
5. Confirm MAP and GPS health are independent and both light blue with a current
   fix and complete usable map.
6. With radar enabled, confirm ordinary GPS movement and base-map tile-boundary
   crossings do not create a blank/flashing radar interval.
7. Confirm roughly one to two map tiles of travel keep radar continuously
   aligned without a visible reload.
8. Confirm travel to the radar spatial threshold begins a background replacement
   while the old complete radar remains visible, followed by a seamless buffer
   swap.
9. Confirm GPS/vehicle-marker motion and the base map remain responsive while
   radar BACK work is active.
10. Change map zoom at least once and confirm radar never appears shifted or at
    the wrong scale.
11. Temporarily make Forge/radar unavailable and confirm eligible existing radar
    is retained only while geographically valid, while base map/GPS/unrelated
    contexts continue working.
12. Restore Forge/radar and confirm recovery occurs without restarting the
    dashboard.
13. Disable public-internet access while remaining inside installed package
    coverage and confirm MAP remains light blue while local tiles continue
    working.
14. Move to a previously unseen viewport inside installed coverage and confirm the
    map remains available without online base-map tile requests.
15. Confirm the marker follows course while moving and retains its heading when
    stopped.
16. Confirm POTA/DX cards, DMR/repeater contexts, the global ticker, and ATAS-120
    warnings still work.
17. Disconnect GPS after a current fix and confirm GPS health becomes yellow
    during the recent-loss window and gray after 30 seconds while the marker
    remains last-known rather than current.
18. Force or observe a map-unavailable condition after a usable map and confirm
    MAP health becomes yellow for less than 30 seconds and gray at 30 seconds,
    even though unavailable snapshots continue updating.
19. Confirm logging, POTA/DX selection, physical controls, and radio polling
    remain usable throughout map/GPS/radar/network degradation.
20. Open a callsign-information mini-map in DAY and NIGHT modes and confirm its
    base map follows the primary-map style without showing a bright DAY rectangle
    at night. With no dedicated callsign source configured, confirm the worldwide
    online fallback remains available and is visibly dark in NIGHT. With an
    explicit style-aware source, confirm its real NIGHT endpoint remains preferred.

Record the visible results in the draft pull request before approval.


## POTA catalog markers

When `pota_map.enabled` is true, the dashboard reads the separate offline POTA
catalog through a dedicated single-worker service. SQLite viewport queries never run
on the Tkinter thread. Marker snapshots are accepted for rendering only when their
viewport exactly matches the currently published base-map viewport, preventing stale
markers from being painted after movement or zoom changes.

Layer order is:

1. base raster map
2. POTA catalog markers
3. weather radar
4. vehicle and status overlays

At zoom 14 and higher, a park is a yellow rectangle with a black outline and centered
black text: POTA reference on line one and full park name on line two. The rectangle
uses Tk's rendered text bounds so the name is not truncated. Overlapping labels are
suppressed. Below zoom 14, parks are yellow dots with black outlines and no text.

The POTA coordinate is an approximate catalog pin only. It is not a park boundary,
navigation destination, or activation-area determination.
