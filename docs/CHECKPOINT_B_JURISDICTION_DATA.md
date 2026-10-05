# Checkpoint B jurisdiction data

Checkpoint B derives one immutable local U.S. state, CQ zone, and ITU zone from
the same accepted latitude/longitude pair already frozen for a QSO. Runtime
resolution is offline and deterministic. No Census, reverse-geocoding, CQ, ARRL,
or other network request occurs at QSO time.

## Supported scope

The generated state artifact contains the 50 U.S. states plus the District of
Columbia. Census state-equivalent territories are intentionally excluded from
the initial supported runtime scope. A coordinate outside the supported
polygons resolves to no jurisdiction; the logger still records the QSO and its
accepted coordinate/grid data.

## State boundary source

Authoritative source:

- Agency: U.S. Census Bureau, Geography Division.
- Dataset: 2025 TIGER/Line State and Equivalent Entity National shapefile.
- Source URL: https://www2.census.gov/geo/tiger/TIGER2025/STATE/tl_2025_us_state.zip
- Census vintage: 2025 TIGER/Line release.
- Runtime code uses STUSPS as the canonical two-character subdivision code.

tools/generate_us_state_jurisdiction.py accepts the pinned ZIP and produces
the runtime ZIP artifact. It records the exact input ZIP SHA-256, generation
timestamp, coordinate precision, source URL, and supported scope in the
artifact. Acceptance must also record the generated artifact SHA-256.

The generator retains Polygon/MultiPolygon rings, including interior holes,
and rounds source coordinates to six decimal degrees. It does not simplify
geometry, snap borders, infer nearest states, or create replacement boundaries.

## CQ zone source and rules

CQ zones are derived separately from state geometry using the published
CQ World Wide WAZ Zone Definitions:
https://www.cqww.com/cq_waz_list.htm

The authoritative definitions make the supported U.S. state assignments
deterministic. The runtime rule table is intentionally small and independent
of the Census polygon data. Alaska is CQ zone 1, Hawaii CQ zone 31, contiguous
U.S. states/DC use CQ zones 3, 4, or 5 according to the published WAZ
definitions.

No Maidenhead-grid or longitude approximation is used for CQ zone selection.

## ITU zone source and rules

ITU zones are derived independently using the U.S. zone-border rules published
for the IARU HF World Championship by ARRL:
https://www.arrl.org/iaru-hf-world-championship

The rules explicitly identify:

- ITU 6/7 split portions of Arizona, Montana, and Utah at 110 degrees west.
- ITU 7/8 split portions of Arkansas, Illinois, Louisiana, Michigan, Missouri,
  Mississippi, Tennessee, and Wisconsin at 90 degrees west.
- Alaska ITU 1/2 split at 141 degrees west.
- Hawaii ITU zone 61.

Whole-state assignments are represented directly where the published rule is
whole-state. Split-state assignment uses the frozen QSO longitude, not the
state code alone.

## Exact-boundary policy

The resolver fails closed to unresolved when a coordinate is mathematically on
a Census polygon ring. It never chooses a nearest state.

For the explicit ITU meridians, the source rules say east/west of the dividing
longitude. An exact longitude of -110, -90, or -141 degrees is therefore
treated as unresolved rather than assigning a side not explicitly owned by the
text.

Polygon holes remain outside the state. MultiPolygon islands/components are
supported. A point contained by zero supported states or ambiguously contained
by more than one state resolves to no jurisdiction.

Invalid, non-finite, or out-of-range coordinates are rejected by the resolver.

## Runtime artifact contract

Artifact format version: 2.

The ZIP archive contains a compact index.json plus one compressed state JSON member per supported state/DC. The index stores format_version, source provenance, canonical state code, state bounding box, and member name. State members retain the exact generated Polygon/MultiPolygon rings as [longitude, latitude].

Runtime startup loads only index.json through LocalJurisdictionResolver.from_artifact. QSO lookup first filters candidate states by bounding box, then lazily decodes only the needed state geometry and keeps a small three-state LRU cache. Polygon bounding boxes further avoid scanning irrelevant components. QSO lookup remains pure in-process computation; no subprocess or network dependency is used.

