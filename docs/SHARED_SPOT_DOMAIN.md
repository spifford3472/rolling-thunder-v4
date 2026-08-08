# Shared Spot Domain

## Purpose

The shared spot domain provides the provider-neutral foundation for unified POTA
and DX operating intelligence.

It defines immutable domain records, canonical snapshots, stable selection,
provider-specific filters, exact staged receive actions, and the two-press
operator-confirmation contract. Forge uses the same domain for public POTA and
bounded DXSpider snapshots, while the Raspberry Pi reconstructs and durably
retains those snapshots for offline-first presentation.

Checkpoint 8 completes the shared operator path for both POTA and DX. The first
activation stages only; the second activation of the same still-valid target may
submit receive tuning through the existing typed `ReceiveTuningService`.

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
never changes identity, callsign, frequency, normalized mode, source timestamp,
source metadata, or POTA park metadata.

## Stable Identities

POTA identity:

```text
pota:<PARK_REFERENCE>:<INTEGER_FREQUENCY_HZ>
```

DX identity:

```text
dx:<NORMALIZED_CALLSIGN>:<INTEGER_FREQUENCY_HZ>
```

Identity never depends on row position, provider arrival order, Python object
identity, QRZ enrichment, operator name, grid, provider comment, or locale
sorting.

Selection is therefore preserved across refreshes only when the same stable
identity remains present.

## Provider Semantics

### POTA records

POTA records use park reference plus integer frequency as identity and require
matching `PotaSpotMetadata`. Park name, location code, coordinates, operator
name, grid, and source comment remain metadata rather than identity.

### DX records

DX records use normalized callsign plus integer frequency as identity and cannot
contain POTA metadata.

The DXSpider adapter reconstructs UTC source time from the provider `HHMMZ`
value, converts decimal kilohertz exactly to integer hertz, and retains bounded
spotter, comment, and mode-provenance metadata.

DX mode normalization uses deterministic explicit-token and sub-band fallback
rules. The resulting normalized `RadioMode` is action-critical. Display mode and
mode provenance remain presentation/source metadata.

## Canonical Snapshots

`SpotSnapshot` collapses duplicate identities and orders records
canonically. Ordering is deterministic by amateur-band rank, integer frequency,
provider rank, serialized identity, callsign, normalized radio mode, and display
mode.

A complete Forge snapshot may contain both POTA and DX records. Forge maintains
provider slices independently so a failed provider refresh can retain only that
provider's prior slice while another provider succeeds.

The Pi does not silently repair a malformed Forge response into a different
snapshot. The typed client reconstructs and validates the received canonical
shape and rejects malformed, duplicate, inconsistent, or noncanonical data.

## Durable Representation

### Forge

Forge persists canonical POTA/DX records and provider health transactionally in
a dedicated Forge SQLite database. Startup reconstruction revalidates identities,
providers, ordering, timestamps, duplicate collapse, and POTA metadata before
publishing retained state.

### Raspberry Pi

Pi application schema version 7 stores the accepted Forge revision, original
Forge generation time, Pi receive/success time, canonical records, ordered source
metadata, and accepted upstream provider health in independent shared-cache
tables.

Replacement is transactional. The Pi follows:

```text
fetch complete response
    -> validate complete response
    -> build complete candidate
    -> persist candidate transactionally
    -> atomically publish immutable state
```

A failed write leaves the previous durable and published snapshots active.

See `docs/PI_FORGE_CLIENT.md` for the HTTP, SQLite, lifecycle, and failure
contract.

## Provider-Specific Filtering

POTA and DX use the same shared panel/controller and the same supported mobile HF
band cycle:

- 80 m
- 40 m
- 20 m
- 17 m
- 15 m
- 12 m
- 10 m

Both providers use the same mode-group cycle:

- SSB
- CW
- FT4
- FT8
- DATA
- ALL

POTA additionally applies its configured maximum spot age, currently 15 minutes
for the mobile panel. DX does not inherit the POTA age filter.

Filter state is provider-specific. Changing POTA filters does not mutate DX
filters and vice versa.

On POTA or DX context activation, the band filter defaults to the current FT-891
band when the current frequency resolves to a supported shared-panel band.
Otherwise the safe fallback is 20 meters.

POTA starts from SSB mode filtering. DX starts from ALL mode filtering.

Every band or mode filter change cancels staging. If filtering removes the
selected identity, selection clears; no neighboring-row fallback is permitted.

## Stable Selection

Selection is stored by `SpotIdentity`, never by row number.

When a snapshot or filtered view is replaced:

- selection remains only if the selected identity remains visible
- the current row position is resolved from the replacement view
- selection clears if the identity disappears
- staging clears if the selected identity disappears
- no neighboring identity becomes selected automatically

Rotating the encoder or otherwise changing the row selection also clears any
staged action.

## Exact Staged Actions

A `StagedSpotAction` captures the exact action-critical values present on the
first activation:

- stable identity
- callsign
- frequency
- normalized radio mode

This prevents a refresh under the same identity from silently changing a later
confirmed action.

Staging clears when the staged target's callsign, frequency, or normalized mode
changes. Non-action-critical metadata may refresh without changing staging,
including operator name, grid, park name, location code, coordinates, provider
comment, spotter callsign, and mode-provenance metadata.

Staging also clears on:

- row selection change
- provider/context change
- POTA or DX band-filter change
- POTA or DX mode-filter change
- identity disappearance
- explicit Back/Cancel
- radio invalidation
- accepted second-press tune submission

