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

Status: complete for the current FT-891 scope.

- Typed radio interface
- Deterministic mock radio
- Frequency and mode readout
- Band change and frequency setting
- Connection-state reporting
- FT-891 CAT adapter
- Safe handling of disconnects and malformed replies
- Background radio polling outside the UI thread

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

Status: complete and audited for the approved roadmap scope.

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

Live receiver validation remains an operational smoke test rather than an
automated-test requirement. The broader v4.1.0 architecture also describes
trusted GPS UTC, speed and heading, stationary/moving hysteresis, and commit-time
GPS capture. Those capabilities remain architecture-aligned follow-up work and
are not implied by completion of this focused roadmap milestone.

## Milestone 7: Home Station Platform Connectivity

- Typed remote API interface
- health and reachability checks
- queued synchronization
- retry with backoff
- idempotent contact upload
- visible online/offline state
- network failures never block local logging

## Milestone 8: POTA Assistance

- Retrieve or receive POTA spots
- filter and rank spots
- frequency and mode display
- assisted tuning through the radio interface
- safeguards against unintended tuning
- local cache for temporary outages

## Milestone 9: Physical Controls

Voice callsign capture is already implemented. Remaining work in this milestone
is the physical control surface and its safe application integration.

- ESP32 button and LED interface
- configuration-driven input mappings
- mock controls for development
- physical Voice, Commit, and Discard controls
- direct context-selection buttons
- driver-distraction and error safeguards

## Milestone 10: Mapping and Operating Intelligence

- map screen
- current location
- contact visualization
- POTA locations
- station status
- selected Home Station Platform-assisted analytics
- cached behavior where practical

## Cross-Cutting Architecture Work

The v4.1.0 architecture specification defines Station State as the unified
operational read model consumed by the UI and dependent services. This boundary
is being added incrementally around the already implemented radio, voice,
logging, storage, context, and health capabilities before more state-producing
subsystems are introduced.

An in-process event bus remains an architectural direction, not a requirement to
retrofit prematurely. Its implementation should be driven by demonstrated
service-coordination needs while preserving the current safe Tkinter and worker-
thread boundaries.

## Later Possibilities

- Wavelog integration
- Maestro or Flex station detection
- enhanced contest workflows
- telemetry to Grafana
- remote-station status
- additional radio adapters
- mobile-safe audible prompts

## Immediate Next Feature

Begin Milestone 7 with the smallest Home Station Platform connectivity slice: a
typed, transport-independent remote API boundary and deterministic mock client.
The slice must define request, response, availability, and error contracts
without performing network I/O, starting retry loops, uploading contacts, or
coupling the UI to a particular server implementation.
