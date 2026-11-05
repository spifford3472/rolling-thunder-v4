# Offline operating-county lookup — initial geometry checkpoint

## Status and scope (2026-11-04)

**Development only, not wired into contact logging or deployed.** Issue #380
requires county lookup for a frozen, valid GPS snapshot, persistence and ADIF
`MY_CNTY` export. This checkpoint implements only a pure, deterministic
polygon lookup primitive in `offline_county.py`, with synthetic test polygons.
There is **no production county dataset** in this commit, so the resolver
cannot currently identify real counties.

## Contracts

- Inputs: WGS84 latitude and longitude in degrees and immutable, prevalidated
  county polygon records; coordinate tuples in the geometry are (longitude,
  latitude). A county may have multiple components and holes.
- Output: a unique (state, county) pair or None. Missing, invalid, out-of-range,
  outside, overlapping county, near-edge or hole-edge positions return None.
- Near-edge buffer defaults to 0.0001 degrees (~11 m latitude); this is a
  conservative angular geometry tolerance, **not** a guarantee of GPS accuracy
  or county-boundary accuracy. Future caller must incorporate measured GPS
  uncertainty and source-data accuracy.
- Pure lookup: no filesystem, network, database, current GPS, radio, UI, or
  provider calls. Caller is responsible for freshness and freezing the fix
  before lookup. Do not invoke full-dataset scans on Tk refresh or FT8
  transmit-critical threads; introduce a bounded spatial index/candidate filter
  before integrating a nationwide dataset.
- This prototype assumes conventional longitude/latitude planar rings and
  does not yet address antimeridian geometries or high-latitude geodesic
  boundary distances. Fail closed or exclude unsupported geometries at dataset
  validation.

## Data-source acceptance gate

Select a versioned public authoritative county boundary release (candidate:
US Census Bureau cartographic county boundaries), record its exact source URL,
publication vintage, checksum, attribution/license, geographic coverage, and
any simplification/accuracy limits. Convert and validate it offline on Forge,
including MultiPolygon, interior rings, Alaska/territories, and border
ambiguity. Package an immutable indexed artifact suitable for the Pi memory
budget, with a documented update mechanism and rollback. Confirm real
locations and county-crossing fixtures against authoritative boundary data.

## Integration gates (not yet implemented)

1. Identify ordinary and FT8 frozen GPS/freshness boundaries and test stale
   fixes, unknown counties, and international positions.
2. Add optional `my_county` through Contact, schema-22 additive migration,
   repositories, idempotency, manual/FT8 logging, immutable JSON/sync
   compatibility, and receiver-first rollout where necessary.
3. Add `MY_CNTY` to ADIF only when a trustworthy state/county pair exists;
   do not set `CNTY` (the remote station's county).
4. Regression tests for database upgrade/restore, contact synchronization,
   timing, and Wavelog export. No backfill from present GPS or grid.
5. Validate in a separate branch/PR and release via approved wrapper only
   after full acceptance.

## Validation and rollback

- Synthetic geometry tests: 10 passed.
- Ruff and strict MyPy for new module: passed.
- No data migration, installed service, integration, or runtime activation.
- Rollback: revert this source-only change; existing production database and
  GPS consumers are unaffected.
- Change history: 2026-11-04 — initial fail-closed pure geometry primitive
  and synthetic regression tests added.

## Census source acquisition and artifact validation (2026-11-04)

- Authoritative source: U.S. Census Bureau, *2025 Cartographic Boundary
  File (SHP), County and Equivalent, 1:500,000*.
  https://www2.census.gov/geo/tiger/GENZ2025/shp/cb_2025_us_county_500k.zip
- Boundary reference date: January 1, 2025; Census publication 2026.
  This is a **generalized cartographic** boundary product, not a survey-grade
  legal boundary. The federal source is public domain; the data.gov catalog
  lists CC0. Attribute the Census Bureau when distributing.
- ZIP SHA-256:
  `aa976c00b181939755d0da757f4c7c2dc0103c3b3b4530fb2a91c2bb62fc777c`
  (11.2 MiB downloaded).
- Source SHP coordinate reference: NAD83 EPSG:4269, longitude/latitude
  degrees. Treating NAD83 degrees as WGS84 GPS degrees is an approximation;
  establish a suitable error buffer before using near borders.
- 3,235 county/county-equivalent records, 56 distinct state/territory codes;
  3,040 Polygon and 195 MultiPolygon records.
- Forge-only source and generated artifact:
  `/home/rt-remote/workspaces/rolling-thunder-county-data/`.
  Conversion tool `tools/county/build_county_sqlite.py` requires development
  `pyshp`; it converts to a read-only, R-tree-indexed SQLite artifact with
  zlib-compressed GeoJSON geometry, 10,067,968 bytes.
- Generated SQLite SHA-256:
  `4c1a2c1b094e660077e922944ddf961efec54997e5cdfb47aa18b0db7250a1b6`.
  **The generated artifact is not committed or installed on the Pi.**
- Validation: SQLite integrity OK, 3,235 county records and 56 state/
  territory codes; read-only indexed candidate lookup with the pure resolver
  correctly returned Warren (Waynesville), Franklin (Columbus), Montgomery
  (Dayton), Hamilton (Cincinnati), Los Angeles (Los Angeles), New York
  (Manhattan), Anchorage (Anchorage), San Juan (Puerto Rico), and unknown
  (London). These are representative fixtures, not complete nationwide or
  road-level acceptance.
- Commands on Forge (development only):
  `python tools/county/build_county_sqlite.py SOURCE.zip ARTIFACT.sqlite`
  then `PYTHONPATH=src python tools/county/validate_county_sqlite.py ARTIFACT.sqlite`.
  The builder refuses overwriting existing artifacts; use a fresh destination
  for reproducibility checks.
- **Remaining blockers**: validate all geometry topology/hole handling and
  border scenarios against an independent GIS engine; benchmark worst-case
  lookup and memory on Pi; define and test GPS uncertainty and frozen fix
  freshness; implement bounded read-only artifact loading and deployment
  packaging. No schema-22 migration or QSO/Wavelog integration yet.

### Independent topology/point validation

Using Forge's system GDAL/OGR library, `tools/county/compare_ogr.py`
independently read the original Census shapefile and checked all 3,235
source geometries with `IsValid()`: **zero invalid geometries**. It
compared 3,706 OGR-verified interior sample points (at least one
`PointOnSurface()` per county plus seeded random points) with the indexed
SQLite + pure Python resolver: **zero mismatches**. This does not
establish accuracy for near-border locations, antimeridian coordinates,
or the live GPS uncertainty model; those remain deployment blockers.
The comparison script uses development-only `osgeo`, not a Pi runtime
dependency.
