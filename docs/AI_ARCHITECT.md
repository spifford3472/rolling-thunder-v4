# Rolling Thunder v4 AI Architecture Guide

## Purpose

This document is the durable engineering playbook for AI-assisted development
of Rolling Thunder v4. It supplements `AGENTS.md` and explains the product
vision, architecture, safety rules, development workflow, ownership model, and
current technical direction.

Any AI assistant, coding agent, or human contributor making architectural or
implementation changes must treat the repository as the source of truth and
read the required documents before proposing code.

## Required Reading Order

At the beginning of a new development session, read these files from the active
repository and branch:

1. `AGENTS.md`
2. `docs/AI_ARCHITECT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/ROADMAP.md`
5. `CONTRIBUTING.md`
6. `docs/RollingThunder_v4.1.0_Architecture_Specification.md`

Then read every file those documents explicitly identify as relevant to the
current task. For the current product state, that commonly includes:

- `config/rolling-thunder.example.yaml`
- `docs/POTA_ENRICHMENT.md`
- `firmware/esp32-controls/README.md`
- the source modules and tests named by the applicable roadmap phase
- any open GitHub issue or merged pull request referenced by the documentation

Do not rely on a prior chat summary when it conflicts with the repository. Do
not assume a feature is missing or complete until the current code, tests,
documentation, issues, and pull requests have been inspected.

## Repository and Working Environment

Authoritative GitHub repository:

```text
spifford3472/rolling-thunder-v4
```

Primary development host:

```text
anvilmobile
```

Local repository:

```text
/home/geoff/projects/rolling-thunder-v4
```

Python virtual environment:

```text
.venv
```

The AI assistant can access the connected GitHub repository and should use that
access to inspect files, issues, pull requests, CI status, and repository history
instead of asking the owner to paste information already available through
GitHub.

When local hardware state, serial devices, working-tree changes, or full-screen
behavior cannot be observed through GitHub, provide a precise command block for
the owner to run on `anvilmobile` and evaluate the returned output.

## Project Vision

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system.
Its primary client runs on `anvilmobile`. Forge may provide Home Station Platform
APIs and heavier processing, but the Pi client must remain useful when Forge,
WireGuard, cellular service, or the public internet is unavailable.

The product should help the operator safely and efficiently:

- discover stations
- select useful POTA opportunities
- tune the receiver through explicit safe actions
- capture a callsign
- attempt a QSO
- commit a successful contact
- discard an unsuccessful pending callsign
- maintain location and station awareness

The software exists to reduce operator workload. Technology that does not serve
safe operating, logging, recovery, or situational awareness should not be added
merely because it is interesting.

## Product Priorities

When priorities conflict, prefer this order:

1. Operator and driving safety
2. No software transmission authority
3. Preservation of contact data
4. Reliable offline operation
5. Predictable and visible failure behavior
6. Clear architectural boundaries
7. Testability
8. Maintainability
9. Mobile usability
10. Performance
11. Development speed

A faster implementation is not better when it creates hidden coupling, hardware
dependence, unsafe radio authority, or fragile recovery behavior.

## AI Leadership Role

The AI assistant acts in two complementary roles.

### Chief Software Architect

Responsibilities include:

- protect the long-term architecture
- maintain domain, application, UI, hardware, persistence, and network boundaries
- prevent direct hardware or network access from Tkinter callbacks
- preserve local-first logging and graceful degradation
- identify safety, security, concurrency, and recovery risks
- challenge designs that create parallel command paths or hidden authority
- document important architectural decisions
- keep the roadmap aligned with implemented reality
- make technical debt explicit rather than silently normalizing it

### Senior Technical Lead and Implementer

Responsibilities include:

- inspect the repository and GitHub history before proposing changes
- translate milestones into the smallest clean implementation slices
- create focused branches rather than changing `main`
- implement code, tests, configuration examples, and documentation
- run or verify Ruff, MyPy, pytest, pre-commit, and GitHub Actions
- open focused draft pull requests with clear validation and limitations
- diagnose failures methodically from logs and evidence
- provide exact hardware-test procedures for `anvilmobile`
- incorporate owner feedback and revise the pull request
- avoid requiring the owner to perform routine coding work the assistant can do

The assistant should not hand the owner a large code-generation prompt and then
step away. It should actively handle design, coding, tests, documentation, GitHub
work, and PR iteration within the available tools.

## Owner Review and Approval Role

The repository owner remains the final product and safety authority.

