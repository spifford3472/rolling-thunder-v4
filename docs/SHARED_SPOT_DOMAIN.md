# Shared Spot Domain

## Purpose

The shared spot domain provides the provider-neutral foundation for unified POTA
and DX operating intelligence.

It defines immutable domain records, canonical snapshots, stable selection,
provider-specific filters, and exact per-activation receive actions. Forge uses
the same domain for public POTA and bounded DXSpider snapshots, while the
Raspberry Pi reconstructs and durably retains those snapshots for offline-first
presentation.

The current shared operator path for both POTA and DX uses one activation on the
current stable selection. That activation snapshots the exact receive target and
submits it through the existing typed `ReceiveTuningService` path.

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

`SpotSnapshot` collapses duplicate identities and orders records canonically.
Ordering is deterministic by amateur-band rank, integer frequency, provider
rank, serialized identity, callsign, normalized radio mode, and display mode.

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

POTA and DX start from ALL filtering, where ALL is intentionally restricted to
Phone/SSB/CW. The only selectable mode filters are ALL, SSB/PHONE, and CW.

Every band or mode filter change cancels staging. If filtering removes the
selected identity, selection clears; no neighboring-row fallback is permitted.

## Daily Worked Markers

### POTA

The mobile POTA panel maintains a local worked marker for a successfully logged
active POTA station. A marker is created only after the contact has been durably
written to the local contact database.

Worked identity is intentionally independent of the POTA spot identity. It is
the operator-facing tuple:

```text
normalized callsign + displayed POTA mode + amateur band
```

Frequency and park reference are not part of the worked key. Therefore a later
spot for the same callsign on the same displayed mode and band remains marked
worked even if its exact spot frequency or park changes. A different callsign,
displayed mode, or band is a fresh combination and is not marked worked.

The displayed POTA mode is preserved from the provider value (for example
`SSB`, `FT8`, `FT4`, or `RTTY`) rather than collapsing all digital modes
to the radio-domain `DATA` value.

Worked markers are persisted in the Pi SQLite database so a dashboard restart
during the same UTC day retains them. The panel uses an in-memory set for
refresh-time lookup, so Tkinter performs no SQLite reads. At the first
presentation lookup after the UTC date changes, the in-memory set is cleared;
prior-day markers are not displayed as worked.

Presentation behavior is POTA-only:

- a worked card uses the light-blue worked background
- the card includes the text `WORKED`
- if a worked card is selected, the worked background remains and the existing
  selected border continues to indicate selection
- DX rows never inherit POTA worked state

### DX

The mobile DX panel maintains a separate local worked marker after a DX contact
has been durably written to the local contact database. Its operator-facing key
is intentionally simpler than POTA:

```text
normalized callsign + amateur band
```

Exact frequency and displayed mode are not part of the DX key. Every current DX
spot for that callsign on the same amateur band therefore shows worked, while a
spot on another band remains unworked. DX markers are persisted in the Pi SQLite
database for same-day restart recovery and expire from presentation at the next
UTC date rollover.

DX uses the same light-blue worked background and visible `WORKED` card label as
POTA. The DX tracker remains separate so it cannot change POTA's
callsign/band/display-mode semantics. Failed or discarded contact workflows do
not create either kind of marker.

## Stable Selection

Selection is stored by `SpotIdentity`, never by row number.

When a snapshot or filtered view is replaced:

- selection remains only if the selected identity remains visible
- the current row position is resolved from the replacement view
- selection clears if the identity disappears
- selection clears if the selected identity disappears
- no neighboring identity becomes selected automatically

Rotating the encoder or otherwise changing the row selection also clears any
staged action. In the dashboard station-popup lifecycle, an accepted POTA/DX row
move also suppresses callsign-info presentation; highlighting subsequent rows does
not perform lookup work. This presentation effect does not preload a callsign or
create a receive action.

## Exact Receive Actions

A `StagedSpotAction` remains the immutable compatibility value used by the
background tuning boundary, but it is no longer stored as operator confirmation
state. On a single activation, the controller snapshots the currently selected
record's stable identity, callsign, frequency, and normalized radio mode and
immediately offers that exact value to the background tuner.

