# Rolling Thunder v4 Architecture

## Purpose

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system.
Its primary client runs on the Raspberry Pi 4 named `anvilmobile`.

The application supports durable local contact logging, voice callsign capture,
physical operator controls, shared POTA/DX operating intelligence, GPS state,
Yaesu FT-891 state and receive-only control, connectivity status, live GPS
mapping, and optional network enrichment.

Forge provides shared POTA/DX aggregation and may provide other Home Station
Platform services, but the Pi remains authoritative for mobile operation and
must remain useful when Forge, WireGuard, cellular service, or the public
internet is unavailable.

The approved `docs/RollingThunder_v4.1.0_Architecture_Specification.md` remains
the product architecture baseline. This document describes the current
implemented architecture through checkpoint 8 of issue #129.

## Design Goals

- Remain useful without internet, WireGuard, or Forge.
- Preserve completed contacts in durable local storage before remote work.
- Keep hardware-specific details outside application and UI logic.
- Support deterministic mock hardware and network boundaries for testing.
- Avoid blocking serial, audio, GPS, SQLite, filesystem, or network work in the
  Tkinter thread.
- Keep configuration typed, centralized, actionable, and free of secrets.
- Route graphical and physical controls through the same application-command
  boundaries.
- Fail visibly and safely when hardware or network services disappear.
- Keep `ReceiveTuningService` as the sole receive-tuning authority.
- Add no software PTT, MOX, keying, tuner, power, or unattended transmit
  authority.

## Current High-Level Components

```text
+--------------------------------------------------------------------+
| Raspberry Pi 4: anvilmobile                                        |
|                                                                    |
|  +-------------------------- Tkinter UI -------------------------+  |
|  | dashboard | shared POTA/DX panel | map | status ticker       |  |
|  +------------------------------+--------------------------------+  |
|                                 |                                   |
|  +---------------- Application Controllers ---------------------+  |
|  | operator commands | logging | shared spot stable selection  |  |
|  | panel commands | navigation | tune-status presentation       |  |
|  +------------------------------+--------------------------------+  |
|                                 |                                   |
|  +------------------- Runtime / Application Services ------------+  |
|  | radio/GPS polling | speech | contact sync | Forge spots      |  |
|  | shared tune worker | enrichment | physical controls          |  |
|  +------------------------------+--------------------------------+  |
|                                 |                                   |
|  +-------------------- Typed Ports and Domain --------------------+ |
|  | Radio | CatTransport | GPSReceiver | ControlSource             | |
|  | repositories | remote clients | immutable state/value objects  | |
|  +------------------------------+--------------------------------+ |
|                                 |                                   |
|  +-------------------------- Adapters ----------------------------+ |
|  | FT-891 CAT | serial GPS | ESP32 serial | SQLite | HTTP        | |
|  +----------------------------------------------------------------+ |
+----------------------------------+---------------------------------+
                                   |
                          private routed network
                                   |
                      +------------v-------------+
                      | Forge spot service       |
                      | POTA + DXSpider + SQLite |
                      +--------------------------+
```

## Layer Responsibilities

### Domain and Value Types

Domain code represents stable project concepts and validation rules, including:

- callsign and Maidenhead grid
- frequency, amateur band, and radio mode
- radio and GPS state
- contact and synchronization state
- provider-neutral POTA/DX spot records
- stable spot identities
- exact per-activation receive actions
- immutable presentation and service snapshots

Domain code does not depend on Tkinter, pyserial, HTTP clients, SQLite details,
device paths, or network availability.

### Ports and Protocols

External capabilities are exposed through small typed interfaces such as:

- `Radio`
- `CatTransport`
- `GPSReceiver`
- `ControlSource`
- contact and retry repositories
- Forge and Home Station Platform clients
- provider/enrichment clients

Ports expose only capabilities required by Rolling Thunder. They must not mirror
an entire vendor API or allow an adapter to bypass application safety policy.

### Adapters

Adapters contain hardware, persistence, and network details. Current examples
include:

- `Ft891Radio` over a typed CAT transport
- `SerialGPSReceiver`
- `SerialControlSource` for ESP32 events
- deterministic mock radio, GPS, and control sources
- SQLite repositories
- HTTP Forge/Home Platform/POTA/QRZ/weather/boundary adapters

