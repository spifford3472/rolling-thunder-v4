# Persistent Map Zoom

## Purpose

Checkpoint #157 adds one mutable operator preference to the existing Settings
context: **Map Zoom**. The operator can change the live-map zoom with the physical
encoder while Settings is active, and the selected value survives an application
restart.

This checkpoint does not change radio control, GPS parsing, Forge, weather,
logging authority, or map-source priority.

## Persistence boundary

The YAML configuration remains immutable at runtime. `map.zoom` continues to be
the configured/default value, while the mutable operator selection is stored in
the same Pi SQLite database as the rest of Rolling Thunder.

Schema version 8 adds the generic `operator_preferences` table. Map Zoom uses the
stable key `map.zoom`.

Startup reads the stored value before the dashboard begins. A stored zoom is used
only when it is a valid integer and lies inside the effective zoom bounds. Missing,
malformed, or out-of-range data falls back to the configured zoom, clamped into
the effective range.

Runtime persistence is asynchronous. Tkinter and physical-control dispatch only
change the in-memory zoom and queue a short SQLite write on the preference worker.
They do not perform SQLite, filesystem, map-package, or network work directly.

## Effective bounds

When installed map packages exist for the configured visual style, their validated
MBTiles metadata defines the operator-selectable zoom interval. The current dark
I-71 package declares zoom `0-15`, so the installed vehicle configuration exposes
Map Zoom range `0-15`.

If no installed package exists for the active style, the generic raster-map range
`0-22` is used.

The bounds affect only the operator setting. Tile resolution remains local-first:
installed package, runtime cache, then allowed online fallback. Changing Map Zoom
does not weaken installed-package authority.

## Operator controls

Select **SETTINGS** using the existing physical context control. The Settings panel
shows:

```text
MAP ZOOM
15
RANGE 0-15
TURN ENCODER: OUT / IN
```

The existing `MOVE_PREVIOUS` encoder command zooms out by one level and
`MOVE_NEXT` zooms in by one level. The value does not wrap at either bound.
POTA/DX selection behavior is unchanged outside Settings.

A zoom change updates `LiveMapService` in memory. The next normal map refresh
requests the same current GPS position at the new zoom through the existing
single background map worker.

## anvilmobile acceptance

1. Update `anvilmobile` to the exact PR head and start the dashboard normally.
2. Select **SETTINGS** and confirm Map Zoom displays the current value and range
   `0-15` with the installed I-71 night package.
3. Rotate the encoder one step toward zoom out and confirm the displayed value
   decreases by one and the live map reframes without UI stalls.
4. Rotate the encoder toward zoom in and confirm the value increases by one.
5. Confirm the setting stops at `0` and `15` rather than wrapping.
6. Change the zoom to an easy-to-remember value such as `13`.
7. Stop Rolling Thunder through the normal SSH process, start it again, return to
   Settings, and confirm Map Zoom remains `13`.
8. Confirm POTA/DX selection, logging, GPS, MAP/GPS health, radio polling, and
   physical controls remain normal.

Record the installed result on the draft pull request before approval. Do not
merge without explicit repository-owner authorization for that exact PR.
