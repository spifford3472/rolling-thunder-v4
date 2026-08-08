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
- Band-context handling and frequency setting
- Connection-state reporting
- FT-891 CAT adapter
- Safe handling of disconnects and malformed replies
- Background radio polling outside the UI thread

The installed Yaesu FT-891 integration has now been validated through the typed
`Radio` and `ReceiveTuningService` boundaries. The approved scope remains
receive-only and contains no PTT, MOX, keying, tuner, power, or unattended
transmit authority.

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

Remaining Milestone 5 work should be focused architecture-aligned integration
and usability refinements rather than a broad dashboard rewrite.

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

Commit-time GPS capture is implemented: a current valid fix is converted to a
six-character mobile-station grid and stored separately from the contacted
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
presentation state.

## Milestone 8: POTA Assistance

Status: complete for the current shared-spot architecture.

The original POTA-only path established:

- typed POTA spot retrieval and durable cache
- band/mode filtering and ranking
- explicit receive-only operator confirmation
- offline presentation
- POTA contact-context metadata
- QRZ/weather/boundary enrichment

The later shared POTA/DX work supersedes the POTA-only live-provider path when
Forge is enabled. POTA now uses the provider-neutral shared snapshot and shared
operator workflow described below.

The completed scope does not permit voice-originated tuning, unattended tuning,
PTT, MOX, keying, tuner, power, or transmission.

## Milestone 9: Physical Controls

Status: complete and audited for the approved physical-input scope.

- typed, transport-independent control actions and input events
- configuration-driven mappings from opaque ESP32 identifiers to approved
  application actions
- deterministic mock control source
- strict versioned `RTCTRL/1 EVENT` parser
- bounded, nonblocking pyserial control source
- startup, refresh-dispatch, shutdown, and failure lifecycle integration
- physical Voice, Commit, and Discard controls
- direct context-selection and panel-action controls
- short- and long-press handling
- rotary-encoder navigation, activation, cancellation, and back behavior
- duplicate-event and rapid-repeat suppression
- malformed, oversized, unsupported, and incomplete input fails closed
- physical controls invoke the same application commands used by the UI
- no physical-control action grants direct PTT, MOX, transmit, or unattended
  tuning authority

The current ESP32 link is intentionally one-way from ESP32 to Raspberry Pi.
Typed bidirectional LED feedback remains a later enhancement.

## Milestone 10: Hardware-Backed Mapping and Operating Intelligence

Status: in progress.

### Phase A: Real GPS Integration

Status: complete and approved.

- stable real GPS device identity and permissions
- actual 9,600-baud mixed-NMEA receiver behavior
- typed `GPSReceiver` boundary and mock source preserved
- live position, fix state, Maidenhead grid, loss, reacquisition, and UI status
- background serial work and automatic recovery
- setup, troubleshooting, and recovery documentation

### Phase B: Real Yaesu FT-891 Integration

Status: complete for the approved receive-only architecture; checkpoint-8 shared
POTA/DX installed-hardware acceptance is complete.

Completed and verified:

- stable Enhanced CAT device identity and permissions
- 38,400-baud, 8-N-2 serial configuration
- read-only frequency, mode, polling, disconnect, and recovery
- typed `Radio` and `CatTransport` boundaries
- independent typed band-context, frequency, and mode operations
- best-effort regular-memory band-context recall for cross-band receive tuning
- selected-memory and recalled-frequency target-band verification
- exact frequency and receive-mode read-back verification
- same-band tuning bypassing memory recall
- same-band and controlled cross-band receive-only validation
- explicit manual band/ATAS operator handoff after cross-band success
- Standard Com Port remaining unopened
- no PTT, MOX, keying, tuner, power, or unattended transmit authority

The approved receive-tuning order is:

```text
best-effort regular-memory band context when crossing bands
selected-memory verification
recalled-frequency target-band verification
exact frequency setting
exact frequency verification
mode setting when needed
mode verification
manual SET BAND / TUNE ATAS operator handoff after cross-band success
```

Successful memory recall is not treated as authoritative FT-891 front-panel band
selection. That behavior is parked in issue #149 for a future firmware/CAT
revisit.

### Phase C: Mapping and Operating Intelligence

Status: first live-map slice complete and approved through pull request #121.

The current first slice provides:

- north-up live map in the right-side situational area
- latest valid GPS position centered at a typed fixed zoom
- prominent current or last-known vehicle marker
- Maidenhead grid, coordinates, GPS state, and map-data state
- explicit waiting, stale, last-known, cache-only, partial, and unavailable
  presentation
- one bounded background worker for map HTTP/cache work
- validated atomic raster-tile cache with configured bounds
- on-demand visible-tile retrieval
- global ticker through priority-arbitrated immutable status snapshots
- no Home Station Platform dependency
- no radio or transmit-control changes

Still deferred:

- panning or zoom controls
- movement trail, heading, or speed arrow
- contact visualization
- persistent POTA markers
- routing, repeaters, weather radar, and analytics
- automatic zoom
- packaged regional offline maps, MBTiles, or vector tiles
- persisted location history
- broad dashboard redesign