Operating-system paths belong only in typed configuration and composition.

### Application Services and Controllers

Application services coordinate use cases without knowing concrete hardware.
Current examples include:

- pending callsign capture, Commit, and Discard
- durable local contact creation
- background contact synchronization
- radio and GPS polling
- Pi Forge shared-spot polling/cache publication
- shared POTA/DX filtering, stable selection, and staging
- background shared receive tuning
- physical-control event mapping, gating, and dispatch
- navigation and context-sensitive panel commands
- thread-safe status-message arbitration

The shared operator-command boundary is fundamental: installed controls and
keyboard/UI actions invoke the same application behavior. There is no
ESP32-only radio path and no provider-specific POTA/DX radio path.

### User Interface

Tkinter presents immutable state and invokes application controllers. It must
not:

- open serial or audio devices directly
- parse NMEA, CAT, or ESP32 protocol messages
- issue raw CAT commands
- perform blocking HTTP requests
- access SQLite implementation details
- decide retry/synchronization policy
- grant physical controls additional authority

UI refresh may read already-published immutable snapshots. Slow hardware,
network, SQLite, filesystem, and CAT work belongs in owned background services.

## Status Message Arbitration

`StatusMessageService` is the runtime-owned, thread-safe boundary for the global
bottom status bar.

Publishers submit immutable messages with a replacement key, text, presentation
token, integer priority, and optional monotonic expiration. The highest-priority
active message is rendered; the newest wins on equal priority.

Checkpoint-8 shared receive tuning publishes:

- normal `TUNING ...` status while the tune is active
- success status for 5 seconds
- failure status for 8 seconds
- cross-band manual band/ATAS-120 reminder for 10 seconds at higher priority

The cross-band reminder text is:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

It is a timed operator handoff, not a claim that CAT authoritatively changed the
FT-891 band state, not a tuner command, and not antenna verification.

## Shared POTA/DX Architecture

The shared spot architecture defines immutable provider-neutral POTA/DX records,
canonical complete snapshots, stable identities, provider-specific filters,
stable selection, exact per-activation receive actions, and the single-press operator
contract.

Forge owns live public POTA and DXSpider provider access. The Pi receives only
complete versioned Forge snapshots through the typed Forge client, validates
them before activation, persists them transactionally, and retains the previous
valid snapshot when a live attempt fails.

The running POTA and DX contexts use one `SharedSpotPanelController`. Dashboard
refresh reads only already-published Pi Forge state and performs no HTTP, SQLite,
filesystem, provider, QRZ, or CAT work.

### Stable identity and selection

Selection is preserved by `SpotIdentity`, never row number. If a selected
identity disappears from a refreshed or filtered view, selection and staging
clear without selecting a neighboring record.

A staged action captures:

- identity
- callsign
- frequency
- normalized radio mode

A refresh that changes any action-critical staged value invalidates staging.
Metadata such as operator name, grid, park name, coordinates, comments, or mode
provenance may refresh without redirecting the action.

### POTA and DX filters

Both POTA and DX support mobile HF bands:

- 80 m
- 40 m
- 20 m
- 17 m
- 15 m
- 12 m
- 10 m

Both use mode groups:

- SSB
- CW
- FT4
- FT8
- DATA
- ALL

Filter state is independent per provider. POTA additionally applies its age
filter; DX does not inherit it.

Activating POTA or DX uses the current FT-891 band when it resolves to one of the
supported shared bands, otherwise 20 meters. POTA starts with SSB filtering; DX
starts with ALL.

Any band or mode filter change cancels staging.

### Single-press contract

The shared POTA/DX operator sequence is:

```text
navigate / rotate
    -> stable selection changes

single activation
    -> validate current radio state
    -> snapshot exact identity/callsign/frequency/mode
    -> SharedSpotTuneController background worker
    -> ReceiveTuningService
    -> typed Radio
```

No persistent receive-confirmation stage is created.

### Radio-state validation

Before single-press submission, the active-panel controller requires
an immutable radio state that is:

- `CONNECTED`
- frequency known
- mode known
- not transmitting

If the state is unusable, no shared-spot receive tune is submitted.

