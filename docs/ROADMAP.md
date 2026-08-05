# Rolling Thunder v4 Roadmap

This roadmap describes intended sequencing. It is not a promise that every
feature will be implemented exactly as listed. The approved v4.1.0 architecture
specification remains authoritative when sequencing or terminology differs.

## Milestone 0: Development Foundation

Status: substantially complete.

- Python package structure
- virtual environment and editable installation
- Ruff
- MyPy
- pytest
- GitHub Actions
- pre-commit checks
- Codex development guidance
- architecture and contribution documentation

## Milestone 1: Typed Configuration

Status: complete and audited.

- Add a typed application configuration model.
- Load configuration from a local YAML file.
- Validate callsign, grid, URLs, paths, and mode selections.
- Support mock-hardware mode.
- Provide clear configuration errors.
- Add full automated tests.
- Include an example configuration without secrets.

## Milestone 2: Core Domain Models

Status: complete and audited.

- Contact model
- Frequency and radio-mode types
- Radio-state model
- GPS-position model
- Synchronization-state model
- Callsign and grid validation
- Serialization boundaries with tests

## Milestone 3: Local Contact Logging

Status: complete and audited.

- SQLite-backed contact repository
- Create and retrieve contacts
- Pending/synchronized status
- Duplicate-protection strategy
- Durable writes
- Export or recovery mechanism
- Tests using temporary databases

## Milestone 4: Radio Abstraction

Status: complete for the current FT-891 software scope.

- Typed radio interface
- Deterministic mock radio
- Frequency and mode readout
- Band change and frequency setting
- Connection-state reporting
- FT-891 CAT adapter
- Safe handling of disconnects and malformed replies
- Background radio polling outside the UI thread

The adapter and CAT protocol are implemented and tested without hardware. Live
operation against the installed Yaesu FT-891 is scheduled as Milestone 10 Phase
B so hardware configuration, device identity, startup, recovery, and safe
receive-only tuning can be validated as one focused integration slice.

## Milestone 5: Basic Pi User Interface

Status: substantially complete for the current mobile-logging slice.

- Full-screen Raspberry Pi application shell
- direct navigation among primary contexts
- live radio status area
- pending-callsign voice workflow
- explicit Commit and Discard controls
- durable local contact commits
- large, readable in-vehicle presentation
- high-contrast layout
- station-health presentation
- no blocking radio, voice, or storage work in the UI thread

Remaining Milestone 5 work should be limited to focused architecture-aligned
integration and usability refinements rather than a broad dashboard rewrite.

## Milestone 6: GPS and Location

Status: complete and audited for the approved software scope.

- Typed GPS interface
- mock GPS source
- serial GPS adapter
- Maidenhead grid calculation
- current position display
- graceful loss and reacquisition of GPS

The implemented GPS path includes typed immutable state, deterministic mock and
serial-NMEA adapters, Station State and dashboard integration, independent
background polling, visible degraded/error state, and automatic recovery after
transient read or parse failures.

The current serial adapter accepts checksummed GPGGA and GNGGA sentences and
provides latitude, longitude, altitude, satellite count, fix state, and update
time. Live receiver integration is scheduled as Milestone 10 Phase A so the
actual device path, baud rate, permissions, sentence mix, startup behavior, and
recovery behavior can be validated on `anvilmobile`.

Commit-time GPS capture is now implemented: a current valid fix is converted
to a six-character mobile-station grid and stored separately from the contacted
station grid. GPS loss or stale data leaves that field empty without preventing
local Commit.

Trusted GPS UTC, speed, heading, and stationary/moving hysteresis remain
architecture-aligned follow-up capabilities.

## Milestone 7: Home Station Platform Connectivity

Status: complete and audited for the approved roadmap scope.

- Typed remote API interface
- health and reachability checks
- queued synchronization
- retry with persisted exponential backoff
- idempotent contact upload
- visible online, offline, unknown, and disabled state
- independent cellular/WireGuard network keepalive
- network failures never block local logging

