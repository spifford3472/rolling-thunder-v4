# Rolling Thunder Weather Radar

Rolling Thunder provides an optional latest-frame weather-radar overlay on the live map. Radar is situational awareness only. It has no radio, CAT, PTT, tuning, logging, or transmit authority.

## Architecture

Radar follows the same safety boundary as the rest of Rolling Thunder:

1. NOAA/NWS is contacted only by Forge.
2. Forge discovers the newest MRMS frame and normalizes provider metadata into Rolling Thunder-owned radar models.
3. The Pi contacts only Forge.
4. Large radar coverage is acquired in bounded batches rather than hundreds of individual public-provider requests.
5. The Pi radar worker performs manifest/coverage I/O and fixed-opacity PNG processing outside Tkinter.
6. Tkinter consumes immutable overlay snapshots and draws already-prepared PNGs between the base map and the vehicle/status overlays.

The existing base-map resolver is unchanged:

`installed MBTiles -> runtime cache -> online tiles`

Radar is a separate optional overlay and never becomes a base-map source.

## Visible viewport and radar coverage viewport

The visible map viewport and radar coverage are intentionally different concepts.

- **Visible map viewport** — the map rectangle currently on screen.
- **Radar coverage viewport** — a larger immutable Web Mercator tile rectangle retained around the visible map.

The Pi normally renders the visible map as a moving crop/window into the current radar coverage buffer. Ordinary GPS movement therefore does not require a radar manifest or provider request merely because the visible map crossed a tile boundary.

The default coverage policy adds **six whole radar tiles on every side** of the visible viewport. If the visible tile rectangle is `W x H`, retained coverage is approximately:

`(W + 12) x (H + 12)`

Coverage is centered on the visible viewport when a generation is requested. Containment and remaining reserve use pure tile-coordinate geometry, including wrapped longitude handling. The policy is independent of Tkinter.

## Spatial recenter threshold

With six tiles of reserve on each side, a replacement radar coverage generation begins when the minimum remaining reserve reaches **three tiles**.

Consequences:

- one tile of ordinary movement remains inside the FRONT buffer with no radar HTTP work;
- two tiles of movement remain inside the safe region with no radar reload;
- about three tiles of movement remain geographically covered while background recentering begins;
- the old coverage remains the displayed FRONT buffer while its replacement is built.

The system does not wait until the visible screen reaches the outside edge of retained coverage.

## FRONT/BACK buffering on the Pi

`LiveRadarOverlayService` owns a double-buffered publication model.

### FRONT buffer

FRONT is one complete immutable exact-frame radar coverage area. It remains published while geographically valid and under the radar hide-age cutoff.

Movement within FRONT creates a new immutable visible crop from already-prepared FRONT PNG bytes and current map placements. No network, disk, manifest, opacity processing, or image decoding is required merely to reframe those pixels.

### BACK buffer

A BACK generation is prepared by the radar background worker. It may retrieve a manifest, obtain missing radar coverage from Forge, validate PNGs, apply fixed opacity, and assemble a complete immutable coverage buffer.

BACK data is never progressively displayed. Partial BACK data cannot replace a complete FRONT buffer.

When BACK is complete, exact-frame valid, still relevant to the newest desired map position, and usefully centered, it atomically becomes FRONT. Obsolete generations cannot publish over newer intent.

Important Pi diagnostics include:

- `RADAR FRONT REFRAME`
- `RADAR BACK LOAD START`
- `RADAR BACK LOAD SUPERSEDED`
- `RADAR BUFFER SWAP`
- `RADAR REFRESH BY AGE`
- `RADAR REFRESH BY SPATIAL THRESHOLD`
- `RADAR PI COVERAGE READY`

## Bulk acquisition path

The original radar implementation requested one 256x256 tile from Forge for each tile in a coverage generation. On a cold Forge cache, each Pi tile request could cause a separate NOAA ArcGIS `exportImage` request. A six-tile overscan can contain roughly 225-324 tiles, so this created hundreds of sequential request opportunities and made a complete BACK generation unnecessarily fragile.

The current acquisition path instead batches radar work:

```text
Pi BACK generation
    -> bounded Forge coverage request
    -> one large exact-frame NOAA export for the requested block
    -> Forge slices that image locally into 256x256 Web Mercator tiles
    -> one ZIP response returns the complete block to the Pi
    -> Pi validates/caches the raw tiles
    -> LiveRadarOverlayService applies opacity and builds BACK
    -> atomic FRONT swap
```

