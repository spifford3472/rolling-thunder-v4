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

## Indexed runtime reader checkpoint (2026-11-04)

`src/rolling_thunder/offline_county_store.py` provides a read-only
`IndexedCountyStore` that queries the SQLite R-tree for nearby candidates,
loads only those compressed county geometries, and applies the conservative
polygon resolver. It does not write to the county artifact, use the network,
or acquire mutable GPS state. A candidate cap of 16 fails closed for
unexpectedly crowded/corrupt spatial queries; missing/corrupt artifacts
return unknown. The caller supplies a frozen `GPSPosition`, an explicit
timestamp, and an age threshold; missing accuracy, invalid fix, stale or
future-dated fixes return unknown.

The default margin includes reported horizontal uncertainty and 20 meters
for datum/cartographic differences. This is a preliminary conservative
policy, **not an assurance** that the 1:500,000 cartographic boundaries are
accurate within 20 meters. Additional real road/county-line checks and
a measured boundary uncertainty policy are mandatory before enabling
automatic QSO county logging.

Synthetic SQLite tests: 2 passed, including boundary, stale GPS, missing
accuracy, missing file, and candidate overflow. On Forge, example indexed
lookup times: Waynesville 0.64 ms, Columbus 0.47 ms, Anchorage 10.42 ms,
San Juan 0.47 ms; these are illustrative single-run Forge measurements,
**not** Pi worst-case latency or performance acceptance. Strict MyPy
and Ruff pass. The store is **not connected to the contact logging service,
not installed on anvilmobile, and not production enabled**.

Rollback: remove the source-only reader; no migrations or service changes.

## Schema 22 staging (not activation)

Schema 22 adds a nullable `contacts.my_county` column. The Contact model
now accepts a normalized county name only alongside frozen local state and
coordinates; Wavelog's ADIF encoder emits `MY_CNTY` when the Contact has
both state and county. Existing contacts remain null; **no historical
backfill**. This is a staged interface only: the contact repository does
not yet persist/read the new field, and the frozen FT8 context does not
yet carry a trusted fix timestamp/accuracy. Consequently no production
QSO automatically receives a county yet. Do not merge or deploy until
the repository, frozen GPS metadata, manual and FT8 paths, Forge sync,
and migration rollback tests are complete.

## Repository persistence checkpoint

All repository SQL paths now include `my_county`: insertion, retrieval,
updates, list projections, JSON recovery, and idempotent payload comparison.
The field remains optional and existing rows remain null. The new
`tests/test_county_persistence.py` proves a real SQLite round trip and
ADIF `MY_CNTY` emission without remote-party `CNTY` contamination.
Targeted persistence/FT8 tests passed (83).

**Still not production-ready**: the QSO authorization context currently
freezes coordinates and jurisdiction but not a trustworthy horizontal
accuracy/timestamp. It would be unsafe to infer county from coordinates
alone. Extend that capture path first, validate Forge sync contract
compatibility, and benchmark the Pi before activating the lookup.

## Merge-review candidate: source, runtime and safety

The complete 2025 Census county-equivalent SQLite artifact is checked into
`src/rolling_thunder/data/us-counties-2025-500k.sqlite` (9.6 MiB).
SHA256: `4c1a2c1b094e660077e922944ddf961efec54997e5cdfb47aa18b0db7250a1b6`.
The runtime discovers it relative to the installed Python source, rather
than assuming a mutable home directory or Forge-only build path.

FT8 authorization now freezes GPS fix timestamp and uncertainty alongside
the existing coordinates. The completed-contact logger uses only this
snapshot, never a new position. A fix must be <=10 seconds old at QSO
authorization, non-future-dated, have an uncertainty estimate, and agree
with the independently frozen jurisdiction state; otherwise `my_county`
remains null. No historical contacts are backfilled. The source serial
NMEA GGA adapter derives a **conservative estimate**, not a measured
accuracy, from HDOP: max(100 m, HDOP × 30 m). Missing or malformed HDOP
is unknown and prevents county assignment. The geometric lookup adds a
further 20 m allowance; cartographic source boundaries can be displaced
by more than this. County-edge field acceptance is required.

The lookup currently occurs in the completed-QSO logging call, and may
take milliseconds on Forge (including >10 ms for complex Alaska shapes).
Before production merge, confirm this does not violate the terminal FT8
timing budget on the Pi; if it does, move county enrichment to a bounded
background worker with a durable handoff, preserving the frozen snapshot.

Forge receiver parses the same additive `Contact` JSON field and its
ADIF encoder now exports `MY_CNTY`. **Receiver-first rollout** is
required because an older Forge process could silently discard the new
optional field and lose county metadata. The local schema 21→22
migration is additive and transactional; restore the pre-upgrade
SQLite backup on rollback, and do not run older code against schema 22.
No new network ports, firewall rules, or OPNsense changes are needed.

### Merge and deployment gates

1. Verify clean full-suite tests, Ruff, MyPy, database integrity and checksum.
2. Review live GPS GGA HDOP availability and county-border behavior on a
   parked anvilmobile. Do not test while driving.
3. Verify source package asset is installed at the expected path on both
   Forge and Pi; read-only benchmark the Pi, including complex geometry.
4. Back up Pi QSO SQLite with SQLite online backup and record current
   production SHA; verify restore and rollback steps.
5. Upgrade compatible Forge contact-sync receiver before Pi sender.
6. Merge only after review/CI, deploy with the guarded deployment process,
   verify schema 22, and test one real completed FT8 QSO and Wavelog ADIF.
7. If a gate fails, leave production unchanged; do not synthesize county.

The prior notes referring to the reader as 'not connected' describe
earlier checkpoints; the later integration above supersedes them.

## Manual contact path

The dashboard/manual `ContactLoggingService.commit` now shares the same
offline county store. It resolves only a valid GPS snapshot matching the
already frozen contact metadata and independently resolved local state;
the same 10-second freshness, known uncertainty and boundary rejection
rules apply. The manual path is separately covered by a real Census
fixture test for a fresh Warren County contact and stale-fix rejection.
This path does not query GPS a second time.

### Review note on GPS uncertainty

`GPSPosition.accuracy_m` is populated from NMEA GGA HDOP only as a
conservative **engineering estimate**, not a receiver-certified
accuracy radius. It is not a statistical guarantee. The 2025 Census
1:500,000 source is cartographically generalized. A near-county-line
position can still be wrong even with a 100-meter margin. Do not
represent the resulting county as authoritative without field checks.
