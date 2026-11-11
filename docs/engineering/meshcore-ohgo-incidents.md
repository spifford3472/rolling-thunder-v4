# MeshCore & OHGO incident view — source staging and operational gates

## Scope and actual state

This source update adds a dashboard context labelled **MESHCORE & OHGO** (keyboard
shortcut `o`) alongside the existing contexts. Its MeshCore label describes
the independently running, *passive receive-only* collector; no source text or
private MeshCore data is exposed in the OHGO view. OHGO incidents are separate
ODOT-sourced observations, not confirmation of MeshCore reports or a
matched navigation route.

The UI remains local-first: the Pi only polls a retained, read-only endpoint
from the **existing Forge spot service** at
`GET /api/v1/ohgo/incidents`. The request runs on a small background thread,
not the Tkinter refresh. It shows at most four brief official records and
explicit disabled, stale, and unavailable states. The existing context
navigation, FT8, POTA/DX, DMR, radio, GPS and map behavior are unchanged aside
from the new context. There are no map-layer overlays or driver alerts.

The Forge composition adds an optional, isolated OHGO HTTP fetch worker to
the existing spots process, **disabled by default**. It does not create a new
listener, port, database, radio authority, cron or second GPS pipeline.
The read-only route exposes a versioned schema with source, status, fetched
timestamp, bounded incident markers and explicit
`driver_alert_permitted:false`. It cannot trigger upstream fetch on a
request; provider retrieval occurs only on its own bounded worker.

## Official API contract

OHGO official documentation:

- https://publicapi.ohgo.com/docs/v1/incidents
- https://publicapi.ohgo.com/docs/api-key
- https://publicapi.ohgo.com/docs/cache
- https://publicapi.ohgo.com/docs/v1/filters

The source requests `GET https://publicapi.ohgo.com/api/v1/incidents` with
`region=sw-ohio&page-size=100`. It uses an
`Authorization: APIKEY <credential>` header, never a query-key URL.
The provider sends an `If-None-Match` header when a previously validated ETag
is present; 304 may refresh the fetch timestamp without altering records.
Requests are limited to at most once per 120 seconds, with a four-second
timeout and a 2 MB maximum body. Unexpected redirects and external hosts are
rejected. Any error, rejected region filter, invalid envelope, or multi-page
response becomes **unavailable** rather than an incomplete list presented as
all incidents. Region coverage and live API data remain unverified until the
operator activates a real key on Forge.

Each retained item has only a provider ID, coordinate, route, travel direction,
category, short description, location, and road status. Malformed coordinates
and duplicates are omitted. This information is **provider reported**; neither
the app nor its geospatial code verifies an event or the user's route.
Provider records are not copied into the traffic ledger or QSO log.

## Secrets and activation

OHGO requires registration at https://publicapi.ohgo.com/ before a real
API key can be obtained. **No key has been provisioned or enabled in this
source change.** A separate operator-approved Forge maintenance step must:

1. Review actual Forge spot-service identity and existing secrets policy.
   Current observed service uses `rolling-thunder-forge-spots.service`,
   `User=rollingthunder`, `EnvironmentFile=-/etc/rolling-thunder/forge-spots.env`
   and `/etc/rolling-thunder/forge-spots.yaml`.
2. Place the API key in a root-protected outside-Git file
   `/etc/rolling-thunder/ohgo-api-key`, mode 0600. Never paste the key into
   chat or console command history.
3. Review and install the **staged, uninstalled** unit drop-in template
   `deploy/forge-ohgo-credentials.conf` under
   `/etc/systemd/system/rolling-thunder-forge-spots.service.d/30-ohgo.conf`.
   It uses `LoadCredential=ohgo-api-key:/etc/rolling-thunder/ohgo-api-key`
   and the operator opt-in `ROLLING_THUNDER_OHGO_ENABLED=1`.
4. Back up any prior drop-in, run `systemd-analyze verify`, load the revised
   configuration, and restart **only** the existing Forge spots component
   through the approved deployment path, verifying FT8, other spot routes,
   radar, weather and map endpoints. Any service change needs its actual
   as-built record and rollback in the private QTH infrastructure repository.
5. Independently validate real OHGO HTTP response schema, region coverage,
   rate-limiting, cache, 304/401/403/429/5xx behavior, key rotation, and
   screen data quality before marking the integration field-accepted.

In the absence of both the environment gate and a valid systemd credential,
the provider performs zero OHGO network requests and the Forge route
returns `disabled` with no incidents.

## Testing and rollback

New deterministic tests cover disabled key, safe HTTP origin, rejected
truncation, metadata bounds, independent Forge route delegation, 304 caching,
rate limit, stale/unavailable results, UI presentation and navigation.
Ruff, strict MyPy, full pytest and GitHub CI are required before merging.
Do not claim a real incident was fetched until the key is provisioned and
observed provider results are validated.

Source rollback: use exact previous SHA via the approved restricted
deployment wrappers. Host-level OHGO rollback: remove/disable only the
reviewed OHGO systemd drop-in, `daemon-reload` and restart the existing
Forge spots service with prior known-working code, protecting the API key,
and verify disabled status without affecting other Forge services.
Never roll back MeshCore broker/traffic/QSO SQLite records or change SCOUT
cursors. The Pi's new tab works safely in disabled/unavailable mode.

**Future issue #408:** separate approval and implementation for OHGO
construction, work zones, detours, delays and optional map layers. No such
features are included in this incident-only source change.