The generated national artifact is not yet committed at this stage. Before
runtime composition is enabled, generate it from the exact Census ZIP, review
its reported source/artifact SHA-256 and state count, commit it under the
package data directory, and run resolver performance/coverage tests.

## Regeneration

From the isolated Checkpoint B worktree after installing development
dependencies:

python tools/generate_us_state_jurisdiction.py \
  /path/to/tl_2025_us_state.zip \
  src/rolling_thunder/data/us_state_jurisdiction_v2.zip

Do not substitute another TIGER vintage without explicit review. A regenerated
artifact is a source-data change and requires boundary regression tests plus a
new recorded checksum.

## Performance acceptance

Before production cutover measure on anvilmobile:

- generated artifact byte size;
- resolver initialization/loading time;
- repeated coordinate lookup time;
- practical RSS/memory impact;
- application startup impact.

If the full unsimplified artifact is too expensive on the Pi, change the
runtime representation only after measurements and review. Do not silently
simplify or approximate authoritative boundaries to meet a guessed target.


## Measured rejected v1 representation

The first exact-geometry representation stored all 51 jurisdictions in one
22,222,003-byte JSON document. On anvilmobile it produced correct answers but
failed the performance gate:

- startup load: 6.903058 seconds;
- maximum RSS after load: 242,480 KiB (236.80 MiB);
- RSS growth during load: 228,712 KiB;
- repeated Waynesville lookup median: 1029.695 ms.

That v1 runtime representation was rejected and must not be committed as the
production artifact. Format v2 exists specifically to preserve the same source
geometry while avoiding whole-country startup expansion and whole-country
lookup scans.


## Accepted v2 benchmark on anvilmobile

Generated artifact provenance:

- source ZIP SHA-256: `59a220888a8d9be8117c4fcd38f542bd02d81abf0d198c78113595ad540dd957`;
- v2 artifact SHA-256: `aceb7cabf4b3c607fac83be5032241977f72ca2ef39628db04eb95770d64a935`;
- artifact size: 6,303,603 bytes;
- archive members: 52 total (index.json plus 51 state/DC members);
- generated at: 2026-10-05T01:40:11Z.

Measured on anvilmobile:

- index startup load: 0.003525 seconds;
- index RSS growth: 0 KiB;
- peak RSS after mixed-state resolution: 37,220 KiB (36.35 MiB);
- first Ohio lookup: 169.914 ms;
- first Indiana lookup: 157.023 ms;
- worst sampled cold lookup (Texas): 610.470 ms;
- repeated Waynesville lookup median: 37.018 ms;
- repeated Waynesville lookup mean: 41.343 ms;
- 25 targeted resolver tests passed.

The v2 indexed/lazy-loading representation is accepted for continued Checkpoint B integration. Cold-state decode cost is bounded to first use of a state member; normal local operation benefits from the three-state cache.


## Gate 3 real schema-16 migration acceptance

Validated on anvilmobile against a fresh SQLite online-backup copy of the live
production database. Production itself was opened read-only for verification and
was not migrated.

Baseline evidence:

- production schema version before test: 16;
- production contact count: 16;
- baseline contact-column count: 18;
- SQLite integrity_check: ok;
- foreign-key errors: 0;
- Checkpoint A contact `35507df2-179b-44ec-bd05-59b9746d2e82` present;
- baseline SHA-256: `37c46f3a48e787ea1cac5a23d07c2b58ab92b8be9bfe65fdd6bd4d0d9b9f2c50`.

Migration acceptance:

- copied database migrated from schema 16 to 17;
- contact count remained 16;
- all pre-existing contact columns/rows were unchanged;
- `my_state`, `my_cq_zone`, and `my_itu_zone` were added and remained NULL for every historical contact;
- Checkpoint A coordinates remained `EM79xm / 39.52442 / -84.06249` and its new jurisdiction fields remained NULL;
- migrated database integrity_check remained ok;
- migrated database foreign-key errors remained 0;
- post-migration verification SHA-256: `4549e27f372b81fc7a71f87c74536536d4c616e67d00c0b5fba93f1bb5b9e8c4`;
- repository model successfully read all 16 migrated contacts;
- production was rechecked after the test and remained schema 16 with no Checkpoint B columns.

This satisfies the Checkpoint B requirement that schema 17 is additive and does
not backfill or reinterpret historical contacts.