The Pi client prefetches up to **20 tile columns x 16 tile rows** at a time. At 256 pixels per tile this is at most 5120x4096 pixels, remaining below the NOAA service's published large-image limits used by this integration. A typical 15- or 16-tile-high radar buffer therefore needs one coverage transfer for a cold frame; a 17- or 18-tile-high buffer normally needs two. World-edge/wrapped geometry may require an additional bounded block.

Forge accepts a bounded coverage rectangle of at most 32 columns x 16 rows and the NOAA provider internally keeps each export below its provider image limits. No unbounded regional radar download is performed.

The legacy single-tile Forge endpoint remains available for compatibility and diagnostics, but normal Pi coverage construction uses the bulk-prefetch path.

## Exact-frame handoff and frame rollover

Every published radar coverage buffer is frame-atomic. NOAA exports are locked with the exact provider raster ID represented by the opaque Rolling Thunder frame token. Tiles from different observation times are never intentionally mixed in one published buffer.

A prior implementation retained only the newest Forge frame token. If NOAA advanced from frame A to frame B while the Pi was still loading A, later A tile requests could be rejected even though the in-flight BACK generation was internally consistent.

Forge now retains the **current frame plus one prior frame generation** for a bounded handoff window. A request already using the immediately preceding frame can finish while it remains under the normal radar render-age cutoff. New manifests still advertise only the latest frame.

This creates the intended handoff:

```text
A is current and usable
    -> Forge discovers B
    -> B becomes current
    -> A remains temporarily retrievable for in-flight work
    -> Pi completes or safely supersedes its generation
    -> later frame retention naturally retires A
```

A complete older FRONT remains preferable to a partial newer BACK.

Forge diagnostics include:

- `RADAR NOAA DISCOVERY`
- `RADAR NOAA COVERAGE`
- `RADAR FORGE COVERAGE READY`
- `RADAR FORGE COVERAGE CACHE`
- `RADAR FRAME HANDOFF`

The NOAA, Forge, and Pi coverage diagnostics include elapsed milliseconds so installed testing can distinguish provider delay from Forge preparation and Pi transfer/processing delay.

## Same-frame overlap reuse

Spatial recentering does not blindly rebuild everything already present in FRONT. When the cached manifest still identifies the same exact radar frame, the BACK builder reuses overlapping prepared FRONT PNG bytes and only requests newly exposed keys.

The Pi raw coverage cache also retains a bounded set of raw same-frame tiles. A service-level request for a newly exposed tile can therefore be satisfied from the prior bulk coverage transfer without another Pi-to-Forge request.

A new meteorological frame cannot reuse old-frame radar pixels. A new exact frame is fully prepared before publication.

## Generation, supersession, and coalescing

Radar work remains bounded to:

- one published FRONT buffer;
- one active BACK generation;
- at most one newest desired replacement target.

Intermediate movement is coalesced rather than queued. If the vehicle moves while BACK is loading, only the newest target that the active BACK cannot adequately cover is retained. Obsolete generations stop requesting additional service-level tiles as soon as practical and never overwrite newer desired state.

## Spatial and meteorological refresh are independent

Radar may refresh for two independent reasons.

### Spatial refresh

The visible viewport consumes enough reserve to cross the three-tile recenter threshold. If the cached manifest is still within its allowed check interval, spatial recentering uses that exact frame and does not force a manifest request simply because the map moved.

### Meteorological refresh

The manifest-refresh interval expires, meaning a newer NOAA observation may be available. This can occur without vehicle movement. FRONT remains visible while the candidate frame is prepared.

Reframing never changes provider observation time. Radar age always derives from the provider observation timestamp.

## Timeouts and bounded caches

Ordinary Forge metadata/API traffic keeps its existing short configured timeout, normally 5 seconds.

Large radar coverage has a separate bounded timeout because a legitimate 4K-class exact-frame image can take longer than an ordinary JSON request:

- Pi -> Forge radar coverage: at least 30 seconds by default;
- Forge -> NOAA radar coverage export: at least 20 seconds by default.

These longer bounds apply only to radar coverage work running outside Tkinter. They do not extend normal weather, spot, health, or other Forge request timeouts.

Pi raw radar prefetch is bounded by both:

- 640 tiles;
- 64,000,000 encoded PNG bytes.

The coverage response is also bounded to 96,000,000 bytes. Forge's existing radar tile cache remains bounded at 256 tiles. No radar history is accumulated.

## Freshness policy

Freshness is based on provider observation time, not when Forge or the Pi downloaded, cached, or reframed the data.

- up to 15 minutes old: normal display;
- more than 15 minutes old: display may continue but radar is marked stale;
- more than 30 minutes old: radar is not rendered.

Provider or Forge failures do not erase a still-eligible complete FRONT buffer. When an attempted update fails, the Pi retains FRONT while it still truthfully covers the visible map and remains under the hide cutoff.

If the vehicle moves outside retained geographic coverage while replacement radar remains unavailable, the Pi does not stretch or misregister old radar. The overlay is removed for that viewport while the base map and unrelated functions continue.

## Zoom behavior

Radar coverage belongs to one Web Mercator zoom level. FRONT at zoom `Z` is never treated as radar data for `Z+1` or `Z-1`.

On a map zoom change:

1. old-zoom radar is considered geographically incompatible;
2. it is not stretched or shifted into the new zoom;
3. a new enlarged coverage buffer is prepared in the background;
4. new-zoom radar appears only after a complete exact-frame BACK is ready.

The base map remains responsive throughout.

## Rendering behavior

The visual layer order remains:

`BASE MAP -> RADAR -> VEHICLE / STATUS OVERLAYS`

Tkinter receives only the current immutable visible radar crop. It does not hold Tk `PhotoImage` objects for every off-screen tile in the larger coverage.

For same-frame movement, the renderer plans radar canvas work as remove/redraw/move. Unchanged visible radar canvas image objects are retained and repositioned when only screen coordinates change. A weather-frame swap redraws the visible radar tiles for the new frame atomically.

Tkinter performs no HTTP, filesystem, SQLite, opacity processing, NOAA access, ZIP parsing, or other expensive radar work.

## Resource bounds

Radar tiles are 256x256 pixels. One decoded RGBA tile is 262,144 bytes (256 KiB). The retained Pi coverage stores already-prepared PNG bytes rather than decoding the entire off-screen area into Tk images.

Representative six-tile-margin coverage sizes are:

| Visible tile rectangle | Coverage | Tiles | Raw RGBA equivalent per complete buffer |
| --- | --- | ---: | ---: |
| 3 x 3 | 15 x 15 | 225 | 56.25 MiB |
| 4 x 4 | 16 x 16 | 256 | 64 MiB |
| 5 x 5 | 17 x 17 | 289 | 72.25 MiB |
| 6 x 6 | 18 x 18 | 324 | 81 MiB |

Those figures are conservative decoded equivalents, not expected encoded PNG sizes. Tk's radar `PhotoImage` cache remains bounded at 128 entries, roughly 32 MiB raw-RGBA equivalent. The independent raw bulk-prefetch cache is bounded by encoded bytes as described above.

Normally the Pi retains one complete FRONT plus one BACK under construction and bounded caches/presentation objects.

## Provider and product

The provider remains the NOAA/NWS time-enabled MRMS base-reflectivity ImageServer. Provider-specific ArcGIS fields, raster IDs, mosaic rules, export geometry, and URLs remain Forge-side.

Rolling Thunder publishes the provider-neutral product token:

`base_reflectivity`

Each accepted frame contains:

- an opaque Rolling Thunder frame token;
- provider observation time;
- Forge fetch time;
- provider/product identity;
- required attribution metadata.

The Pi never receives the NOAA raster/object identifier.

## Display policy

Rolling Thunder intentionally supports only the latest useful frame.

- fixed opacity: 55%;
- no animation;
- no timeline controls;
- no route prediction;
- no automatic intensity/opacity policy;
- no regional/offline radar seeding.

NOAA/NWS attribution and radar observation time remain separate from base-map attribution.

The map health box labels the subsystem `RADAR`. Color carries compact state:

- light blue: radar image ready/healthy;
- yellow: waiting, background loading, stale, or degraded;
- gray: radar image disabled/not configured;
- red: radar image unavailable/error.

## Operator Settings control

When radar is configured, Settings exposes a selected `RADAR Image` row. Button #2
requests OFF and Button #3 requests ON.

