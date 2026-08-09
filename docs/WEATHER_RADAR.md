# Rolling Thunder Weather Radar

Checkpoint #163 adds an optional latest-frame weather-radar overlay to the existing live map. Radar is situational awareness only. It has no radio, CAT, PTT, tuning, logging, or transmit authority.

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

## Exact-frame viewport rule

A visible radar viewport is frame-atomic. Forge locks every requested tile to the exact provider raster represented by the opaque frame token. The Pi then loads all tiles for one `MapViewport` using that same token.

If NOAA advances to a newer raster while an existing viewport is loading, the in-flight generation finishes or is superseded using its original frame token. A later generation adopts the newer frame. Tiles from two observation times are never intentionally published in one immutable overlay snapshot.

If a new frame is only partially available and a complete prior frame for the same tile set remains eligible to render, the Pi retains the prior complete frame rather than mixing old and new pixels.

## Freshness policy

Freshness is based on the provider observation time, not merely when Forge or the Pi downloaded data.

- up to 15 minutes old: normal display;
- more than 15 minutes old: display may continue, but radar is marked stale;
- more than 30 minutes old: radar is not rendered.

Provider or Forge failures do not erase a still-eligible complete frame. When a manifest refresh fails but a cached frame is still renderable, the Pi retains that frame with degraded health. After the 30-minute cutoff, that frame is removed from display.

## Display policy

Checkpoint #163 intentionally supports only the latest frame.

- fixed opacity: 55%;
- no animation;
- no timeline controls;
- no route prediction;
- no automatic intensity or opacity policy;
- no regional/offline radar seeding.

The dashboard displays radar above base-map tiles and below the vehicle/status overlays. NOAA/NWS attribution and the radar observation time remain visible separately from base-map attribution.

The map health box always labels the radar row simply `RADAR`; transient text such as `UPDATING RADAR` is not displayed there. Color carries the compact state:

- light blue: radar image ready/healthy;
- yellow: waiting, loading, stale, or partial/degraded;
- gray: radar image disabled or the radar capability is not configured;
- red: radar image unavailable/error.

## Operator Settings control

When the radar capability is configured, the Settings page exposes a `RADAR Image` on/off switch with the helper text `Context Button #1`.

Context Button #1 toggles only Pi-side radar image work. Turning the image off:

- immediately clears the visible radar overlay;
- publishes the local radar state as disabled;
- suppresses Pi radar viewport, manifest, and tile work while disabled;
- does not disable or reconfigure the Forge radar service;
- does not change the base map, GPS, logging, controls, or radio authority.

Turning the image back on returns the Pi radar worker to an idle/waiting state. The next normal map refresh requests the current published map viewport, shows yellow while loading, and returns to light blue when a complete healthy frame is ready.

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

`radar.enabled: true` is rejected at configuration validation time unless both `map.enabled` and `forge.enabled` are true. This YAML setting controls whether the radar capability is composed at all. The Settings-page `RADAR Image` switch is the persistent operator runtime/display preference inside that configured capability.

## Forge API

### `GET /api/v1/radar`

Returns the latest provider-neutral manifest and radar health. The response includes API schema version `1`, revision, optional frame, provider health, stale state, and render eligibility.

The endpoint is read-only. Unsupported methods return HTTP 405 with `Allow: GET`.

### `GET /api/v1/radar/tiles/{frame_token}/{z}/{x}/{y}.png`

Returns one validated 256x256 transparent PNG for the exact opaque frame token and Web Mercator tile coordinate.

The token must still identify the current retained Forge radar frame and that frame must remain under the render cutoff. Wrong/obsolete tokens return an explicit unavailable/conflict response rather than silently returning a tile from another observation time.

The response includes `X-Rolling-Thunder-Radar-Frame` so acceptance tests can prove exact-frame locking.

## Failure isolation

Radar is optional end to end.

A radar failure must not block or change:

- GPS acquisition;
- base-map rendering;
- physical controls;
- radio state or tuning authority;
- shared POTA/DX spot data;
- local contact logging;
- Forge weather;
- retained mobile location.

Radar frame/tile processing does not write the Pi application database. The only #163 database write is the explicit operator `RADAR Image` preference, queued through the existing nonblocking operator-preference service. No radar component has radio authority.

## Acceptance gates

Checkpoint #163 is not complete until all of the following pass on the applicable exact PR head:

- Ruff;
- strict MyPy;
- full pytest;
- live NOAA/NWS frame discovery from the real retained mobile location;
- exact-frame tile retrieval for an Ohio viewport;
- provider observation time and attribution verification;
- 15-minute stale and 30-minute hide behavior;
- Forge `/health`, `/spots`, `/weather`, and mobile-location behavior remain healthy/independent;
- anvilmobile loads radar through Forge only;
- the overlay follows the current published map viewport and zoom;
- radar health displays only `RADAR` using the approved state colors;
- Settings Context Button #1 toggles the radar image off/on and the choice persists;
- no visible Tkinter blocking/flicker during radar retrieval or toggling;
- base map remains usable when radar is disabled or unavailable.
