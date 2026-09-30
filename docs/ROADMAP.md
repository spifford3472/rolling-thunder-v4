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

- typed application configuration model
- local YAML loading and validation
- callsign, grid, URL, path, and mode validation
- mock-hardware mode
- clear configuration errors
- automated tests
- example configuration without secrets

## Milestone 2: Core Domain Models

Status: complete and audited.

- contact model
- frequency and radio-mode types
- radio-state model
- GPS-position model
- synchronization-state model
- callsign and grid validation
- serialization boundaries with tests

## Milestone 3: Local Contact Logging

Status: complete and audited.

- SQLite-backed contact repository
- create and retrieve contacts
- pending/synchronized status
- duplicate-protection strategy
- durable writes
- export and recovery support
- tests using temporary databases

## Milestone 4: Radio Abstraction

Status: complete for the current FT-891 software scope.

- typed `Radio` and `CatTransport` boundaries
- deterministic mock radio
- frequency and mode readout
- band-context handling and frequency setting
- connection-state reporting
- FT-891 CAT adapter
- safe disconnect/malformed-reply handling
- background radio polling outside the UI thread

The installed Yaesu FT-891 integration is validated through the typed `Radio`
and `ReceiveTuningService` boundaries. The approved scope remains receive-only
and contains no PTT, MOX, keying, tuner, power, automatic transmit, or unattended
transmit authority.

## Milestone 5: Basic Pi User Interface

Status: substantially complete for the current mobile-logging slice.

- full-screen Raspberry Pi application shell
- direct navigation among primary contexts
- live radio status area
- pending-callsign Voice workflow
- explicit Commit and Discard controls
- durable local contact commits
- large high-contrast in-vehicle presentation
- station-health presentation
- no blocking radio, voice, storage, map, or network work in the UI thread

Remaining Milestone 5 work should remain focused architecture-aligned integration
and usability refinement rather than a broad dashboard rewrite.

## Milestone 6: GPS and Location

Status: complete and audited for the approved current-position scope.

- typed GPS interface
- deterministic mock GPS source
- serial NMEA adapter
- Maidenhead grid calculation
- current position display
- speed and heading capture from the installed mixed-NMEA stream
- live-map heading presentation with stopped-vehicle heading retention
- graceful loss and reacquisition of GPS
- independent background polling and automatic recovery

Commit-time GPS capture is implemented: a current valid fix is converted to a
six-character mobile-station grid and stored separately from the contacted
station grid. GPS loss or stale data leaves that field empty without preventing
local Commit.

Trusted GPS UTC suitable for host-clock verification/synchronization remains a
follow-up capability under issue #158 and #159.

## Milestone 7: Home Station Platform Connectivity

Status: complete and audited for the approved roadmap scope.

- typed remote API interface
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
keepalive configuration/service, runtime composition, and pure connectivity
presentation state.

## Milestone 8: POTA Assistance and Shared POTA/DX Spots

Status: complete for the current shared-spot architecture.

The original POTA-only path established typed POTA retrieval/cache, filtering,
ranking, selection, POTA contact-context metadata, and enrichment. The later
shared POTA/DX work supersedes the POTA-only live-provider path when Forge is
enabled.

GitHub issue #129 checkpoints 1 through 8 are complete and merged. PR #150
completed the final shared POTA/DX receive-tuning and Forge-deployment slice.

The completed shared path provides:

- provider-neutral immutable POTA/DX records and canonical snapshots
- stable identity-based selection
- Forge POTA and configurable DXSpider aggregation
- optional bounded Forge-side QRZ enrichment
- transactional Forge persistence and versioned REST
- typed Pi Forge client and durable retained shared snapshots
- one shared POTA/DX controller and presentation path
- independent POTA/DX band and mode filter state
- supported shared bands 80/40/20/17/15/12/10 meters
- shared mode groups SSB/CW/FT4/FT8/DATA/ALL
- POTA age filtering without leaking that rule into DX
- current-radio-band activation default with 20-meter fallback
- single-press shared receive tuning from the current stable selection
- activation snapshots exact identity/callsign/frequency/mode and submits it through
  the background typed tuning path
