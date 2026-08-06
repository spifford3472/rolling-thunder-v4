# Shared Spot Domain

## Purpose

The shared spot domain provides provider-neutral foundations for unified POTA
and DX operating intelligence.

It defines immutable domain records, canonical snapshots, stable selection, and
staged-action primitives. Forge now uses the domain for public POTA and bounded
DXSpider snapshots. The running Raspberry Pi dashboard has not yet migrated to
the Forge client or unified panel.

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

Forge-side QRZ enrichment may fill missing operator name and grid values before
a snapshot is persisted. Provider-supplied values take precedence. Enrichment
never changes identity, callsign, frequency, mode, source timestamp, source
metadata, or POTA park metadata.

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

Identity never depends on:

- row position
- provider arrival order
- Python object identity
- operator name
- Maidenhead grid
- QRZ enrichment state
- provider comment text
- locale-sensitive sorting

A QRZ name or grid appearing, changing, expiring from cache, or being unavailable
cannot change a stable selection identity.

## Provider Semantics

### POTA records

POTA records use park reference plus integer frequency as identity and require
matching `PotaSpotMetadata`. Optional park name, location code, and coordinate
pair remain presentation and operating-intelligence data rather than selection
identity.

### DX records

DX records use normalized callsign plus integer frequency as identity and cannot
contain POTA metadata.

The DXSpider adapter reconstructs a UTC source timestamp from the provider's
`HHMMZ` value, converts decimal kilohertz exactly to integer hertz, and retains
bounded spotter, comment, and mode-provenance metadata.

DXSpider comments do not provide one guaranteed normalized radio mode field.
The Forge parser therefore applies deterministic explicit-token and sub-band
fallback rules. The resulting normalized mode is part of action-critical
staging. The display mode and provenance metadata explain the provider token or
fallback used.

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

A complete Forge snapshot may contain both POTA and DX records. Provider slices
remain independently replaceable so one provider failure can retain only that
provider's previous records while another provider refresh succeeds.

## Durable Representation

Forge persists the same canonical `SpotRecord` fields used in memory, including:

- stable POTA or DX identity
- optional provider or QRZ operator name
- optional provider or QRZ grid
- integer frequency
- normalized and display modes
- UTC source timestamp
- bounded source metadata
- optional POTA metadata

Startup reconstruction revalidates identities, providers, ordering, timestamps,
duplicate collapse, and POTA metadata consistency before publishing retained
state.

Enriched fields remain non-action-critical after persistence. A retained QRZ
name or grid does not gain identity or tuning authority merely because it was
stored durably.

## Stable Selection

Selection is stored as a stable identity rather than a row index.

When a complete snapshot is replaced:

- selection remains when the identity is still present
- the current row index is resolved from the replacement snapshot
- selection clears when the identity disappears
- staging also clears when the selected identity disappears
- no neighboring row is selected as a fallback

Combined POTA and DX ordering therefore cannot redirect a selection merely
because records from the other provider were inserted, removed, or refreshed.

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
or radio mode changes. Non-actionable metadata may refresh without invalidating
the staged action, including:

- operator name
- Maidenhead grid
- park name
- location code
- coordinates
- provider comment
- spotter callsign
- mode-provenance metadata

Staging also clears on:

- selection change
- explicit cancellation
- context invalidation
- radio invalidation
- later-stage failure

## Safety Boundary

The shared spot domain, Forge provider adapters, QRZ enrichment, and selection
controller perform no:

- Tkinter work
- radio or hardware access
- CAT commands
- band, frequency, or mode changes
- PTT, MOX, keying, tuner, power, or transmit control
- Pi contact logging
- modification of the Pi contact database

Forge networking and SQLite work occur outside request handlers and outside the
Pi application. The existing typed `ReceiveTuningService` remains the only
receive-tuning authority.

## Current Integration Status

Completed foundations now include:

- shared immutable POTA and DX records
- stable provider-specific identities
- deterministic canonical combined snapshots
- stable selection and staged-action primitives
- Forge public POTA ingestion
- Forge bounded DXSpider snapshot ingestion
- Forge best-effort QRZ name and grid enrichment
- Forge transactional combined persistence and read-only REST

The running POTA dashboard remains intentionally unchanged. The following remain
separate checkpoints:

- Pi Forge HTTP client
- Pi durable shared-spot snapshots
- migration of the POTA panel
- unified POTA and DX presentation
- operator-confirmed two-press receive tuning

No current Forge or shared-domain component has radio or transmit authority.