`ReceiveTuningService` independently refuses ordered receive tuning when the
radio reports transmitting.

### Back / Cancel

Within shared POTA/DX state, Back:

1. clears the selected row if selected

Back does not acknowledge the timed band/ATAS status and does not create a radio
action.

See `docs/SHARED_SPOT_DOMAIN.md` for the complete domain and operator contract.

## Forge Service Architecture

Forge spot aggregation is an independent process. It owns:

- typed Forge YAML loading
- optional environment-backed QRZ secrets
- public POTA and bounded DXSpider providers
- optional best-effort QRZ enrichment
- transactional Forge SQLite snapshots
- provider-specific health
- versioned read-only REST
- background refresh lifecycle

REST request handlers read only already-published immutable Forge state. They do
not contact providers, write SQLite, or access radio hardware.

Production deployment is now formalized under systemd on Forge:

- service account `rollingthunder`
- application `/opt/rolling-thunder-forge`
- config `/etc/rolling-thunder/forge-spots.yaml`
- optional secret env `/etc/rolling-thunder/forge-spots.env`
- database `/var/lib/rolling-thunder/forge-spots.db`
- listener `192.168.9.170:8766`
- `Restart=on-failure`
- five-second restart delay
- enabled at boot
- journald diagnostics

The API has no TLS or application-layer authentication in checkpoint 8. It is
supported only inside the documented private RadioLAN/CarLAN-over-WireGuard
trust boundary. See `docs/FORGE_DEPLOYMENT.md`.

## Pi Forge Client and Offline State

The Pi Forge path is:

```text
HttpForgeSpotClient
    -> complete-response validation
    -> ForgeSpotCacheRepository
    -> PiForgeSpotService
    -> PiForgeSpotPollingService
    -> ApplicationRuntime.latest_forge_spot_state
```

Persistence happens before publication. The service distinguishes:

- empty
- cached
- live
- retained

Forge/network/provider failure leaves the prior valid shared snapshot available
when one exists and never blocks local contact logging.

When Forge is enabled, the legacy direct public-POTA poller is not composed. The
legacy implementation/cache remain as a non-destructive compatibility path when
Forge is disabled.

See `docs/PI_FORGE_CLIENT.md`.

## Runtime Composition and Lifecycle

`ApplicationRuntime` owns core radio, GPS, logging, connectivity, Forge client,
and status-message services. UI composition adds shared-panel, shared-tune
status, navigation, and physical-control command controllers.

Startup/shutdown remains explicit:

1. load and validate configuration
2. build mocks or physical adapters
3. connect hardware through typed boundaries
4. start lifecycle-managed polling/worker services
5. start UI refresh and bounded event dispatch
6. stop producers before closing adapters and UI

A failed optional service must not prevent unrelated local functions from
starting. Errors become visible disconnected/degraded/error state rather than
hidden stale state or broad application failure.

## Configuration and Secrets

`ApplicationConfig` is the authoritative typed application YAML boundary.
Secrets are not stored in YAML or Git.

QRZ credentials are loaded through the centralized application-secrets boundary.
Forge production QRZ credentials, when enabled, are provided through the
external environment file documented in `docs/FORGE_DEPLOYMENT.md`.

Secret values, session keys, and authentication responses must not be logged or
placed in tests, issues, pull requests, or documentation examples.

## Live Map Architecture

The live-map subsystem is local-first and keeps map storage and network work out
of Tkinter.

`LiveMapController` converts immutable GPS state into presentation without I/O.
`LiveMapService` owns bounded background viewport work and publishes immutable
map snapshots. Map failure remains isolated from GPS polling, logging, shared
spots, physical controls, radio polling, and receive-only tuning.

### Viewport scheduling and publication

Viewport requests are generation-aware. A newer request can supersede obsolete
queued work; stale work is prevented from publishing over the newest viewport
and stops before making unnecessary additional online tile requests.

Identical loaded viewports are ignored. Movement that retains the same visible
tile set can reframe those tiles without additional tile I/O. Locally available
tiles are published before slower online refresh completes, and current-viewport
online results may be published progressively.

### Rendering

