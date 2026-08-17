# Rolling Thunder Weather Radar

Rolling Thunder provides an optional latest-frame weather-radar overlay on the live map. Radar is situational awareness only. It has no radio, CAT, PTT, tuning, logging, or transmit authority.

## Architecture

Radar follows the same safety boundary as the rest of Rolling Thunder:

1. NOAA/NWS is contacted only by Forge.
2. Forge normalizes provider metadata into Rolling Thunder-owned radar models.
3. Forge exposes a provider-neutral manifest and exact-frame tile API on the existing Forge service and port.
4. The Pi contacts only Forge.
5. The Pi radar worker performs manifest/tile I/O and fixed-opacity PNG processing outside Tkinter.
6. Tkinter consumes immutable overlay snapshots and draws already-prepared PNGs between the base map and the vehicle/status overlays.

The existing base-map resolver is unchanged:

`installed MBTiles -> runtime cache -> online tiles`

Radar is a separate optional overlay and never becomes a base-map source.

## Visible viewport and radar coverage viewport

The visible map viewport and radar coverage are intentionally different concepts.

- **Visible map viewport** — the map rectangle currently on screen.
- **Radar coverage viewport** — a larger immutable Web Mercator tile rectangle retained around the visible map.

The Pi normally renders the visible map as a moving crop/window into the current radar coverage buffer. Ordinary GPS movement therefore does not require a radar manifest or tile request merely because the visible map crossed a tile boundary.

The default coverage policy adds **six whole radar tiles on every side** of the visible viewport. If the visible tile rectangle is `W x H`, the retained coverage is approximately:

`(W + 12) x (H + 12)`

The coverage is centered on the visible viewport when a generation is requested. Containment and remaining reserve are calculated with pure tile-coordinate geometry, including wrapped longitude handling. The policy is independent of Tkinter.

## Spatial recenter threshold

With six tiles of reserve on each side, a replacement radar coverage generation begins when the minimum remaining reserve reaches **three tiles**. This uses half of the original reserve as the recenter threshold.

Consequences:

- one tile of ordinary movement remains inside the FRONT buffer with no radar HTTP work;
- two tiles of movement remain inside the safe region with no radar reload;
- about three tiles of movement are still geographically covered, but crossing the three-tile reserve threshold schedules a replacement in the background;
- the old coverage remains the displayed FRONT buffer while that replacement is built.

The system does not wait until the visible screen reaches the outside edge of retained coverage.

## FRONT/BACK buffering

The Pi radar service owns a double-buffered publication model.

### FRONT buffer

The FRONT buffer is one complete, immutable, exact-frame radar coverage area. It remains published while geographically valid and under the radar hide-age cutoff.

Movement within FRONT coverage creates a new immutable **visible crop snapshot** using the already-prepared FRONT PNG bytes and the current map placements. No network, disk, manifest, opacity processing, or image decoding is required to reframe those pixels.

### BACK buffer

A BACK generation is prepared entirely by the radar background worker. It may retrieve a manifest, fetch missing tiles, validate PNGs, apply fixed opacity, and assemble a complete immutable coverage buffer.

BACK data is never progressively displayed. A partial BACK generation cannot replace a complete FRONT buffer.

When BACK is complete, exact-frame valid, still relevant to the newest desired map position, and usefully centered around it, publication swaps atomically to the new FRONT buffer. If a newer desired target supersedes it, the obsolete generation is discarded instead of publishing over newer intent.

Diagnostic logging distinguishes the important transitions with messages equivalent to:

- `RADAR FRONT REFRAME`
- `RADAR BACK LOAD START`
- `RADAR BACK LOAD SUPERSEDED`
- `RADAR BUFFER SWAP`
- `RADAR REFRESH BY AGE`
- `RADAR REFRESH BY SPATIAL THRESHOLD`

## Same-frame overlap reuse

Spatial recentering does not blindly redownload a complete coverage rectangle. When the selected manifest still identifies the same exact radar frame, the BACK builder reuses overlapping prepared PNG bytes from FRONT and requests only newly exposed edge tiles.

For example, a three-tile horizontal recenter requests roughly three new tile columns, not the complete coverage rectangle. This keeps movement-triggered Pi-to-Forge and Forge-to-NOAA work bounded while preserving the six-tile reserve.

A new meteorological frame cannot reuse old-frame radar pixels. When the manifest selects a new frame token, the BACK generation loads all required coverage tiles for that new exact frame before publication.

## Generation, supersession, and coalescing

Radar work is bounded to:

- one published FRONT buffer;
- one active BACK generation;
- at most one newest desired replacement target.

Intermediate movement is coalesced rather than queued. If the vehicle moves while BACK is loading, the service retains only the newest target that the active BACK cannot adequately cover. The active worker checks for supersession before requesting further tiles and stops obsolete work as soon as practical.

A completed obsolete generation never overwrites a newer desired radar state.

## Spatial and meteorological refresh are independent

Radar may refresh for two independent reasons.

### Spatial refresh