## Two-Press Operator Contract

Both POTA and DX use one two-press contract:

```text
navigate / rotate
    -> selection changes
    -> staging clears

first activation
    -> stage exact identity/callsign/frequency/mode
    -> no CAT
    -> no radio change

second activation of the same still-valid target
    -> submit exact staged action to background tuning
    -> clear staging after submission is accepted
    -> ReceiveTuningService performs ordered receive-only tuning
```

There is no third confirmation step in the checkpoint-8 shared POTA/DX path.

If no still-valid staged action exists, an activation stages rather than tunes.
If the background tuning boundary is unavailable or already busy, the staged
action is not silently redirected to another record.

## Radio-State Gate

Before either staging or second-press submission, the active-panel command
controller synchronizes the current immutable radio state.

The radio is usable for shared-spot action only when:

- connection state is `CONNECTED`
- frequency is known
- mode is known
- the radio is not transmitting

If those conditions are not met, any staged action is invalidated and no tune is
submitted.

`ReceiveTuningService` independently rejects ordered receive tuning while the
radio reports `transmitting=True`. This keeps the radio-safety rule below the UI
and shared-panel layers as well as at the operator-command boundary.

## Sole Receive-Tuning Authority

Shared POTA/DX execution follows:

```text
physical or keyboard activation
    -> OperatorCommandController
    -> SharedSpotActivePanelCommandController
    -> SharedSpotTuneController
    -> ReceiveTuningService
    -> typed Radio boundary
```

The shared panel, Tkinter code, physical-control adapter, Forge client, and Forge
service issue no CAT commands.

`ReceiveTuningService` remains the sole receive-tuning authority and preserves
band-before-frequency ordering and read-back verification for the FT-891.

No provider-specific POTA or DX tune executor is introduced by checkpoint 8.

## Background Tuning and Presentation

`SharedSpotTuneController` submits the exact staged frequency/mode on a background
thread so blocking CAT work does not run in Tkinter.

Published tune states are:

- idle
- tuning
- succeeded
- failed

The UI refresh path observes immutable tune status and publishes operator status
through `StatusMessageService`.

Current status behavior is:

- tuning message: normal priority status while tuning
- success message: green/success presentation for 5 seconds
- failure message: error presentation for 8 seconds
- verified cross-band result: amber ATAS-120 reminder for 10 seconds

The ATAS warning text is:

```text
BAND CHANGED TO <BAND> METERS — RETUNE ATAS-120
```

The warning states only that a verified receive band change occurred. Rolling
Thunder does not tune or verify the ATAS-120 and does not claim the antenna is
safe to transmit.

## Back / Cancel Behavior

Within a shared POTA/DX context, Back operates on panel state only:

1. if an action is staged, cancel staging
2. otherwise, if a row is selected, clear selection
3. otherwise, return control to the normal surrounding navigation behavior

Back does not create a radio action and does not bypass the two-press contract.

## Pi Retained and Live State

The Pi Forge service distinguishes:

- `empty`: no valid shared snapshot yet
- `cached`: durable state restored at startup
- `live`: a live Forge response validated, persisted, and published
- `retained`: a live attempt failed while the previous snapshot remains usable

Diagnostics preserve original Forge generation time, Pi receive time, last live
attempt, bounded error category/text, revision, active spot count, and upstream
provider health. Restarting the Pi does not make old data appear fresh.

Forge polling is background-only. `ApplicationRuntime` and Tkinter read only
already-published immutable state.

## Forge Authority and Offline Behavior

When Forge is enabled, the Pi does not compose the legacy direct public-POTA
poller. Forge is authoritative for live POTA and DX ingestion.

The legacy POTA implementation and `pota_spot_cache` tables remain intact as a
non-destructive rollback/compatibility path when Forge is disabled.

Forge, WireGuard, cellular, provider, or public-internet failure does not block
local SQLite contact logging. The Pi retains its last valid shared snapshot when
one exists.

Production Forge deployment is documented in `docs/FORGE_DEPLOYMENT.md`.

## Safety Boundary

The shared spot domain, Forge provider adapters, Forge-side QRZ enrichment, Pi
Forge client/cache/service/poller, selection controller, and UI presentation
perform no:

- PTT or MOX
- CW or voice keying
- tuner control
- power control
- unattended transmit
- voice-originated receive tuning
- direct CAT from Tkinter or physical-control parsing
- contact modification as part of spot refresh

Voice capture remains a callsign/input workflow and cannot invoke the shared
receive-tuning path.

## Checkpoint-8 Integration Status

Checkpoint 8 now includes:

- DX band and mode filtering through the shared controller
- independent POTA/DX filter state
- current-radio-band activation default with 20-meter fallback
- exact two-press POTA/DX staging and receive-tune submission
- action-critical staging invalidation
- radio-state invalidation before staging/tuning
- background shared receive tuning
- shared tuning/success/failure presentation
- timed cross-band ATAS-120 warning
- production Forge systemd deployment under the dedicated `rollingthunder`
  service account
- production Forge POTA and DXSpider live-health acceptance

The remaining checkpoint-8 acceptance work is the final real FT-891 shared POTA
and DX bench: same-band and cross-band two-press operation, first-press no-change
verification, filter/context invalidation, ATAS warning behavior, retained Forge
behavior, and local logging continuity.

No shared-spot component has transmit authority.