Tkinter does not rebuild the complete base-map layer for every viewport update.
The presentation path plans tile changes as remove, redraw, or move. Unchanged
canvas tile objects are retained, and tiles whose image content is unchanged but
whose screen position moved are repositioned rather than decoded and recreated.
A bounded Tk `PhotoImage` cache reuses unchanged decoded tile images.

### Radar coverage buffering

The optional radar layer follows a stricter complete-publication contract than
the progressively publishable base map. The visible map viewport is separated
from a larger immutable radar coverage viewport. Current policy builds radar
coverage with six whole Web Mercator tiles of reserve on every side and begins a
spatial replacement when the minimum reserve reaches three tiles.

`LiveRadarOverlayService` owns one complete published FRONT coverage buffer, one
active BACK generation, and at most one coalesced newest desired target. Ordinary
movement inside FRONT coverage publishes a new immutable visible crop from
already-prepared FRONT PNG bytes and requires no radar HTTP or disk work. When
spatial or meteorological refresh is required, BACK is built outside Tkinter
while FRONT remains published. Partial or obsolete BACK data cannot replace
FRONT; only a complete exact-frame candidate that is still relevant swaps into
FRONT.

Spatial and meteorological refresh are independent. Movement can trigger a
coverage recenter without forcing a manifest request while the cached manifest
is still within its check interval, while expiration of that interval can adopt
a newer radar frame without vehicle movement. Same-frame spatial recentering
reuses overlapping FRONT PNG bytes and requests only newly exposed edge tiles.
Every published coverage buffer remains locked to one radar frame token and
provider observation time.

Radar buffers are zoom-specific. Incompatible old-zoom radar is removed during a
zoom transition rather than stretched or misregistered. If BACK fails, a still
fresh FRONT may remain visible only while it truthfully covers the visible map.
Moving beyond its geographic coverage or crossing the radar hide-age cutoff
removes the overlay rather than displaying false coverage.

Tkinter receives only already-prepared immutable visible radar state. It retains
and repositions same-frame radar canvas objects where image bytes are unchanged;
it does not perform radar HTTP, filesystem, SQLite, opacity processing, or
provider work. See `docs/WEATHER_RADAR.md` for resource bounds, exact-frame
semantics, diagnostics, and physical acceptance.

### Tile source resolution

Installed raster MBTiles packages are represented through typed package and
resolver boundaries. The resolution order is:

```text
installed package
    -> runtime tile cache
    -> online provider
    -> unavailable
```

Installed packages are opened read-only and carry validated identity, bounds,
zoom range, PNG raster format, TMS scheme, style, attribution, version, and
priority metadata. Higher-priority matching packages are consulted first.

Declared installed coverage is authoritative. If a coordinate lies inside a
package's declared bounds and zoom range, a missing tile there does not silently
grant the online provider authority for that location. This preserves genuine
offline behavior instead of unexpectedly consuming cellular data.

The first production package proven through this architecture covers the normal
I-71 mobile corridor and is installed outside Git on `anvilmobile`. Broader Ohio
and surrounding-state package coverage remains follow-up work under issue #124.

### Runtime tile cache

The runtime cache remains separate from installed offline packages. Tile writes
are PNG validated, written through a temporary file, flushed and `fsync`ed,
atomically replaced, and timestamped for retention and oldest-entry eviction.

Historically every successful cache write immediately performed a recursive
enumeration, stat, complete mtime sort, and prune. That made a multi-tile online
viewport repeatedly rescan the same cache.

Issue #151 changes pruning to a deterministic bounded successful-write cadence.
The first successful write performs the initial prune check so an already
oversized cache is corrected promptly; later full prune passes are amortized
across writes. A prune failure remains non-fatal and does not invalidate a tile
that was successfully written.

### Failure isolation

Map HTTP, installed-package, cache, radar, or rendering-data failure must not
disable GPS polling, callsign capture, Commit or Discard, local SQLite logging,
shared POTA/DX state, DMR, repeaters, physical controls, radio polling, or
receive-only tuning.

Tkinter does not open map/radar network connections, query MBTiles databases, or
perform runtime-cache filesystem maintenance directly.

Automatic day/night selection, broader regional package coverage, and the
separate future operating-overlay/PAD-US path remain follow-up work in issue
#124.

## Local Logging and Offline Operation

The Pi remains local-first:

1. callsign is captured/selected into pending state
2. no QSO is written until explicit Commit
3. Commit snapshots available radio/GPS/context metadata
4. complete QSO is written immediately and durably to local SQLite
5. optional enrichment/synchronization occurs afterward
6. remote failure never removes or invalidates the local contact

`my_grid` represents the mobile/operator location; `grid` represents the
contacted station/park location. POTA reference and grid-source semantics remain
separate typed fields.

Forge failure, WireGuard loss, provider failure, or rejected shared data must not
prevent local Commit or Discard.

Checkpoint-8 acceptance additionally proved this boundary with an isolated
temporary SQLite database while Forge was intentionally unavailable. The test
contact was created and read back locally, the production contact count remained
unchanged, the UI remained running, Forge recovered, and all temporary artifacts
were removed.

## Radio Architecture and Safety

The `Radio` boundary and `Ft891Radio` adapter support only the approved
receive-side scope:

- connect/disconnect
- read current VFO-A frequency and receive mode
- background state refresh/recovery
- independent best-effort band-context operation
- independent same-band frequency change
- independent receive-mode change
- verified ordered receive-only tuning

The ordered `ReceiveTuningService` sequence is:

```text
resolve target band
read current radio state

if target band differs:
    select mapped regular memory with MCxxx;
    verify selected memory with MC;
    copy memory to VFO-A with MA;
    read recalled state;
    verify recalled frequency belongs to target amateur band

set exact target frequency
read frequency
verify exact target

set mode when needed
read mode
verify requested mode
```

A direct cross-band `set_frequency()` request remains guarded. Failed
best-effort memory-context verification stops that ordered attempt; failed exact
frequency verification stops mode work.

Successful memory recall is not treated as proof that the FT-891 changed its
authoritative operator-visible band state. After a successful cross-band receive
tune, Rolling Thunder explicitly hands control back to the operator with:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

The operator manually sets/confirms the band and tunes the ATAS-120 before
transmitting. The unresolved CAT/front-panel band-context behavior is tracked in
issue #149.

The FT-891 Standard Com Port remains unopened. No component exposes PTT, MOX, CW
keying, voice keying, digital TX control, tuner control, power control, or
unattended transmit authority.

Voice input and ESP32 input are operator-input mechanisms, not direct radio
control.

See `docs/REAL_FT891_INTEGRATION.md` for the hardware and physical acceptance
evidence.

## GPS Architecture

The `GPSReceiver` boundary has mock and serial implementations. GPS polling runs
outside Tkinter and converts transient read/parse failure into visible state
while allowing automatic recovery.

Current GPS state provides connection/fix state, coordinates, altitude,
satellite count, and immutable update time. Commit-time valid GPS is converted
to a six-character mobile grid without blocking local logging when GPS is
unavailable.

## Physical Controls

The physical-control architecture remains input-only and fail-closed:

```text
ESP32 firmware
    -> RTCTRL/1 EVENT
    -> bounded nonblocking serial source
    -> typed events
    -> duplicate/repeat gate
    -> configuration action mapper
    -> shared operator-command controller
    -> application behavior
```

The ESP32 emits opaque identifiers; it cannot name arbitrary Python functions or
request PTT.

Installed controls support Voice, Commit, Discard, context selection,
context-sensitive panel commands, encoder navigation, encoder activation, and
Back/Cancel behavior.

Malformed, oversized, unsupported, duplicate, rapidly repeated, and incomplete
messages fail closed. Startup failure leaves the UI operational without physical
controls.

The connection is intentionally one-way. Future LED feedback requires a typed
output boundary.

## Concurrency and Reliability

Potentially blocking work must not execute in the UI thread, including:

- serial GPS and CAT operations
- shared receive tuning
- speech capture/recognition
- HTTP requests
- radar manifest/tile retrieval and PNG opacity processing
- synchronization/retry work
- SQLite maintenance
- filesystem/cache work

Every worker/poller defines startup/shutdown ownership, timeouts, cancellation,
stale-state semantics, bounded work, and observable error state.

## Checkpoint-8 Acceptance Status

Checkpoint-8 implementation, Forge production deployment, and installed-hardware
acceptance are complete on the feature branch.

Accepted on `anvilmobile` with the real FT-891 and installed controls:

