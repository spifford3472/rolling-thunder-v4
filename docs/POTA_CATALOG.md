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

Recognized common aliases include `parkReference`, `parkName`, `lat`, `lon`,
`lng`, and `locationDesc`. Optional status/active and park-type fields are retained
when present.

## Import

From the repository virtual environment:

```bash
rolling-thunder-pota-catalog /path/to/parks.csv \
  --database data/pota/pota-catalog.db \
  --source-version YYYY-MM-DD
```

The command reports the imported park count, destination, and SHA-256 checksum.

## Safety and atomic promotion

Every refresh is built in a temporary SQLite database beside the live catalog.
All rows are validated before promotion. A malformed coordinate, missing required
field, duplicate park reference, invalid location list, unreadable source, or SQLite
failure rejects the refresh. The existing live catalog is left untouched.

Only after staging commits successfully is `os.replace()` used to promote the new
database atomically.

The database records:

- catalog schema version
- source filename
- SHA-256 checksum
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