## Cross-Cutting Architecture Work

The v4.1.0 architecture specification defines Station State as the unified
operational read model consumed by the UI and dependent services. This boundary
continues to be added incrementally around implemented radio, voice, logging,
storage, context, health, GPS, connectivity, shared spots, physical input, and
mapping capabilities.

The runtime owns a thread-safe immutable status-message service. Routine status,
shared tuning status, and the cross-band manual band/ATAS-120 reminder publish
through replacement keys, priority arbitration, and bounded expiration.

An in-process event bus remains an architectural direction rather than a reason
to retrofit completed services prematurely.

## Shared POTA/DX Spot Architecture

Status: checkpoint 8 implementation, Forge production deployment, and installed
FT-891/shared-control physical acceptance are complete on the feature branch;
documentation review, final quality gates, pull-request review, CI, owner
approval, and merge remain.

GitHub issue #129 checkpoints 1 through 8 now provide:

- provider-neutral immutable POTA/DX records and canonical snapshots
- stable identity-based selection
- exact action-critical `StagedSpotAction` values
- Forge POTA and configurable DXSpider aggregation
- optional bounded Forge-side QRZ enrichment
- transactional Forge persistence and versioned read-only REST
- typed Pi Forge client and durable retained shared snapshots
- one shared POTA/DX controller and presentation path
- independent POTA/DX band and mode filter state
- supported shared bands 80/40/20/17/15/12/10 meters
- shared mode groups SSB/CW/FT4/FT8/DATA/ALL
- POTA age filtering without leaking that rule into DX
- current-radio-band activation default with 20-meter fallback
- exact two-press shared receive tuning
- first activation stages only and performs no CAT
- second activation submits only the same still-valid staged target
- staging invalidation on selection, context, filter, disappearance,
  action-critical mutation, Back/Cancel, or invalid radio state
- background shared receive tuning outside Tkinter
- `ReceiveTuningService` as the sole receive-tuning authority
- timed success/failure status and 10-second cross-band manual band/ATAS reminder
- no duplicate Pi-side public-POTA polling while Forge is enabled
- local SQLite contact logging remaining authoritative
- no new radio transmit authority

The shared execution path is:

```text
installed control / keyboard
    -> operator command
    -> shared active-panel controller
    -> background shared tune controller
    -> ReceiveTuningService
    -> typed Radio
```

No POTA- or DX-specific CAT executor is part of the checkpoint-8 path.

## Forge Production Deployment

Status: complete and live on Forge.

Checkpoint 8 converted the temporary bench process into a supported systemd
service:

- dedicated service account `rollingthunder`
- application `/opt/rolling-thunder-forge`
- config `/etc/rolling-thunder/forge-spots.yaml`
- environment secrets `/etc/rolling-thunder/forge-spots.env`
- persistent database `/var/lib/rolling-thunder/forge-spots.db`
- listener `192.168.9.170:8766`
- systemd restart-on-failure with five-second delay
- active and enabled at boot
- journald diagnostics
- QRZ credentials excluded from YAML and Git
- private RadioLAN/CarLAN-over-WireGuard trust boundary documented
- no public port forward or UPnP assumption
- explicit rollback procedure

The production cutover verified the exact deployed code commit, dedicated
service UID, SQLite integrity, live healthy POTA and DX refreshes, process
identity, listener, and real Pi requests to `/api/v1/spots`.

See `docs/FORGE_DEPLOYMENT.md`.

## Current Checkpoint-8 Acceptance Work

Installed physical acceptance is complete.

Verified on `anvilmobile`:

1. POTA and DX filters and current-band/fallback behavior
2. first press stages without changing the radio
3. same-band POTA and DX second-press exact receive tuning
4. cross-band POTA and DX exact receive frequency/mode tuning
5. explicit manual `SET BAND TO <BAND> METERS — TUNE ATAS-120` handoff
6. staging invalidation for selection, band filter, mode filter, Back, and radio
   invalidation
7. radio disconnect/recovery without stale staged execution
8. Enhanced CAT ownership with the Standard TX-capable port closed
9. retained shared spots during controlled Forge interruption
10. isolated local SQLite logging while Forge is unavailable
11. production contact count unchanged by the isolated offline test
12. Forge recovery and cleanup after the controlled interruption
13. no PTT/MOX/keying/tuner/power/transmit path

The unresolved automatic FT-891 band-context behavior is non-blocking and
tracked in issue #149.

Remaining checkpoint-8 work:

1. finish documentation alignment
2. run Ruff, strict MyPy, full pytest, pre-commit, and `git diff --check`
3. prepare/review the checkpoint-8 pull request
4. require GitHub Actions success
5. remain unmerged until explicit repository-owner authorization

## Later Possibilities

- typed bidirectional ESP32 LED feedback
- Wavelog integration
- Maestro or Flex station detection
- enhanced contest workflows
- telemetry to Grafana
- remote-station status
- additional radio adapters
- mobile-safe audible prompts