- DX band/mode filtering
- independent POTA/DX filter state
- current-band activation default with 20-meter fallback
- exact single-press POTA/DX receive submission
- no persistent receive-confirmation stage
- same-band POTA exact receive tuning
- same-band DX exact receive tuning
- cross-band POTA exact receive frequency/mode tuning
- cross-band DX exact receive frequency/mode tuning
- explicit `SET BAND TO <BAND> METERS — TUNE ATAS-120` handoff for cross-band
  operation
- no false band/ATAS warning on same-band operation
- staging invalidation on selection, band filter, mode filter, Back, and invalid
  radio state
- radio power-loss/recovery without resurrection of stale staging
- Enhanced CAT remains active and the Standard TX-capable FT-891 interface
  remains closed
- production Forge systemd deployment
- live healthy POTA/DX provider refreshes
- Pi requests reaching production `/api/v1/spots`
- retained POTA/DX snapshot presentation during controlled Forge loss
- isolated local SQLite contact commit/readback while Forge is unavailable
- production contact count unchanged by the isolated offline test
- Forge recovery after controlled interruption and clean removal of test artifacts
- no PTT, MOX, keying, tuner, power, or transmit authority

Automatic authoritative FT-891 band-state selection is explicitly not claimed;
the best-effort memory-context mechanism and future firmware/CAT investigation
are documented in issue #149.

Remaining checkpoint-8 closure work is final documentation review, full
repository quality gates, pull-request preparation/review, GitHub Actions, and
explicit owner authorization before merge.

## Development and Approval Model

Development occurs through focused branches and pull requests, never directly on
`main`.

The AI assistant may inspect GitHub, design slices, implement code/tests/docs,
run available validation, and prepare the PR. The repository owner performs real
hardware/full-screen acceptance and explicitly authorizes merge.

The normal loop remains:

```text
clean main
    -> focused feature branch
    -> implementation/tests/docs
    -> Ruff/MyPy/pytest/pre-commit
    -> pull request and CI
    -> owner hardware/UI validation
    -> owner approval and merge
```

Checkpoint 8 must remain unmerged until that explicit authorization is given.


## Selected Spot Callsign Preload

POTA and DX encoder activation may preload the exact selected spot callsign into
the existing pending-callsign capture state after the receive-tune submission is
accepted. Merely rotating/highlighting a row never changes the pending callsign.

This reuses the same state consumed by Commit. It does not create a separate
spot-only logging field. A later explicit voice capture remains authoritative and
may replace the preloaded callsign, which supports the operator case where a new
station takes over a frequency before the external spot feed refreshes.

A rejected or unusable radio/tune activation does not preload the callsign.


## Incremental POTA Map Marker Rendering

The moving-map POTA overlay must retain stable canvas objects across ordinary
vehicle movement. A viewport refresh does not delete and recreate the complete
POTA layer.

POTA marker canvas identity is based on the park reference plus its catalog
latitude/longitude. When the viewport changes at the same presentation mode:

- markers still visible are repositioned with canvas coordinate updates
- newly visible markers are created
- markers that leave the viewport are removed
- the complete POTA layer is cleared only when the overlay becomes invalid
  (for example, no matching published map/POTA viewport)

Crossing between dot and label presentation modes may recreate the affected
marker objects because their canvas representation changes.

This keeps POTA rendering consistent with the incremental base-map/radar
architecture and avoids visible park-marker flicker during continuous driving.


### Asynchronous POTA viewport handoff

The map and POTA database workers publish independently. A new GPS/map viewport
may therefore become visible before the POTA worker has published the matching
park query. This is normal and must not blank the overlay.

While the POTA snapshot is briefly for the previous viewport, its latest known
park set is projected against the current map viewport and retained on screen.
The next POTA snapshot then incrementally adds/removes any parks exposed by the
new bounds. Exact viewport equality is not required for temporary presentation.

This also prevents stationary GPS position jitter from causing the park layer to
blink off and back on.

## Browse Operating Context

Browse is a free-form receive and logging context placed immediately after DX in
the dashboard context cycle. It is intentionally independent of POTA/DX spot
selection and provider state.

The existing shared callsign-capture state remains authoritative. Browse does not
preload a callsign from any spot source; callsigns are entered through the same
Voice workflow used elsewhere and Commit/Discard retain their existing behavior.