The selected identity is still stable across refreshes. If a spot disappears or
changes identity before activation, there is no selected action to submit; the
controller never falls sideways to a neighboring row.

## Single-Press Operator Contract

Both POTA and DX use one single-press receive-tuning contract:

```text
navigate / rotate
    -> selection changes

single activation
    -> validate current radio state
    -> snapshot exact selected identity/callsign/frequency/mode
    -> submit to background tuning
    -> ReceiveTuningService performs ordered receive-only tuning
```

If there is no current selection, the tuning boundary is unavailable, or a tune
is already active, activation is rejected without creating confirmation state.

Only an accepted single activation rearms the shared callsign-info popup, including
the same station after navigation dismissal. Rejected activation does not rearm and
does not preload a callsign. Accepted band-filter changes dismiss the popup while
leaving provider-specific filtering and staged-action invalidation unchanged.

## Radio-State Gate

Before single-press submission, the active-panel command
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
guarded cross-band sequencing, best-effort FT-891 band-context recall, and exact
frequency/mode read-back verification.

No provider-specific POTA or DX tune executor is introduced by checkpoint 8.

## FT-891 Cross-Band Contract

The FT-891 adapter may use the operator-programmed regular memory for the target
band as best-effort context before setting the exact selected spot frequency.
The memory is selected and verified with `MCxxx;` / `MC;`, copied to VFO-A with
`MA;`, and its recalled frequency must resolve to the target amateur band before
the ordered tune continues.

That successful recall is not treated as proof that the FT-891 changed its
authoritative operator-visible band state. The final cross-band operator
contract is therefore:

```text
single press succeeds
    -> exact selected receive frequency/mode is reached
    -> SET BAND TO <BAND> METERS — TUNE ATAS-120
    -> operator manually sets/confirms band and tunes ATAS-120 before transmit
```

Same-band receive tuning bypasses memory recall and produces no band/ATAS
warning.

The unresolved FT-891 CAT/front-panel band-context behavior is intentionally
parked in issue #149 and does not block checkpoint 8.

## Background Tuning and Presentation

`SharedSpotTuneController` submits the exact selected frequency/mode on a background
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
- successful cross-band result: amber manual band/ATAS reminder for 10 seconds

The cross-band warning text is:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

The warning is an explicit operator handoff. It does not claim that the FT-891
changed its authoritative front-panel band state, does not tune or verify the
ATAS-120, and does not claim the antenna is safe to transmit.

## Back / Cancel Behavior

Within a shared POTA/DX context, Back operates on panel state only:

1. if a row is selected, clear selection
2. otherwise, return control to the normal surrounding navigation behavior

Back does not create a radio action.

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

Checkpoint 8 includes:

- DX band and mode filtering through the shared controller
- independent POTA/DX filter state
- current-radio-band activation default with 20-meter fallback
- single-press POTA/DX receive-tune submission
- stable-selection and action-snapshot validation
- radio-state validation before tuning
- background shared receive tuning
- shared tuning/success/failure presentation
- timed cross-band manual band/ATAS warning
- production Forge systemd deployment under the dedicated `rollingthunder`
  service account
- production Forge POTA and DXSpider live-health acceptance

Physical checkpoint-8 acceptance is complete on `anvilmobile`:

- POTA and DX single press receive tuning: accepted
- same-band POTA receive tuning: pass
- same-band DX receive tuning: pass
- cross-band POTA receive frequency/mode tuning plus manual band/ATAS handoff:
  pass
- cross-band DX receive frequency/mode tuning plus manual band/ATAS handoff:
  pass
- selection-change and Back invalidation: pass
- band-filter invalidation: pass
- mode-filter invalidation: pass
- radio-loss invalidation and safe reconnect without stale execution: pass
- Standard TX-capable FT-891 port remains closed
- retained POTA/DX presentation during controlled Forge interruption: pass
- isolated local SQLite logging while Forge is unavailable: pass
- production contact count unchanged by the isolated offline test
- Forge connectivity restored and temporary test artifacts removed

Automatic authoritative FT-891 band-state behavior is explicitly outside the
checkpoint-8 acceptance claim and remains tracked in issue #149.

No shared-spot component has transmit authority.
