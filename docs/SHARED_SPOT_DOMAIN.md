# Shared Spot Domain

## Purpose

The shared spot domain provides provider-neutral foundations for unified POTA
and DX operating intelligence.

It defines immutable domain records, canonical snapshots, stable selection, and
staged-action primitives. Forge uses the domain for public POTA and bounded
DXSpider snapshots, and the Raspberry Pi reconstructs and durably retains the
same shared snapshot domain.

Checkpoint 7 migrates the running POTA presentation and the DX context to one
shared provider-neutral controller and presentation path backed only by the
already-published Pi Forge snapshot.

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
remain independently replaceable on Forge so one provider failure can retain
only that provider's previous records while another provider refresh succeeds.

The Pi client does not recanonicalize a malformed Forge response. It reconstructs
`SpotSnapshot` directly and rejects duplicate or noncanonical server ordering so
a corrupt or incomplete wire response cannot silently become a different local
snapshot.

## Durable Representation

### Forge service

Forge persists the same canonical `SpotRecord` fields used in memory, including:

- stable POTA or DX identity
- optional provider or QRZ operator name
- optional provider or QRZ grid
- integer frequency
- normalized and display modes
- UTC source timestamp
- bounded source metadata
- optional POTA metadata

Forge startup reconstruction revalidates identities, providers, ordering,
timestamps, duplicate collapse, and POTA metadata consistency before publishing
retained server state.

### Raspberry Pi shared cache

Pi application schema version 7 adds independent shared-cache tables in the
existing application database. They do not replace or alter contacts or the
legacy `pota_spot_cache` tables.

The Pi cache stores the accepted Forge revision, original Forge generation time,
Pi receive/success time, canonical shared records, ordered source metadata, and
accepted upstream provider health. Complete replacement is transactional.
Loading reconstructs and revalidates the immutable snapshot before publication.
A malformed cache is a local-storage failure rather than usable spot state.

The Pi follows persistence-before-publication ordering: fetch, validate, build
the complete candidate, persist transactionally, then atomically publish. A
failed write leaves both the previous durable snapshot and previous published
snapshot active.

Enriched fields remain non-action-critical after persistence. A retained QRZ
name or grid does not gain identity or tuning authority merely because it was
stored durably.

See `docs/PI_FORGE_CLIENT.md` for the complete Pi HTTP, SQLite, lifecycle,
offline, and diagnostics contract.

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

## Pi Retained and Live State

The optional Pi Forge service distinguishes:

- `empty`: no valid shared snapshot yet
- `cached`: durable state restored at process startup
- `live`: a live Forge response validated, persisted, and published
- `retained`: a live attempt failed while the previous snapshot remains usable

Published diagnostics preserve the original Forge `generated_at`, Pi
`received_at`, last live attempt, bounded failure category/text, revision, active
spot count, and upstream provider health. Restarting the Pi does not make old
data appear fresh.

Forge refresh-on-start is submitted to a background worker. `ApplicationRuntime`
and Tkinter only read already-published immutable state; they do not perform
Forge HTTP or shared-cache SQLite work on the caller/UI thread.

## Safety Boundary

The shared spot domain, Forge provider adapters, Forge-side QRZ enrichment, Pi
Forge client/cache/service/poller, and selection controller perform no:

- radio or hardware access
- CAT commands
- band, frequency, or mode changes
- receive tuning
- PTT, MOX, keying, tuner, power, or transmit control
- unattended radio action
- contact modification as part of shared-spot refresh
- Tkinter network or SQLite work

Forge server networking and persistence occur outside REST request handlers. Pi
Forge networking and shared-cache persistence occur only on the background
worker. The existing typed `ReceiveTuningService` remains the only receive-tuning
authority.

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
- typed Pi `GET /api/v1/spots` client with complete-response validation
- Pi application schema v7 durable combined shared snapshot cache
- transactional Pi persistence-before-publication behavior
- truthful cached/live/retained/error state and provider-health diagnostics
- background-only Pi Forge polling and runtime lifecycle composition

Checkpoint 7 now routes both POTA and DX through one shared panel backed by
`ApplicationRuntime.latest_forge_spot_state`.

When Forge is enabled, the Pi no longer composes the legacy direct-POTA poller.
The legacy implementation and `pota_spot_cache` tables remain available as a
non-destructive rollback/compatibility path when Forge is disabled.

The real checkpoint-7 bench validated:

- live POTA and DXSpider data through Forge
- WireGuard/CarLAN delivery to `anvilmobile`
- durable Pi shared-cache publication
- POTA and DX display on the installed dashboard
- encoder navigation and staging
- staged-action invalidation on context change
- no FT-891 frequency change when a spot is staged

Checkpoint 8 remains responsible for second-press receive tuning through
`ReceiveTuningService` and permanent Forge deployment/security hardening.

No current Forge, Pi shared-spot, shared-panel, or shared-domain component has
transmit authority.