Browse receive controls route through the context-aware active-panel boundary:

- encoder left: decrease receive frequency by the selected step
- encoder right: increase receive frequency by the selected step
- Button #2 / secondary: cycle 100 Hz, 500 Hz, and 1 kHz tuning steps
- Button #3 / tertiary: cycle CW, FM, SSB, and AM

The UI presents SSB as one operator-facing mode. Radio execution maps SSB to LSB
below 10 MHz and USB at or above 10 MHz. Browse tuning is receive-only, runs on a
background worker, does not expose raw CAT, and retains the existing no-PTT/no-MOX
safety boundary.

Browse Commit uses the existing durable local contact pipeline. With a valid GPS
fix, the contact note is:

`Mobile Contact from <latitude>, <longitude> (<six-character-grid>)`

If GPS is unavailable, the contact still commits and records
`Mobile Contact (GPS unavailable)` rather than inventing coordinates.


### Browse US Amateur Extra advisory

Browse includes a presentation-only US Amateur Extra frequency/mode advisory.
The rules live in `us_extra_band_advisory.py` rather than the Tk layer so the
regulatory boundaries are deterministic and unit tested.

Presentation is intentionally advisory and does not create transmit authority or
a CAT/PTT interlock:

- red with white text: the tuned carrier is outside a configured US Amateur
  Extra allocation/channel;
- yellow with dark text: the carrier is inside an allocation but the selected
  emission family is not authorized in that segment;
- no warning box: the frequency/mode combination passes the advisory.

CW is treated according to Part 97's rule permitting CW anywhere the control
operator is otherwise authorized. SSB/AM/FM are evaluated as phone-family
Browse modes for the requested sub-band warning. DATA is also evaluated for
radios entering Browse while already in DATA mode.

The rule set includes 160, 80/75, current 60 m privileges, 40, 30, 20, 17, 15,
12, 10, and 6 meters. Current 60 m channel/segment handling is special-cased,
and Browse SSB selects USB on 60 m.

The advisory does not calculate occupied emission bandwidth at a band edge and
must not be treated as a substitute for operator compliance with Part 97.


## Callsign Information Overlay

Rolling Thunder may show an optional lower-right map overlay after a pending
callsign is entered through an existing legitimate callsign path. The overlay is
informational only and never participates in durable Commit.

An independent Forge process owns on-demand QRZ, Wavelog-history, and target
weather provider work. This preserves the retained Forge spot API rule that its
request handlers read already-published state rather than performing provider
refresh I/O.

The Pi uses one bounded background request per pending callsign. A monotonic
generation identifies every request/presentation lifecycle. Callsign replacement,
Commit/discard clearing, timeout, service stop, and the Settings toggle invalidate
the generation so a late response cannot resurrect stale information.

Current-location priority is POTA park coordinate when the selected pending POTA
spot has one, otherwise QRZ QTH coordinates. The same selected coordinate drives
the overlay mini-map and simple current weather. QRZ state/DXCC-center coordinates
are not treated as precise weather locations.

The feature deliberately omits QRZ profile photographs. Weather is considered
more operationally useful and avoids image-download/cache complexity.

When Wavelog has no previous exact-callsign QSO, the prior-contact region displays
`FIRST CONTACT`.

A second regional map service uses the same map architecture, installed package
format, cache policy, and tile resolver types as the main live map, but owns its
own worker/resolver lifecycle. Tkinter consumes immutable map snapshots only.

Settings Context Button #3 toggles CALLSIGN INFO. The preference is persisted
through the existing asynchronous operator-preference service. When disabled,
active presentation is cleared immediately and no new lookup is started.

See `docs/CALLSIGN_INFO.md` for the API model, cache policy, lifecycle, weather
rules, deployment, and limitations.


## v4.3 Experimental FT8 architecture

Status: experimental runtime integration through Checkpoint 9; disabled by default.
The implementation includes receive/decode, one explicitly operator-authorized
bounded QSO path, successful-contact persistence, and a presentation/controller
boundary. Production migration remains separately owner-approved.

Earlier Checkpoint 1 architecture notes below describe the original research
boundary and are retained as historical design context. FT8 runtime or transmit authority is
implemented on `main`.

