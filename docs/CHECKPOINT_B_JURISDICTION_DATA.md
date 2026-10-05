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
the runtime JSON artifact. It records the exact input ZIP SHA-256, generation
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

Artifact format version: 1.

The JSON document contains format_version, source provenance metadata, and
states containing canonical state codes and Polygon/MultiPolygon rings as
[longitude, latitude].

Runtime loading is performed once through
rolling_thunder.local_jurisdiction.load_state_boundaries. QSO lookup is pure
in-process computation; no subprocess or network dependency is used.

The generated national artifact is not yet committed at this stage. Before
runtime composition is enabled, generate it from the exact Census ZIP, review
its reported source/artifact SHA-256 and state count, commit it under the
package data directory, and run resolver performance/coverage tests.

## Regeneration

From the isolated Checkpoint B worktree after installing development
dependencies:

python tools/generate_us_state_jurisdiction.py \
  /path/to/tl_2025_us_state.zip \
  src/rolling_thunder/data/us_state_jurisdiction_v1.json

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