- stale/disappeared selections and unusable radio state fail closed
- duplicate rapid activations are rejected while tuning is already active
- background shared receive tuning outside Tkinter
- `ReceiveTuningService` as the sole receive-tuning authority
- timed success/failure status and 10-second cross-band manual band/ATAS reminder
- no duplicate Pi-side public-POTA polling while Forge is enabled
- local SQLite contact logging remaining authoritative
- no new transmit authority

The shared execution path is:

```text
installed control / keyboard
    -> operator command
    -> shared active-panel controller
    -> background shared tune controller
    -> ReceiveTuningService
    -> typed Radio
```

No POTA- or DX-specific CAT executor is part of the accepted path.

## Milestone 9: Physical Controls

Status: complete and audited for the approved physical-input scope.

- typed transport-independent control actions/input events
- configuration-driven mappings from opaque ESP32 identifiers to approved
  application actions
- deterministic mock control source
- strict versioned `RTCTRL/1 EVENT` parser
- bounded nonblocking pyserial control source
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

Status: complete and approved for current-position/speed/heading behavior.

- stable real GPS device identity and permissions
- actual 9,600-baud mixed-NMEA receiver behavior
- typed `GPSReceiver` boundary and mock source preserved
- live position, fix state, Maidenhead grid, speed, heading, loss, reacquisition,
  and UI status
- background serial work and automatic recovery
- setup, troubleshooting, and recovery documentation

Trusted GPS UTC and GPS-assisted host clock synchronization are intentionally
separate follow-up checkpoints #158 and #159.

### Phase B: Real Yaesu FT-891 Integration

Status: complete for the approved receive-only architecture and shared POTA/DX
installed-hardware acceptance.

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

Rolling Thunder v4.3 Checkpoint 6 completed the separate supervised FT8
hardware-validation track using Enhanced-CAT `TX1;`/`TX0;`, bounded left-only
DigiRig playback, watchdog release, and explicit frequency/mode verification.

Checkpoint 7 is now the experimental controlled-QSO integration track. It may
connect exactly one explicitly operator-selected CQ station to the validated
physical executor through a QSO-specific authorization, `DigitalTransmitSession`,
slot coordinator, normalized decode feed, and manual ABORT. The generic `Radio`
contract remains receive-side; UI, voice, ESP32, Forge/network services, POTA/DX
activity, and unrelated application paths receive no independent PTT authority.

Checkpoint 7 remains disabled by default behind both `ft8.enabled` and
`ft8.transmit.enabled`. It produces an immutable terminal QSO result but does
not yet write a successful contact to SQLite/Wavelog. Automatic next-station
selection, unattended CQ hunting, autonomous band hopping, and voice-controlled
FT8 transmission remain prohibited.

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
selection. That behavior remains parked in issue #149.

### Phase C: Mapping and Operating Intelligence

Status: complete for the current v4.2 map/POTA-marker scope.

The implemented map path now includes:

- north-up live map in the situational area
- latest valid GPS position centered in the viewport
- prominent current/last-known vehicle marker
- Maidenhead grid, coordinates, GPS state, and map-data state
- explicit waiting, stale, last-known, cache-only, partial, and unavailable
  presentation
- generation-aware viewport requests and stale-publication suppression
- one bounded queued viewport with newer work superseding obsolete work
- identical and same-tile-set request deduplication
- prompt publication of locally available tiles before online refresh completes
- progressive current-viewport publication
- incremental Tk canvas tile move/redraw/remove behavior
- retained canvas objects and bounded Tk `PhotoImage` reuse
- typed installed raster-MBTiles package discovery and priority
- local-first resolution: installed package -> runtime cache -> online provider
- authoritative installed coverage that does not silently require public internet
- offline DAY and NIGHT regional packages for Ohio, Indiana, Kentucky, Michigan,
  Pennsylvania, and West Virginia on the external RT_DATA SSD
