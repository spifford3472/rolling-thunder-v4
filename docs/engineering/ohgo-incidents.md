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
provider-supplied and unverified for the driver's route. There are no driver
alerts, navigation changes, or map overlays.

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

## Verification and rollback

Deterministic coverage is in `tests/test_forge_ohgo_incidents.py`,
`tests/test_forge_ohgo_api.py`, `tests/test_forge_ohgo_credentials.py`,
`tests/test_ohgo_panel.py`, `tests/test_ohgo_ui.py`, and
`tests/test_context_navigation.py`. These cover API/provider isolation,
response validation, disabled/stale states, rendering, separators, MORE,
rotary scoping, and context navigation without live credentials or hardware.

Source rollback uses the exact prior application commit through the approved
deployment wrapper. Forge credential or unit changes are outside this source
change and require their own approval and rollback procedure. No MeshCore
history or SQLite data is part of OHGO rollback.

## Historical naming

The original Pi files were named `meshcore_ohgo_panel.py` and
`meshcore_ohgo_ui.py` because the view shared a screen with MeshCore. The
screen's provider, data path, and behavior were always OHGO-only. The
MC-REMOVE source change renames these files to `ohgo_panel.py` and
`ohgo_ui.py`; the old names remain visible in Git history.
