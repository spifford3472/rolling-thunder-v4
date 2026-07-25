# Rolling Thunder v4 Roadmap

This roadmap describes intended sequencing. It is not a promise that every
feature will be implemented exactly as listed.

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

Status: next.

- Typed radio interface
- Deterministic mock radio
- Frequency and mode readout
- Band change and frequency setting
- Connection-state reporting
- FT-891 CAT adapter
- Safe handling of disconnects and malformed replies

## Milestone 5: Basic Pi User Interface

- Application shell
- navigation among primary screens
- radio status area
- basic manual logging
- large in-vehicle controls
- readable high-contrast layout
- no blocking work in the UI thread

## Milestone 6: GPS and Location

- Typed GPS interface
- mock GPS source
- serial GPS adapter
- Maidenhead grid calculation
- current position display
- graceful loss and reacquisition of GPS

## Milestone 7: Forge Connectivity

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

## Milestone 9: Voice and Physical Controls

- USB microphone abstraction
- test with the Jabra headset
- callsign speech-to-text workflow
- confidence and correction flow
- ESP32 button and LED interface
- mock controls for development
- driver-distraction and error safeguards

## Milestone 10: Mapping and Operating Intelligence

- map screen
- current location
- contact visualization
- POTA locations
- station status
- selected Forge-assisted analytics
- cached behavior where practical

## Later Possibilities

- Wavelog integration
- Maestro or Flex station detection
- enhanced contest workflows
- telemetry to Grafana
- remote-station status
- additional radio adapters
- mobile-safe audible prompts

## Immediate Next Feature

Begin Milestone 4 with a small focused slice that defines the typed radio
interface and deterministic mock radio. Build application behavior and tests
against that boundary before adding the FT-891 CAT adapter.