- automatic solar DAY/NIGHT selection with manual override support
- persistent operator zoom through the supported installed-package range
- lightweight POTA catalog markers queried by visible viewport on a background
  worker
- yellow park labels with full reference/name at zoom 14 and above
- 24-pixel yellow/black park dots below zoom 14
- 60-second last-valid-GPS grace period for POTA marker stability
- safe empty-marker and disabled-radar canvas-layer handling
- map/POTA/radar failure isolation from GPS, logging, shared spots, controls,
  and radio state

The earlier PAD-US / park-boundary polygon plan is intentionally dropped from the
current roadmap. Approximate POTA catalog coordinates provide the desired operator
awareness without introducing GIS geometry, spatial-index, boundary-correlation, or
polygon-rendering complexity on the mobile platform. Future polygon work should not
be treated as an implied next phase; it would require a new explicitly approved use
case.

The old I-71 corridor package may remain as a small fallback artifact, but it is no
longer the primary offline map deployment.

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

## Forge Production Deployment

Status: complete and live for the current shared-spot service.

The supported deployment uses:

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
- private RadioLAN/CarLAN-over-WireGuard trust boundary
- no public port-forward or UPnP assumption
- explicit rollback procedure

The production path has been physically accepted from Forge through the Pi
shared POTA/DX panel and installed FT-891 controls. See
`docs/FORGE_DEPLOYMENT.md`.

## Approved Post-PR-152 Workstream

Umbrella issue #154 is the approved next development sequence. It is intentionally
split so map, GPS time, Forge weather, repeater data/UI, and FT-891 repeater CAT
do not become one broad implementation branch.

Sequence:

0. #155 — reconcile roadmap, architecture, and issue state
1. #156 — map information box and explicit MAP/GPS health
2. #157 — persistent Map Zoom operator setting
3. #158 — trusted GPS UTC observations
4. #159 — GPS-assisted Raspberry Pi clock synchronization
5. #160 — Forge mobile-location write API and retained domain
6. #161 — publish valid Pi GPS fixes to Forge
7. #162 — retained Forge weather domain, provider, and API
8. #164 — Pi retained weather client and immutable state
9. #165 — weather panel and map-temperature integration
10. #166 — 6 m repeater data, Active overrides, and geospatial filtering
11. #167 — 6 m repeater panel and operator Active controls
12. #168 — typed FT-891 FM repeater receive capabilities
13. #169 — typed 6 m repeater radio configuration integration (single-press activation now supersedes its original confirmation workflow)

Issue #163 is a parking-lot item for a future weather-radar map overlay and is not
part of the initial #154 completion sequence.

The workstream preserves these permanent rules:

- local SQLite contact logging remains authoritative
- Forge/weather/public internet failure never prevents basic logging
- Tkinter performs no blocking serial/network/filesystem/SQLite/CAT work
- provider-specific data is normalized behind typed provider-neutral boundaries
- receive-selection activation uses the current single-press typed application path
- radio work routes only through typed application/radio boundaries
- no PTT, MOX, keying, tuner, power, automatic transmit, voice-originated tuning,
  or unattended transmit authority
- significant installed display, GPS, Forge deployment, physical-control, and
  FT-891 behavior requires owner acceptance before merge

## v4.2 Callsign Information Overlay

Status: implementation in progress on PR #209; requires Forge/anvilmobile and
in-car physical acceptance before merge.

The feature adds an optional pending-callsign overlay with QRZ identity/QTH,
regional map, simple target weather, and Wavelog previous-QSO context. POTA park
coordinates take priority over QRZ home coordinates for the current activation.
No previous QSO is presented explicitly as FIRST CONTACT. Provider failures
remain outside Commit and produce no intrusive error overlay.

## Later Possibilities

- typed bidirectional ESP32 LED feedback
- Maestro or Flex station detection
- enhanced contest workflows
- telemetry to Grafana
- remote-station status
- additional radio adapters
- mobile-safe audible prompts
- movement trails, contact visualization, persistent POTA markers, and routing
  when justified by operator value and safe presentation