For larger changes, especially hardware, full-screen UI, radio, GPS, speech, or
physical-control changes, the owner should:

- run the supplied live test on `anvilmobile`
- describe or photograph the observed behavior
- approve or reject user-visible behavior
- request corrections when the implementation does not match actual operation
- explicitly approve the pull request before merge
- perform or authorize the merge

The AI assistant must not treat passing automated tests as a substitute for live
hardware or in-vehicle presentation validation. It must also not ask for
repeated confirmation of routine implementation steps once the task and scope
are clear.

## Engineering Philosophy

Treat Rolling Thunder v4 as production-quality software.

Prefer:

- typed interfaces and immutable state
- dependency injection
- deterministic mocks and fakes
- explicit lifecycle ownership
- small focused modules and pull requests
- durable local storage
- bounded work and timeouts
- observable degraded and error state
- provider-independent application logic
- incremental hardware integration
- documentation that reflects the current code

Avoid:

- hidden global state
- direct hardware access from UI code
- hard-coded device paths scattered across modules
- blocking I/O in the UI thread
- business policy inside serial or HTTP adapters
- network-dependent core logging
- broad catch-all exception handling
- large speculative frameworks
- untested hardware-dependent application logic
- direct ESP32-to-radio authority
- voice-originated unattended tuning
- PTT, MOX, keying, or transmit commands
- broad rewrites when a small vertical slice will work

Use the simplest design that preserves the required safety and architectural
boundaries.

## Current Implemented Product State

The repository is no longer at the initial foundation stage. The implemented and
audited system includes:

- typed YAML configuration and example configuration
- validated domain and value types
- durable SQLite contact logging and recovery/export support
- pending-callsign Voice, Commit, and Discard workflow
- typed `Radio` and CAT transport boundaries
- deterministic mock radio and FT-891 CAT adapter
- typed `GPSReceiver`, mock GPS, serial NMEA adapter, and background polling
- full-screen Tkinter dashboard and context navigation
- first live GPS map slice with stale and last-known presentation
- bounded raster-tile retrieval and validated local cache
- station-health and connectivity presentation
- Home Station Platform health, queued synchronization, durable retries, and
  network keepalive
- POTA retrieval, filtering, ranking, selection, receive-only tune intent, and
  persistent cache
- asynchronous QRZ, weather, local-time, U.S. state, and DX boundary enrichment
- timed POTA park-detail overlay with park marker and operator photo/badge
- typed physical-control actions, mappings, mock and serial sources
- strict `RTCTRL/1 EVENT` parser and complete ESP32 panel firmware
- Voice, Commit, Discard, Panel, Context, and encoder integration through shared
  operator commands
- automated CI and pre-commit quality gates

Milestone 9 is complete for the approved physical-input scope. The ESP32 link is
intentionally one-way from ESP32 to Pi. Bidirectional LED feedback is not
implemented and is a later typed output enhancement, not hidden unfinished input
work.

## Architectural Boundaries

### Domain

The domain layer contains stable project concepts and validation rules, such as:

- callsign and Maidenhead grid
- contact and synchronization state
- frequency, band, and radio mode
- radio and GPS state
- POTA spot, park, and tune intent
- immutable service and presentation snapshots

Domain code must not depend on GUI frameworks, serial libraries, audio
libraries, HTTP clients, SQLite details, Raspberry Pi packages, or Forge
availability.

### Application Services and Controllers

Application code coordinates use cases, including:

- recording or discarding a pending callsign
- displaying radio and GPS state
- requesting map viewports and presenting immutable cached map state
- selecting and confirming POTA receive tuning
- synchronizing pending contacts
- dispatching physical input through approved operator commands
- requesting background enrichment and presenting cached state
- handling online, offline, stale, degraded, and error transitions

Application services depend on typed ports rather than concrete hardware or
network implementations.

### Ports and Interfaces

External capabilities are represented by small typed boundaries. Current
examples include:

- `Radio`
- `CatTransport`
- `GPSReceiver`
- `ControlSource`
- repositories
- remote platform and enrichment providers

Interfaces expose capabilities required by Rolling Thunder. They must not expose
raw vendor power or bypass application safeguards.

### Adapters

Adapters implement ports using real or simulated resources, including:

- FT-891 CAT
- serial GPS
- ESP32 serial controls
- mock radio, GPS, and controls
- SQLite repositories
- Home Station Platform HTTP
- POTA, QRZ, Open-Meteo, Census, and geoBoundaries HTTP clients

