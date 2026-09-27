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

Park locations are normalized into a child table because a park can span more than
one POTA location. Indexes support program, location, latitude, and longitude
candidate selection.

## Separation from polygons

This database stores POTA reference points and descriptive catalog data only.
Checkpoint 3 will add boundary geometry through a separate source/representation.
A polygon must never be invented from a POTA coordinate, and missing polygon
coverage must not make a valid POTA catalog record disappear.