The v4.3 experiment is documented in `docs/FT8_ARCHITECTURE.md`. It preserves
the generic `Radio` protocol as receive-side and keeps all future FT8 transmit
authority behind a separate, narrow, operator-authorized capability.

The proposed FT8 path is feature-gated and disabled by default. When disabled,
no decoder, FT8 audio worker, FT8 timing worker, QSO worker, PTT backend, or
FT8-specific CAT operation may be constructed.

The installed target hardware is the FT-891 + DigiRig DR-891. The existing
Enhanced CAT path remains a single serialized owner; v4.3 must not create a
second unsynchronized connection. DigiRig audio and any future PTT mechanism
remain separate typed hardware boundaries.

Checkpoint 1 selects no production decoder. It requires a later on-Pi benchmark
of `ft8_lib` and `ft8mon` against current WSJT-X reference decodes before
the initial receive backend is chosen.

No current v4.2/v4.3-main safety claim is weakened by this design document:
software PTT/MOX/keying and FT8 transmission remain absent until an explicitly
approved later checkpoint implements and physically validates the narrow
transmit boundary.


## Experimental v4.3 FT8 domain foundation

Checkpoint 2 introduces a hardware-independent FT8 package without changing the
production runtime composition. The package owns immutable FT8 periods, decodes,
CQ activity, frozen one-QSO authorization context, deterministic timing, and a
bounded QSO state machine.

The only transmit-facing boundary is `DigitalTransmitSession`, which is
logical and fake-only at this checkpoint. It is separate from the generic
receive-side `Radio` protocol. No PTT, CAT transmit command, audio output,
decoder, waveform generator, persistence path, or hardware worker is composed.

FT8 configuration defaults to disabled:

```yaml
ft8:
  enabled: false
  qso:
    attempts_per_state: 6
```

The QSO retry budget is six attempts per unchanged state/message. CQ discovery
has no station-selection authority, and terminal QSO outcomes require an
explicit reset before another station can be authorized.


## Experimental v4.3 FT8 decoder foundation

Checkpoint 3 adds a receive-only project-owned decoder boundary under
`src/rolling_thunder/ft8/decoder.py` without composing it into
`ApplicationRuntime` or the production service.

The application-facing input is an `FT8PcmPeriod` containing an explicit
`FT8Period`, sample rate, and immutable mono signed-16-bit little-endian PCM
bytes. Backend-specific WAV paths, subprocess handles, and native decoder
objects do not cross that boundary.

Saved-WAV adapters currently exist for the pinned `kgoba/ft8_lib` and
`rtmrtmrtmrtm/ft8mon` candidates. Both normalize into the existing immutable
`FT8Decode` domain type. The official WSJT-X 3.0.2 ARM64 build is used only
as an isolated saved-WAV oracle during the bake-off and is not a production
dependency.

Checkpoint 3 still adds no live DigiRig capture, decoder worker, QSO execution,
successful-QSO logging, CAT transmit action, PTT, transmit audio, waveform
generation, or RF authority.


Checkpoint 3's Pi bake-off selects `kgoba/ft8_lib` as the initial receive
backend for the next experimental checkpoint because its bounded sub-second
decode time and low memory/CPU footprint provide substantially more FT8 slot
timing margin. The measured sensitivity deficit versus `ft8mon` is retained
as an explicit architectural limitation, and `ft8mon` remains a comparison
or fallback candidate. WSJT-X 3.0.2 is benchmark/oracle only.

## Experimental v4.3 FT8 live receive composition

Checkpoint 4 composes the receive-only FT8 pipeline when and only when
`ft8.enabled` is true. The pipeline is:

```text
DigiRig ALSA capture
  -> FT8AudioInput
  -> FT8PcmPeriod
  -> Ft8LibDecoder
  -> FT8Decode
  -> FT8CQActivityManager
```

The concrete ALSA adapter is isolated below the project-owned audio protocol.
Runtime/UI code does not open ALSA device paths or subprocesses directly.
Capture and decode are background-owned and use a bounded one-period handoff so
Tkinter cannot block and decoder backlog cannot grow without bound.

This checkpoint does not add an FT8 browser UI or any transmit capability.