The visible viewport has consumed enough of the current coverage reserve to cross the three-tile recenter threshold. If the cached manifest is still within its allowed check interval, spatial recentering uses that manifest and does **not** perform a new manifest request merely because the map moved.

### Meteorological refresh

The manifest-refresh interval expires, meaning a newer NOAA observation may be available. This refresh can occur without any vehicle movement. FRONT remains visible while the candidate latest frame is prepared.

Reframing never changes the provider observation timestamp. Radar age always derives from provider observation time.

## Exact-frame rule

Every published radar coverage buffer is frame-atomic. Forge locks every requested tile to the exact provider raster represented by the opaque Rolling Thunder frame token. The Pi then builds one BACK generation using that same token.

If NOAA advances while BACK is loading, the in-flight generation continues under its locked frame or is safely superseded. Tiles from different observation times are never intentionally mixed in one published coverage buffer.

A complete older FRONT buffer is preferred to a partial newer BACK buffer.

## Freshness policy

Freshness is based on provider observation time, not when Forge or the Pi downloaded or reframed data.

- up to 15 minutes old: normal display;
- more than 15 minutes old: display may continue, but radar is marked stale;
- more than 30 minutes old: radar is not rendered.

Provider or Forge failures do not erase a still-eligible complete FRONT buffer. When an attempted update fails, the Pi retains FRONT while it still truthfully covers the visible map and remains under the hide cutoff.

If the vehicle moves outside retained geographic coverage while replacement radar remains unavailable, the Pi does not stretch or misregister the old radar. The overlay is removed for that viewport while the base map and all unrelated functions continue.

## Zoom behavior

Radar coverage belongs to one Web Mercator zoom level. A FRONT buffer at zoom `Z` is never treated as radar data for `Z+1` or `Z-1`.

On a map zoom change:

1. the old-zoom radar is immediately considered geographically incompatible with the new visible viewport;
2. the old radar is not stretched or shifted into the new zoom;
3. a new enlarged radar coverage buffer for the new zoom is prepared in the background;
4. the new zoom radar appears only after the complete exact-frame BACK buffer is ready.

The base map remains responsive during this transition.

## Rendering behavior

The visual layer order remains:

`BASE MAP -> RADAR -> VEHICLE / STATUS OVERLAYS`

Tkinter receives only the current immutable visible radar crop. It does not hold Tk `PhotoImage` objects for every off-screen tile in the larger radar coverage.

For same-frame movement, the renderer plans radar canvas work as remove/redraw/move. Unchanged visible radar canvas image objects are retained and repositioned when only their screen coordinates changed. A weather-frame swap redraws the visible radar tiles for the new frame atomically.

Tkinter performs no HTTP, filesystem, SQLite, opacity processing, or other expensive radar work.

## Resource bounds

Radar tiles are 256x256 pixels. One decoded RGBA tile is 262,144 bytes (256 KiB). The retained Pi coverage stores already-prepared PNG bytes rather than decoding the entire off-screen coverage into Tk images.

The dashboard gives the right situational/map column three fifths of full-screen width. Exact visible tile count depends on the installed display dimensions and sub-tile offset, so the deterministic sizing rule is more useful than assuming one monitor resolution:

- visible `W x H` tile rectangle;
- coverage `(W + 12) x (H + 12)`;
- total coverage tiles `(W + 12) * (H + 12)`.

Representative bounds:

| Visible tile rectangle | Six-tile coverage | Coverage tiles | Raw RGBA equivalent per complete buffer |
| --- | --- | ---: | ---: |
| 3 x 3 | 15 x 15 | 225 | 56.25 MiB |
| 4 x 4 | 16 x 16 | 256 | 64 MiB |
| 5 x 5 | 17 x 17 | 289 | 72.25 MiB |
| 6 x 6 | 18 x 18 | 324 | 81 MiB |

Those memory figures are conservative **raw decoded equivalents**, not expected PNG byte sizes. The coverage buffers retain compressed PNG bytes, while Tk decodes only visible/cache-resident images. The Tk radar `PhotoImage` cache remains bounded at 128 entries, a raw-RGBA equivalent ceiling of about 32 MiB for that cache.

Normally the Pi retains only one complete FRONT buffer plus one BACK generation under construction and tightly bounded presentation objects. No radar history is accumulated.

Forge's radar tile cache remains bounded at the existing default of 256 tiles. A larger coverage rectangle can exceed 256 tiles, but same-frame spatial recentering reuses FRONT overlap on the Pi and therefore does not immediately ask Forge for evicted overlapping tiles. A new weather frame may require one bounded full-coverage load (up to the selected viewport size) because old-frame pixels cannot be reused. The existing 256-tile Forge bound is therefore retained rather than increased without evidence of pathological churn.

## Initial provider and product

The initial provider is the NOAA/NWS time-enabled MRMS base-reflectivity ImageServer. Provider-specific ArcGIS fields, raster IDs, mosaic rules, and URLs remain Forge-side.

Rolling Thunder publishes the product as the provider-neutral token:

`base_reflectivity`

Each accepted frame contains:

- an opaque Rolling Thunder frame token;
- provider observation time;
- Forge fetch time;
- provider/product identity;
- required attribution metadata.

The Pi never receives or stores the NOAA raster/object identifier.

## Display policy

Rolling Thunder intentionally supports only the latest frame.

- fixed opacity: 55%;
- no animation;
- no timeline controls;
- no route prediction;
- no automatic intensity or opacity policy;
- no regional/offline radar seeding.

NOAA/NWS attribution and radar observation time remain visible separately from base-map attribution.

The map health box always labels the radar row simply `RADAR`; transient text such as `UPDATING RADAR` is not displayed there. Color carries the compact state:

- light blue: radar image ready/healthy;
- yellow: waiting, background loading, stale, or degraded;
- gray: radar image disabled or the radar capability is not configured;
- red: radar image unavailable/error.

## Operator Settings control

When the radar capability is configured, the Settings page exposes a `RADAR Image` on/off switch with the helper text `Context Button #1`.

Context Button #1 toggles only Pi-side radar image work. Turning the image off:

- immediately clears the visible radar overlay;
- publishes the local radar state as disabled;
- suppresses new Pi radar viewport, manifest, tile, and image work while disabled;
- prevents an obsolete in-flight generation from publishing after disable;
- does not disable or reconfigure the Forge radar service;
- does not change the base map, GPS, logging, controls, or radio authority.

Turning the image back on returns the Pi radar worker to an idle/waiting state. The next normal map refresh requests enlarged coverage around the current map viewport and returns to light blue when a complete healthy frame is ready.

The operator choice is persisted asynchronously in the existing local `operator_preferences` SQLite table under `radar.image.enabled`. The setting survives application restarts without rewriting `rolling-thunder.yaml`.

## Forge configuration

Radar is opt-in. Existing Forge configurations remain valid because the default is disabled.

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

Forge uses the latest retained mobile location for frame discovery. Missing location, NOAA failure, malformed metadata, invalid PNG data, or tile retrieval failure affects radar health only and must not destabilize spots, weather, mobile-location retention, or the Forge process.

## Pi configuration

The Pi overlay capability is independently opt-in and requires both the map and Forge client to be enabled.

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

`radar.enabled: true` is rejected at configuration validation time unless both `map.enabled` and `forge.enabled` are true. The six-tile coverage margin and three-tile recenter threshold are current application policy rather than operator configuration, so no YAML keys are added for this change.

## Forge API

### `GET /api/v1/radar`

Returns the latest provider-neutral manifest and radar health. The response includes API schema version `1`, revision, optional frame, provider health, stale state, and render eligibility.

The endpoint is read-only. Unsupported methods return HTTP 405 with `Allow: GET`.

### `GET /api/v1/radar/tiles/{frame_token}/{z}/{x}/{y}.png`

Returns one validated 256x256 transparent PNG for the exact opaque frame token and Web Mercator tile coordinate.

The token must still identify the current retained Forge radar frame and that frame must remain under the render cutoff. Wrong/obsolete tokens return an explicit unavailable/conflict response rather than silently returning a tile from another observation time.

The response includes `X-Rolling-Thunder-Radar-Frame` so acceptance tests can prove exact-frame locking.

## Failure isolation

Radar is optional end to end. A radar failure must not block or change:

- GPS acquisition;
- base-map rendering;
- physical controls;
- radio state or tuning authority;
- shared POTA/DX spot data;
- local contact logging;
- Forge weather or weather alerts;
- retained mobile location;
- DMR, repeaters, or other dashboard contexts.

Radar frame/tile processing does not write the Pi application database. The only radar-related database write is the explicit operator `RADAR Image` preference, queued through the existing nonblocking operator-preference service. No radar component has radio authority.

## Physical acceptance on anvilmobile

On the exact green PR head:

1. Start Rolling Thunder with radar enabled and confirm radar appears normally.
2. Observe movement through ordinary base-map tile boundaries and confirm radar does not disappear/reload.
3. Confirm one to two tiles of movement remain continuous with no visible radar refresh.
4. Confirm movement out to roughly the three-tile threshold remains geographically aligned while BACK loading begins.
5. Use the radar diagnostic events to distinguish FRONT reframes, BACK load start, supersession, spatial/age refresh, and buffer swap.
6. Confirm FRONT remains visible while BACK is loading and the completed replacement swaps without a blank interval or flash.
7. Confirm the vehicle marker/GPS and base map remain responsive during radar work.
8. Temporarily make Forge/radar unavailable and confirm an eligible FRONT is retained while covered, unrelated functions remain usable, and no old radar is stretched beyond its geographic coverage.
9. Restore Forge/radar and confirm recovery without restarting the dashboard.
10. Change map zoom at least once and confirm old-zoom radar is removed rather than shifted/misregistered, followed by correctly aligned radar at the new zoom.
11. Confirm RADAR health remains truthful for ready, background update, stale/degraded, disabled, and unavailable states.
12. Confirm the 15-minute stale and 30-minute hide policy still follows provider observation time.
