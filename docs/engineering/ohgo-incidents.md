# OHGO incidents — Forge service and Rolling Thunder screen

## Architecture

OHGO is provided by Forge and displayed by Rolling Thunder independently of
MeshCore. The existing Forge spots process owns the protected OHGO credential,
provider polling, cached snapshot, and the versioned read-only route
`GET /api/v1/ohgo/incidents`. It adds no listener, port, database, scheduler,
or GPS pipeline.

On the Pi, `ohgo_panel.py` polls the existing Forge API on a bounded background
thread and publishes an immutable, age-checked state. `ohgo_ui.py` renders the
snapshot as a large-text, wrapped view with horizontal separators and a fixed
MORE indicator derived from actual text geometry. The `o` shortcut selects the
OHGO context. Rotary next/previous scrolls the displayed text only while OHGO
is selected; other contexts continue through the shared control dispatcher.
Tk reads the published snapshot and does not perform HTTP work.

The OHGO context has no MeshCore USB, process, database, queue, GPS publisher,
or broker dependency. A disabled, stale, unavailable, or empty response has an
explicit status; an empty list is not represented as clear roads. Reports are
provider-supplied and unverified for the driver's route. The separate map
overlay below also has no alert or navigation authority.

## Forge provider contract

Forge requests `GET https://publicapi.ohgo.com/api/v1/incidents` for the
configured southwest Ohio region using the protected `Authorization: APIKEY`
header. Polling is limited to one request per 120 seconds with a four-second
timeout and a two-megabyte response bound. Conditional ETag requests may reuse
a validated snapshot. Redirects, rejected filters, malformed envelopes,
truncation, and multi-page responses are rejected rather than rendered as a
complete incident set. The route publishes at most 100 records with
`driver_alert_permitted: false`.

The provider is independently opt-in on Forge. Without both the environment
gate and protected systemd credential, it makes no upstream request and the
route reports `disabled`. The Pi never stores the key or calls OHGO directly.

## Statewide map layers

Forge publishes `GET /api/v1/ohgo/map-layers` on the existing private spots
listener. The response schema is `rolling-thunder/ohgo-map-layers/v1`. Its
`layers` object has one key for each of `construction`,
`dangerous-slowdowns`, `incidents`, and `travel-delays`. Each value contains
`status`, `fetched_at` (ISO 8601 UTC or null), and `markers` (objects with
`id`, `latitude`, and `longitude`). Status is `current`, `stale`,
`disabled`, `incomplete`, or `unavailable`. A current empty array means
the validated feed has no usable markers in that category. Other statuses have
empty arrays. The route neither fetches upstream nor accepts vehicle coordinates.

The worker shares the existing enable gate, protected key, HTTPS allowlist,
four-second request timeout and 2 MB per-response bound. It requests the
[official OHGO v1 resources](https://publicapi.ohgo.com/docs/v1/resources)
with [`page-all=true`](https://publicapi.ohgo.com/docs/v1/filters) and no
regional filter, and verifies the provider's page and record totals. An
incomplete or oversized page set is never rendered as a current statewide list.
The overlay uses top-level latitude and longitude. Construction uses the
provider's default active results with `exclude-work-zone=true`; nested work
zones use longitude then latitude and are unnecessary for point markers.
Travel delays use the top-level coordinates documented in the resource guide.
The published Swagger currently references the incident envelope for travel
delays. The overlay depends only on ID and the two shared coordinate fields.

The four resources each get at most one request per 120 seconds in normal
operation. Category-local failures back off to four and then eight minutes.
A successful conditional 304 renews a previously validated category.
The regional incident poll continues separately at up to one request per
120 seconds. The combined budget is at most five requests per two-minute
cycle. The regional call retains OHGO's configured region filtering, text
fields, existing order, and result bounds. The statewide marker feed and
regional text route cannot substitute for one another without changing those
semantics. The map route publishes at most 4,000 records per category after
checking the page envelope and deduplicating by provider ID. Both hosts expire
a current category after five minutes. No upstream access happens per viewport.

The Pi Settings controller keeps four independent operator preferences in the
existing SQLite preference table. The map service observes the GPS poller's
accepted fixes and resolves the current coordinate via the bundled Census
jurisdiction artifact on a dedicated background worker. It uses the same GPS
validity/freshness rules as the primary map. It rejects future-dated fixes too.
An unresolved fix, stale fix, or any result other than OH pauses new overlay
requests and removes markers. Panning or the map's last-known center cannot
satisfy the gate. With a valid Ohio fix and at least one enabled layer, the
Pi makes at most one Forge request every 30 seconds using a two-second
request timeout and a 5 MB response cap. A request already underway can finish
after the gate closes. Forge outages retain only still-fresh marker data. All
HTTP, decoding, and jurisdiction artifact access run outside Tk.

The primary map uses its visible Web Mercator viewport and redraws on changes
to relevant settings, data, or viewport. At dense zooms the renderer draws at
most one point per 24-pixel cell per category and 48 points per category per
viewport. Zoom in for local detail.

## Verification and rollback

Deterministic coverage is in `tests/test_forge_ohgo_incidents.py`,
`tests/test_forge_ohgo_api.py`, `tests/test_forge_ohgo_credentials.py`,
`tests/test_ohgo_panel.py`, `tests/test_ohgo_ui.py`, and
`tests/test_context_navigation.py`. These cover API/provider isolation,
response validation, disabled/stale states, rendering, separators, MORE,
rotary scoping, and context navigation without live credentials or hardware.

Source rollback uses the exact prior application commit through the approved
deployment wrapper. Forge credential or unit changes are outside this source
change and require their own approval and rollback procedure. The four operator preferences add ordinary rows to the existing table
and require no schema migration. Use current durable data during rollback.
Turn all four map selections OFF to disable the overlay immediately.

### Parked acceptance

1. Before any approved release, independently verify the installed checkout
   and service health on both hosts. Read-only checks on November 22, 2026
   observed Forge spots at `bf63f255a3d1b502488ce0fa612312ef1ae880a1`
   (healthy, DX connection live) and AnvilMobile at
   `ef6afb31fb5b9706c6b8185f3028a7d90bace60c` (service active and owner-verified
   OHGO scrolling, tagged `rollback/anvilmobile-2026-11-22`). Recheck before
   release and use the freshly verified exact previous SHAs for rollback.
2. After separate approval, use the existing [exact SHA deployment
   wrappers](codex-deployment-workflow.md). Verify Forge first. Check all four
   category statuses and the existing regional route, spots, weather, and radar
   on the existing listener. Then validate AnvilMobile while parked.
3. In full screen, use the encoder and B2/B3 to enable each icon, use multiple
   layers, compare day/night readability and zoom responsiveness, verify
   persistence after an approved restart, and check the vehicle, POTA, and radar
   layers. Verify OHGO text, separators, MORE, and rotary context isolation.
   Use recorded fixes to validate Ohio exit, stale fixes, and return when a
   real boundary crossing is impractical. Verify the overlay disappears while
   the base map stays usable during an isolated feed outage.
4. For rollback, disable all four toggles first if the UI is usable. Restore
   only the affected component through its approved wrapper using the exact
   pre-release SHA. Retain the current database and the wrapper's backups and
   verify service health and the regional OHGO context afterward.

## Historical naming

The original Pi files were named `meshcore_ohgo_panel.py` and
`meshcore_ohgo_ui.py` because the view shared a screen with MeshCore. The
screen's provider, data path, and behavior were always OHGO-only. The
MC-REMOVE source change renames these files to `ohgo_panel.py` and
`ohgo_ui.py`; the old names remain visible in Git history.