Turning radar image off immediately clears the visible overlay and suppresses new Pi radar image work, without disabling Forge radar or changing base map, GPS, logging, controls, or radio authority. Turning it back on returns the Pi worker to idle; the next normal map refresh requests coverage around the current viewport.

The operator choice is persisted asynchronously in the existing `operator_preferences` SQLite table under `radar.image.enabled`.

## Forge configuration

Radar remains opt-in:

```yaml
radar:
  enabled: true
  endpoint: https://mapservices.weather.noaa.gov/eventdriven/rest/services/radar/radar_base_reflectivity_time/ImageServer
  request_timeout_s: 5.0
  check_interval_s: 60.0
  stale_after_s: 900.0
  hide_after_s: 1800.0
  maximum_cached_tiles: 256
  refresh_on_start: true
```

`request_timeout_s` remains the ordinary provider request timeout. Large coverage exports automatically use a separate bounded minimum timeout and do not require a new production YAML setting.

Forge uses the latest retained mobile location for frame discovery. Missing location, NOAA failure, malformed metadata, invalid PNG data, or coverage retrieval failure affects radar health only.

## Pi configuration

The Pi overlay capability is independently opt-in and requires map and Forge:

```yaml
forge:
  enabled: true
  api_url: http://192.168.9.170:8766

map:
  enabled: true

radar:
  enabled: true
  manifest_refresh_interval_s: 60.0
  stale_after_s: 900.0
  hide_after_s: 1800.0
  opacity: 0.55
```

The six-tile coverage margin and three-tile recenter threshold remain application policy rather than operator configuration.

## Forge API

### `GET /api/v1/radar`

Returns the latest provider-neutral manifest and radar health.

### `GET /api/v1/radar/coverage/{frame_token}/{z}/{x_start}/{y_start}/{columns}/{rows}.zip`

Returns one bounded exact-frame coverage rectangle as a ZIP containing validated `z/x/y.png` entries. The response identifies the frame token and tile count. This is the normal Pi bulk-acquisition path.

### `GET /api/v1/radar/tiles/{frame_token}/{z}/{x}/{y}.png`

Returns one validated 256x256 transparent PNG for compatibility/diagnostics. The current frame and immediately prior retained frame may be served while under the render cutoff; older/unknown tokens fail explicitly rather than silently returning another observation time.

All radar routes are read-only.

## Failure isolation

Radar failure must not block or change:

- GPS acquisition;
- base-map rendering;
- physical controls;
- radio state or tuning authority;
- shared POTA/DX spot data;
- local contact logging;
- Forge weather or weather alerts;
- retained mobile location;
- DMR, repeaters, or other dashboard contexts.

Radar frame/coverage processing does not write the Pi application database. The only radar-related database write is the explicit operator preference. No radar component has radio authority.

## Physical acceptance on Forge and anvilmobile

On the exact green PR head:

1. Deploy the same exact PR head to production Forge and `anvilmobile`.
2. Confirm Forge `/api/v1/health` and `/api/v1/radar` are healthy before starting the dashboard.
3. Start Rolling Thunder with radar enabled and confirm radar loads reliably from a cold Pi process.
4. Record `RADAR NOAA COVERAGE`, `RADAR FORGE COVERAGE READY`, and `RADAR PI COVERAGE READY` timings; confirm one/few large coverage requests replace hundreds of per-tile provider requests.
5. Observe ordinary base-map tile-boundary movement and confirm radar does not disappear/reload.
6. Confirm one to two tiles of movement remain continuous with no visible radar refresh.
7. Confirm movement to roughly the three-tile threshold starts BACK loading while FRONT remains visible.
8. Confirm the completed replacement swaps without a blank interval or flash.
9. Keep the dashboard running through at least one NOAA frame rollover and confirm the prior FRONT does not disappear while the new frame is prepared.
10. Confirm vehicle marker/GPS and base map remain responsive during radar coverage work.
11. Temporarily make Forge/radar unavailable and confirm an eligible FRONT is retained while geographically valid and unrelated functions remain usable.
12. Restore Forge/radar and confirm recovery without restarting the dashboard.
13. Change map zoom at least once and confirm old-zoom radar is never shifted/misregistered.
14. Confirm RADAR health remains truthful for ready, background update, stale/degraded, disabled, and unavailable states.
15. Confirm the 15-minute stale and 30-minute hide policy still follows provider observation time.