The implemented connectivity path includes a transport-independent Home Station
Platform boundary, deterministic mock and HTTP clients, lifecycle-managed health
polling, queued contact synchronization, durable retry eligibility, typed network
keepalive configuration and service, runtime composition, and pure connectivity
presentation state. The existing dashboard ticker exposes network, platform, and
synchronization status without changing the reserved right-side presentation
area or coupling the UI directly to worker services.

Live validation against the configured cellular hotspot, WireGuard route, and
Forge endpoint remains an operational smoke test rather than an automated-test
requirement. Home Station Platform server implementation and broader remote
analytics remain later architecture work and are not implied by completion of
this client-side milestone.

## Milestone 8: POTA Assistance

Status: complete and audited for the approved roadmap scope.

- Retrieve or receive POTA spots
- filter and rank spots
- frequency and mode display
- assisted tuning through the radio interface
- safeguards against unintended tuning
- local cache for temporary outages

The implemented POTA path includes typed provider-independent spot models,
deterministic mock and HTTP sources, lifecycle-managed polling, visible degraded
and stale-data handling, local filtering and ranking, dashboard presentation,
explicit operator-confirmed tune intent, receive-only runtime tuning, and a
durable SQLite-backed cache that survives application restarts.

The POTA panel also includes asynchronous QRZ name/profile enrichment,
Open-Meteo weather and park-local time, U.S. Census state outlines,
geoBoundaries DX subdivision/country outlines, a park-location marker, and a
timed detail overlay. These network enhancements remain independent of local
logging, radio state, and the core POTA spot workflow.

The completed scope does not permit voice-originated tuning, unattended tuning,
PTT, MOX, or transmission.

## Milestone 9: Physical Controls

Status: complete and audited for the approved physical-input scope.

- typed, transport-independent control actions and input events
- configuration-driven mappings from opaque ESP32 identifiers to approved
  application actions
- deterministic mock control source for tests and development
- strict versioned `RTCTRL/1 EVENT` parser
- bounded, nonblocking pyserial control source
- startup, refresh-dispatch, shutdown, and failure lifecycle integration
- physical Voice, Commit, and Discard controls
- direct context-selection and panel-action controls
- short- and long-press handling for Panel, Context, and encoder-switch inputs
- rotary-encoder navigation, activation, cancellation, and back behavior
- duplicate-event and rapid-repeat suppression
- malformed, oversized, unsupported, and incomplete input fails closed
- physical controls invoke the same shared application commands used by the UI
- no physical-control action grants direct PTT, MOX, transmit, or unattended
  tuning authority
- complete ESP32 GPIO/event firmware and bench validation on the installed panel

The milestone was delivered through the typed control boundary, serial transport,
complete ESP32 panel firmware, shared operator-command dispatch, and active-panel
encoder integration. Hardware event identifiers were observed and validated on
`anvilmobile`; the full panel was bench-tested for one-event-per-press behavior,
short/long press separation, held-button suppression, and encoder direction.

The current ESP32 link is intentionally one-way from ESP32 to Raspberry Pi.
Bidirectional LED color or status control was explicitly excluded from the
implemented milestone. LED feedback remains a later physical-panel enhancement
and must use a typed output boundary rather than being added to the input parser
or UI callbacks.

## Milestone 10: Hardware-Backed Mapping and Operating Intelligence

Status: in progress.

Milestone 10 begins by proving the real local hardware foundations, then expands
mapping and operating intelligence in focused vertical slices.

### Phase A: Real GPS Integration

Status: complete and approved.

- stable real GPS device identity and permissions
- actual 9,600-baud mixed-NMEA receiver behavior
- typed `GPSReceiver` boundary and mock source preserved
- live position, fix state, Maidenhead grid, loss, reacquisition, and UI status
- background serial work and automatic recovery
- setup, troubleshooting, and recovery documentation

### Phase B: Real Yaesu FT-891 Integration

Status: complete and approved.

Completed and verified:

- stable Enhanced CAT device identity and permissions
- 38,400-baud, 8-N-2 serial configuration
- read-only frequency, mode, polling, disconnect, and recovery
- typed `Radio` and `CatTransport` boundaries
- independent band, frequency, and mode operations
- hard band-before-frequency ordering for cross-band changes
- band, frequency, and mode read-back verification
- confirmed POTA receive tuning through the ordered service
- unsupported 60-meter CAT band selection failing closed
- same-band and controlled cross-band hardware validation
- isolated FT-891 band-memory behavior validation
- Standard Com Port remaining unopened
- amber global ATAS-120 retune warning for 10 seconds after verified band changes
- same-band warning suppression and replacement-key updates through generic
  status arbitration
- no PTT, MOX, keying, tuner, power, or unattended transmit authority

The required receive-tuning order remains:

```text
band selection
band verification
frequency setting
frequency verification
mode setting when needed
mode verification
```

### Phase C: Mapping and Operating Intelligence

Status: first live-map slice complete and approved through pull request #121.

The current first slice provides:

- north-up live map in the existing right-side situational area
- latest valid GPS position centered at a typed configurable fixed zoom
- prominent current or last-known vehicle marker
- Maidenhead grid, coordinates, GPS state, and map-data state
- explicit waiting, stale, last-known, cache-only, partial, and unavailable
  presentation
- one bounded background worker for all map HTTP and cache work
- validated atomic raster-tile cache with configured bounds
- on-demand visible-tile retrieval with no route or regional prefetching
- existing POTA overlay above the map
- global ticker rendered through priority-arbitrated immutable status snapshots
- no Home Station Platform dependency
- no radio or transmit-control changes

Still deferred after the first slice:

- panning or zoom controls
- movement trail, heading, or speed arrow
- contact visualization
- POTA markers on the persistent map
- routing, repeaters, weather radar, and analytics
- automatic zoom
- packaged regional offline maps, MBTiles, or vector tiles
- persisted location history
- dashboard redesign

Large hardware or full-screen changes require manual validation by the repository
owner on `anvilmobile` before their pull requests are approved or merged.

## Cross-Cutting Architecture Work

The v4.1.0 architecture specification defines Station State as the unified
operational read model consumed by the UI and dependent services. This boundary
is being added incrementally around the implemented radio, voice, logging,
storage, context, health, GPS, connectivity, POTA, enrichment, physical-input,
and live-map capabilities.

The runtime now owns a thread-safe immutable status-message service. The routine
ticker and verified ATAS-120 reminder publish through stable replacement keys,
priority arbitration, and monotonic expiration. This is the approved extension
point for future APRS, MeshCore, weather, DX, and radio alerts.

An in-process event bus remains an architectural direction, not a requirement to
retrofit prematurely. Its implementation should be driven by demonstrated
service-coordination needs while preserving the current safe Tkinter and worker-
thread boundaries.

## Later Possibilities

- typed bidirectional ESP32 LED feedback
- Wavelog integration
- Maestro or Flex station detection
- enhanced contest workflows
- telemetry to Grafana
- remote-station status
- additional radio adapters
- mobile-safe audible prompts

## Immediate Next Feature

Implement checkpoint 3 of GitHub issue #129: add the shared provider-neutral spot
domain, deterministic ordering, stable selection, and staged-action primitives.

The next checkpoint must:

- define immutable POTA/DX-neutral spot records and snapshots
- preserve selection by stable identity across snapshot replacement
- clear selection and staged action when a selected spot disappears
- order by explicit amateur-band rank, frequency, and deterministic tie-breakers
- collapse duplicate same-park/same-frequency POTA entries deterministically
- display unknown operator names and grids as `<UNKNOWN>`
- remain independent of Forge, public internet, Tkinter, SQLite, CAT, and hardware
- preserve the existing `ReceiveTuningService` as the only tuning authority
- add no PTT, MOX, keying, tuner, power, or unattended transmit authority
- pass Ruff, strict MyPy, full pytest, pre-commit, and GitHub Actions
- remain unmerged without explicit owner authorization
