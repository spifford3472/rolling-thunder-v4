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
