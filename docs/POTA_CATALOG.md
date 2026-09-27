# POTA Park Catalog

Rolling Thunder keeps the POTA park catalog in a separate SQLite reference database,
not in the operational contact database. This allows a large park-data refresh to be
validated and replaced without risking contacts, preferences, cached spots, or other
operator state.

## Source boundary

Parks on the Air documents a park as having a Program, one or more Locations, a
Name, Type, Latitude, and Longitude. The park Reference is the unique identifier.

POTA's published coordinates are approximate park-location pins. They are suitable
for catalog lookup and later nearby-candidate selection, but **not** for navigation,
activation-boundary decisions, or polygon rendering.

Checkpoint 2 deliberately does not fetch an undocumented POTA bulk endpoint. The
operator supplies a CSV export/file. This keeps updates reproducible and allows the
same importer to accept future official exports without application-code changes when
the required fields remain available.

Required logical CSV fields:

- reference
- name
- latitude
- longitude
- location(s)

The current state export also provides `grid`, `website`, and `notes`; Rolling Thunder retains those fields when present. Changing activity counters (`attempts`, `activations`, `qsos`) and operator-specific counters (`my_activations`, `my_hunted_qsos`) are intentionally ignored.

Recognized common aliases include `parkReference`, `parkName`, `lat`, `lon`,
`lng`, and `locationDesc`. Optional status/active and park-type fields are retained when present.

## Import

From the repository virtual environment:

```bash
rolling-thunder-pota-catalog /path/to/pota-states/*.csv \
  --database data/pota/pota-catalog.db \
  --source-version YYYY-MM-DD
```

The shell expands the glob to one or more state CSV files. All files are validated into one staging database. The command reports the imported park count, source-file count, destination, and a deterministic SHA-256 checksum representing the complete ordered source set.

## Safety and atomic promotion

Every refresh is built in a temporary SQLite database beside the live catalog.
All rows are validated before promotion. A malformed coordinate, missing required
field, duplicate park reference, invalid location list, unreadable source, or SQLite
failure rejects the refresh. The existing live catalog is left untouched.

Only after staging commits successfully is `os.replace()` used to promote the new
database atomically.

The database records:

- catalog schema version
- source filename for a single file, or source-file count summary for a multi-file import
- source-file count
- deterministic SHA-256 checksum for the complete source set
- optional source version/date
- UTC import timestamp
- park count

POTA state exports can contain the same park reference in multiple state files. The catalog therefore keys park occurrences by `(reference, location_code)`, preserving each POTA state/location occurrence instead of assuming the reference alone is unique. A park whose `locationDesc` contains multiple locations is likewise represented once for each location code. Indexes support reference, program, location, grid, latitude, and longitude candidate selection.

## Map markers

Checkpoint 3 intentionally uses these catalog coordinates as lightweight map markers
instead of loading park boundary polygons on the Raspberry Pi. This keeps the map
offline-friendly and avoids GIS geometry processing.

The dashboard queries only rows inside the current map viewport on a background
worker. At map zoom 14 and higher, each visible park is shown as a yellow,
black-outlined rectangle containing the POTA reference on the first line and the full
park name on the second line. Below zoom 14, the same location is represented by a
yellow dot with a black outline and no text. Overlapping high-zoom labels are
suppressed rather than stacked into unreadable text.

The marker layer is drawn above the base map and below weather radar, vehicle, and
status overlays. Multi-location catalog occurrences sharing the same reference, name,
and coordinate render as one marker.

These coordinates remain approximate POTA catalog pins. A marker is **not** a
navigation destination, property boundary, or guarantee that the coordinate itself is
inside a valid activation area. Operators must use appropriate authoritative mapping
to determine activation boundaries.

POTA map markers retain the last valid GPS-based viewport through brief GPS dropouts. The default grace period is 60 seconds (`pota_map.gps_grace_period_s`); after that, markers are cleared until a valid fix returns. A stationary vehicle does not clear markers while valid GPS fixes continue.