Device paths, baud rates, protocol parsing, and transport exceptions belong in
configuration, factories, and adapters only.

### User Interface

The UI presents state and invokes application controllers. It must not:

- open serial devices
- capture or parse hardware protocols directly
- issue raw CAT commands
- execute blocking HTTP requests
- own database implementation details
- decide retry or synchronization policy
- create special authority for physical buttons

## Local-First and Offline Requirements

At minimum:

1. A completed contact is written immediately to local durable storage.
2. No contact is written before explicit Commit.
3. Unsynchronized contacts remain locally identifiable.
4. Network failure never loses a completed local contact.
5. Synchronization resumes later without duplicate upload.
6. Forge unavailability does not prevent basic logging.
7. Public enrichment failure does not prevent POTA selection or logging.
8. Temporary radio, GPS, speech, or ESP32 loss does not crash the application.
9. Online, offline, stale, degraded, disabled, and error state is visible.

Remote services enhance the Pi client. They do not become hidden prerequisites
for local operation.

## Hardware Development Pattern

Every hardware capability should normally be developed in this sequence:

1. Read the architecture, roadmap, configuration, current adapter, tests, and
   relevant GitHub issue or prior PRs.
2. Observe the real device safely before changing behavior when observation is
   needed to establish protocol facts.
3. Define or confirm the smallest useful typed interface.
4. Preserve or create a deterministic mock or fake.
5. Write application and failure-case tests against the boundary.
6. Implement or refine the physical adapter.
7. Keep blocking hardware work outside Tkinter.
8. Add explicit startup, timeout, malformed-data, disconnect, and recovery
   behavior.
9. Open a focused draft PR.
10. Ask the owner to perform a precise hardware test on `anvilmobile`.
11. Incorporate the result, update documentation, and obtain owner approval
    before merge.

Do not combine unrelated hardware devices in the same first integration pull
request.

## Radio Safety Rules

These are permanent constraints:

- no software PTT
- no MOX
- no CW keying
- no voice keying
- no unattended transmit
- no voice command may directly tune or transmit
- no ESP32 event may name a raw CAT command
- physical controls use the same application-command and confirmation boundaries
  as the UI
- receive-only tuning must require the existing explicit operator intent and
  confirmation flow
- radio state in the current scope remains `transmitting=False`

A proposal that violates these rules must be rejected or redesigned.

## Physical-Control Rules

The ESP32 reports opaque, versioned events. The Pi maps those identifiers to a
closed `ControlAction` vocabulary.

Required safeguards include:

- strict protocol parsing
- bounded reads and event counts
- duplicate-event rejection
- rapid-repeat suppression
- unknown input rejection
- configuration validation
- nonblocking dispatch
- safe startup failure
- shared application-command routing

The current link is input-only. Future LED feedback must use a typed output port,
explicit state-to-feedback policy, bounded writes, reconnection handling, and
mock tests. Do not mix output commands into the existing input event parser.

## Concurrency and Reliability

Potentially blocking work must not run in the Tkinter thread, including:

- CAT and GPS serial operations
- speech capture and recognition
- HTTP requests and image normalization
- map tile retrieval, validation, and cache I/O
- synchronization and retries
- database maintenance
- long calculations

Every worker or polling service must define:

- lifecycle owner
- startup and shutdown sequence
- timeout behavior
- cancellation or stop behavior
- stale-state rules
- device-loss behavior
- retry or recovery policy
- bounded work
- observable errors

An in-process event bus remains a long-term direction, not a reason for a broad
retrofit. Add it only when a demonstrated coordination problem justifies it.

## Configuration and Secret Handling

Configuration is typed, validated, centralized, and test-constructible.
Machine-specific paths belong in local YAML. Safe example values belong in
`config/rolling-thunder.example.yaml`.

Never commit or display:

- passwords
- API keys
- access tokens
- private keys
- QRZ session keys
- authentication responses
- personal credentials

Optional QRZ credentials are loaded through the centralized application-secrets
boundary from a local environment file. Do not scatter environment lookups
through feature modules.

## Git and Pull-Request Workflow

Never develop directly on `main`.

Use one focused branch for one logical change:

```text
feature/<short-description>
fix/<short-description>
docs/<short-description>
```

The AI assistant should normally:

1. verify repository, branch, and working-tree state
2. inspect applicable issues, pull requests, documentation, code, and tests
3. propose the smallest clean slice
4. create or instruct creation of the focused branch
5. implement code, tests, configuration examples, and documentation
6. run or verify:

   ```bash
   ruff check src tests
   mypy src
   pytest
   pre-commit run --all-files
   ```

7. push the branch and open a draft pull request
8. inspect GitHub Actions and correct failures
9. provide a focused live-test procedure
10. keep the PR in draft until significant hardware or UI behavior is approved
11. request explicit owner approval before merge

The owner should not be asked to manually write routine production code that the
assistant can implement. The owner should be asked to test real hardware,
validate operator experience, and make merge decisions.

## Documentation Expectations

Update documentation whenever a change affects:

- architecture
- roadmap status
- configuration
- setup and deployment
- hardware wiring or device selection
- operator workflow
- external provider behavior
- security or secret handling
- troubleshooting and recovery
- known limitations

Important decisions must live in the repository rather than only in a chat.
Documentation must distinguish implemented behavior, validated hardware
behavior, deferred work, and long-term architectural direction.

## Current Development Direction: Milestone 10

Milestone 10 is `Hardware-Backed Mapping and Operating Intelligence` and must be
executed in separate phases.

### Phase A: Real GPS Integration

Start with GitHub issue #10, `Implement real GPS provider`.

Before coding:

- inspect the actual issue and current repository state
- read `GPSReceiver`, `SerialGPSReceiver`, GPS polling, configuration, runtime,
  Station State, dashboard integration, and all GPS tests
- observe the connected receiver's stable device path, permissions, baud rate,
  and emitted NMEA sentence mix on `anvilmobile`

The first GPS PR should be the smallest live-hardware slice. It should establish
safe startup and read-only current position through the existing typed boundary.
Preserve mock mode. Add sentence support only when the real receiver demonstrates
that it is needed. Validate fix state, position, grid, loss, reacquisition, and
visible status. Update setup and recovery documentation.

Do not include FT-891 changes in the GPS branch.

### Phase B: Real Yaesu FT-891 Integration

After the GPS PR is approved and merged, use a separate branch and PR for the
installed FT-891.

Begin with:

- stable CAT device identity and permissions
- correct serial settings
- read-only connection
- current frequency and mode
- background polling
- disconnect and recovery

Only after read-only behavior is approved should the same focused effort validate
explicit receive-only frequency, mode, band, and confirmed POTA tuning. Preserve
the typed `Radio` and `CatTransport` boundaries and the mock radio. Add no PTT,
MOX, keying, or unattended transmit authority.

### Phase C: Mapping and Operating Intelligence

After real GPS and radio state are reliable, expand:

- live current-location mapping
- movement presentation
- contact visualization
- POTA locations and details
- station and connectivity status
- selected Home Station Platform-assisted analytics
- caching and offline behavior

Do not design Phase C around unproven hardware assumptions.

## Definition of Done

A feature is complete when all applicable criteria are satisfied:

- requested behavior works
- architecture remains clean
- no safety boundary is weakened
- application logic remains testable without hardware
- mocks and fakes remain usable
- normal and important failure behavior is tested
- Ruff passes
- MyPy passes
- pytest passes
- pre-commit passes
- GitHub Actions passes
- relevant hardware or full-screen testing is completed on `anvilmobile`
- the owner approves significant user-visible or hardware behavior
- offline behavior is preserved
- errors are actionable and visible
- secrets are not committed or exposed
- documentation and roadmap are updated
- assumptions, limitations, and deferred work are recorded
- the pull request is focused and reviewable

## New AI-Assisted Session Checklist

At the start of a new session:

1. Confirm the repository is `spifford3472/rolling-thunder-v4`.
2. Confirm the local directory is `/home/geoff/projects/rolling-thunder-v4`.
3. Read the required documents in the order listed at the top of this file.
4. Follow links and file references in those documents that apply to the task.
5. Use connected GitHub access to inspect the current issue, PR history, code,
   tests, and CI rather than relying on memory.
6. Confirm the active branch and working tree before changing anything.
7. Act as Chief Software Architect, Senior Technical Lead, and implementer.
8. Keep work in small focused branches and draft pull requests.
9. Handle coding, tests, documentation, CI corrections, and PR preparation.
10. Have the owner test and approve larger hardware and UI changes before merge.
11. Treat the repository as more authoritative than previous chat summaries.
12. Begin Milestone 10 with real GPS only; do not combine the initial GPS work
    with FT-891 changes.
