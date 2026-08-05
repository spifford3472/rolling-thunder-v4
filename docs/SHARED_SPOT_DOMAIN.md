# Shared Spot Domain

## Purpose

The shared spot domain provides provider-neutral foundations for future unified
POTA and DX operating intelligence.

This checkpoint adds only immutable domain records, canonical snapshots, stable
selection, and staged-action primitives. It does not connect to Forge, public
spot providers, the radio, or the running dashboard.

## Domain Records

`SpotRecord` contains:

- provider and stable identity
- normalized callsign
- optional operator name
- optional Maidenhead grid
- typed integer-hertz frequency
- normalized radio mode
- provider display mode
- UTC source timestamp
- deterministic provider/source metadata
- optional POTA park metadata

Unknown operator names and grids remain typed `None`. Presentation code converts
unknown optional values to `<UNKNOWN>` only at the presentation boundary.

## Stable Identities

POTA identity:

```text
pota:<PARK_REFERENCE>:<INTEGER_FREQUENCY_HZ>
```

DX identity:

```text
dx:<NORMALIZED_CALLSIGN>:<INTEGER_FREQUENCY_HZ>
```

POTA activator callsign is deliberately not part of POTA identity. Reports for
the same park and integer frequency therefore belong to one duplicate group.

Identity never depends on row position, provider arrival order, Python object
identity, operator name, enrichment data, or locale-sensitive sorting.

## Canonical Snapshots

`SpotSnapshot` collapses duplicate identities and orders records by:

1. explicit amateur-band rank
2. integer frequency
3. explicit provider rank
4. serialized stable identity
5. normalized callsign
6. normalized radio mode
7. normalized provider display mode

Records sharing a stable identity are collapsed deterministically. The newest
UTC source timestamp wins; normalized record content provides stable equal-time
tie-breakers. The result is independent of provider input order.

Frequencies outside the supported amateur-band table sort after known bands.
The implementation does not use enum declaration order as an implicit band
ranking.

## Stable Selection

Selection is stored as a stable identity rather than a row index.

When a complete snapshot is replaced:

- selection remains when the identity is still present
- the current row index is resolved from the replacement snapshot
- selection clears when the identity disappears
- staging also clears when the selected identity disappears
- no neighboring row is selected as a fallback

## Staged Actions

A staged action captures the exact action-critical values present when the
operator performs the first action:

- stable identity
- callsign
- frequency
- radio mode

This prevents a refreshed record under the same stable identity from silently
changing the later confirmed action.

Staging clears when the selected record disappears or its callsign, frequency,
or radio mode changes. Non-actionable metadata such as operator name, grid, park
name, or source metadata may refresh without invalidating the staged action.

Staging also clears on:

- selection change
- explicit cancellation
- context invalidation
- radio invalidation
- later-stage failure

## Safety Boundary

The shared spot domain and selection controller perform no:

- Tkinter work
- network or Forge access
- SQLite or filesystem access
- background or blocking work
- CAT commands
- radio or hardware access
- PTT, MOX, keying, tuner, power, or transmit control

The existing typed `ReceiveTuningService` remains the only receive-tuning
authority.

## Current Integration Status

The running POTA dashboard is intentionally unchanged. It continues to use its
existing selection, tune-intent request, confirmation, and execution workflow.

Forge aggregation, provider adapters, durable Pi snapshots, shared POTA/DX
presentation, and the later two-press workflow remain separate checkpoints.
