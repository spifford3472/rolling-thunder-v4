# Rolling Thunder v4 AI Architecture Guide

> **Current-state note:** This document contains valuable historical design context, but it predates the current v4.4 engineering baseline. For current ownership, dependencies, shared-component contracts, Forge service rules, source/test catalogs, and agent guardrails, start with `AGENTS.md` and `docs/engineering/index.md`. When this document conflicts with the current code/tests or engineering guide, the current implementation and engineering guide are authoritative.

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
- `docs/LIVE_MAP.md`
- `docs/REAL_GPS_INTEGRATION.md`
- `docs/REAL_FT891_INTEGRATION.md`
- `docs/SHARED_SPOT_DOMAIN.md`
- `docs/PI_FORGE_CLIENT.md`
- `docs/FORGE_DEPLOYMENT.md`
- `firmware/esp32-controls/README.md`
- the source modules and tests named by the applicable roadmap checkpoint
- the current GitHub issue and any merged pull requests it depends on

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

- discover stations and operating opportunities
- select useful POTA, DX, and later repeater opportunities
- tune/configure the receiver through explicit safe actions
- capture a callsign
- attempt a QSO
- commit a successful contact
- discard an unsuccessful pending callsign
- maintain location, map, weather, connectivity, and station awareness

The software exists to reduce operator workload. Technology that does not serve
safe operating, logging, recovery, or situational awareness should not be added
merely because it is interesting.

## Product Priorities

When priorities conflict, prefer this order:

1. Operator and driving safety
2. No general or unattended software transmission authority
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

For larger changes, especially hardware, full-screen UI, radio, GPS, speech,
physical-control, Forge deployment, or system-time changes, the owner should:

- run the supplied live test on the applicable system
- describe or photograph the observed behavior where useful
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
- general-purpose PTT, MOX, keying, or transmit commands outside explicitly approved bounded capabilities
- broad rewrites when a small vertical slice will work

Use the simplest design that preserves the required safety and architectural
boundaries.

## Current Implemented Product State

The repository is well beyond the initial foundation stage. As of the
post-PR-152 baseline, implemented and audited behavior includes:

- typed YAML configuration and safe example configuration
- validated domain and value types
- durable SQLite contact logging, synchronization state, recovery, and export
- pending-callsign Voice, Commit, and Discard workflow
- typed `Radio` and `CatTransport` boundaries
- deterministic mock radio and installed FT-891 CAT adapter
- background radio polling, disconnect detection, and recovery
- typed `GPSReceiver`, mock GPS, serial mixed-NMEA adapter, and background polling
- live GPS position, Maidenhead grid, speed, heading, stale/last-known state, and
  automatic recovery
- full-screen Tkinter dashboard and context navigation
- station-health and connectivity presentation
- Home Station Platform health, queued synchronization, durable retries, and
  network keepalive
- runtime-owned generic thread-safe status-message arbitration
- typed physical-control actions, mappings, mock/serial sources, strict
  `RTCTRL/1 EVENT` parsing, and installed ESP32 panel firmware
- Voice, Commit, Discard, Panel, Context, and encoder integration through shared
  application/operator commands
- provider-neutral shared POTA/DX domain, stable selection, and exact staged
  action values
- Forge POTA/DXSpider aggregation, optional QRZ enrichment, transactional
  snapshots, versioned REST, and supported systemd production deployment
- typed Pi Forge background client, durable retained shared snapshots, and
  truthful cached/live/retained diagnostics
- one shared POTA/DX panel with independent band/mode filters
- single-press POTA/DX receive tuning through background execution and
  `ReceiveTuningService`
- explicit cross-band manual `SET BAND ... — TUNE ATAS-120` handoff where the
  FT-891 CAT behavior cannot authoritatively establish front-panel band context
- north-up live map with current/last-known vehicle marker and immutable
  map/GPS presentation state
- generation-aware/coalesced viewport requests and stale-publication suppression
- progressive local-first tile publication and incremental Tk rendering
- installed raster-MBTiles source/resolver architecture
- installed offline I-71 corridor package proven on `anvilmobile`
- source priority installed package -> runtime cache -> online provider ->
  unavailable
- amortized map-cache pruning rather than a full cache scan/sort after every
  successful tile write
- automated CI and pre-commit quality gates

The obsolete POTA park-detail overlay is removed. The current POTA and DX UI is
the shared spot panel; documentation or code that assumes the old overlay/live
provider-specific path must not be reintroduced.

Milestone 9 is complete for the approved physical-input scope. The ESP32 link is
intentionally one-way from ESP32 to Pi. Bidirectional LED feedback remains a
later typed output enhancement, not hidden unfinished input work.

## Architectural Boundaries

### Domain

The domain layer contains stable project concepts and validation rules, such as:

- callsign and Maidenhead grid
- contact and synchronization state
- frequency, band, and radio mode
- radio and GPS state
- shared spot identities/records/snapshots
- map coordinates, source metadata, and immutable presentation snapshots
- immutable service state suitable for safe cross-thread publication

Domain code must not depend on GUI frameworks, serial libraries, audio
libraries, HTTP clients, SQLite details, Raspberry Pi packages, or Forge
availability.

### Application Services and Controllers

Application code coordinates use cases, including:

- recording or discarding a pending callsign
- displaying radio and GPS state
- requesting map viewports and presenting immutable cached map state
- selecting and single-press shared receive tuning
- synchronizing pending contacts
- dispatching physical input through approved operator commands
- consuming already-published Forge/shared state
- handling online, offline, stale, retained, degraded, and error transitions

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
- map tile/package sources
- Home Station Platform clients
- Forge/shared-spot clients/providers

Future weather, system-clock, mobile-location publication, and repeater
capabilities must follow the same pattern. Interfaces expose only the authority
Rolling Thunder requires; they must not expose raw vendor power or bypass
application safeguards.

### Adapters

Adapters implement ports using real or simulated resources, including:

- FT-891 CAT
- serial GPS
- ESP32 serial controls
- mock radio, GPS, and controls
- SQLite repositories
- Home Station Platform HTTP
- Forge provider/client HTTP
- POTA, DXSpider, QRZ, Open-Meteo, Census, and geoBoundaries integrations where
  currently applicable
- raster MBTiles installed packages and online map fallback

Device paths, baud rates, protocol parsing, HTTP/provider details, and transport
exceptions belong in configuration, factories, and adapters only.

### User Interface

The UI presents immutable state and invokes application controllers. It must not:

- open serial devices
- capture or parse hardware protocols directly
- issue raw CAT commands
- execute blocking HTTP requests
- read/write SQLite directly
- perform map tile/package filesystem work
- own database implementation details
- decide retry, retention, or synchronization policy
- create special authority for physical buttons

## Local-First and Offline Requirements

At minimum:

1. A completed contact is written immediately to local durable storage.
2. No contact is written before explicit Commit.
3. Unsynchronized contacts remain locally identifiable.
4. Network failure never loses a completed local contact.
5. Synchronization resumes later without duplicate upload.
6. Forge unavailability does not prevent basic logging.
7. Public provider failure does not prevent basic logging or invalidate unrelated
   retained/local state.
8. Temporary radio, GPS, speech, ESP32, map, or Forge loss does not crash the
   application.
9. Online, offline, stale, retained, degraded, disabled, and error state is
   visible where relevant.
10. Installed offline map coverage does not silently require public internet.

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
10. Ask the owner to perform a precise hardware test on `anvilmobile` or the
    applicable production host.
11. Incorporate the result, update documentation, and obtain owner approval
    before merge.

Do not combine unrelated hardware devices or privilege boundaries in the same
first integration pull request.

## Radio Safety Rules

These are permanent constraints:

- no general-purpose software PTT or MOX capability
- no CW keying or voice keying
- no unattended transmit
- no voice command may directly tune or transmit
- no ESP32 event may name a raw CAT command or directly authorize transmit
- no network request may directly authorize transmit
- physical controls use the same application-command and confirmation boundaries
  as the UI
- operator-confirmed receive/repeater configuration must use typed application
  services and the typed `Radio` boundary
- a receive-selection press routes through the typed application service and never issues raw CAT from UI/control code
- the generic `Radio` contract remains receive-side and does not gain PTT, MOX,
  keying, or generic transmit methods

### v4.3 experimental FT8 exception

Checkpoint 6 may introduce one disabled-by-default, owner-initiated, physically
supervised, tightly bounded FT8 hardware-test transmit capability. This is a
narrow architecture exception for proving the FT-891 + DigiRig execution
boundary; it is not general software transmission authority.

During Checkpoint 6:

- only an explicit owner test harness may invoke the physical executor;
- `FT8QsoController` and its existing `DigitalTransmitSession` remain
  hardware-independent and must not be wired to RF;
- CQ activity, UI callbacks, voice, ESP32 controls, Forge, network requests, and
  logging have no physical transmit authority;
- exactly one verified PTT mechanism may be active;
- every key-down operation is bounded by cancellation, guaranteed release, and
  a maximum watchdog;
- disabling FT8 must create no playback, PTT, or transmit-executor resource.

Any broader automated FT8 QSO authority requires a later explicit architecture
checkpoint and owner approval. A proposal outside this narrow exception must be
rejected or redesigned.

The existing FT-891 cross-band limitation is also part of the safety contract:
regular-memory CAT recall is best-effort context only and must not be described
as authoritative front-panel band selection. Use the explicit manual band/ATAS
handoff until new physical evidence proves a safer typed capability.

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
- HTTP/provider requests and image normalization
- map tile retrieval, validation, package lookup, and cache I/O
- synchronization and retries
- database maintenance and preference persistence
- Forge publication/polling
- weather retrieval
- system-clock operations
- long calculations

Every worker or polling service must define:

- lifecycle owner
- startup and shutdown sequence
- timeout behavior
- cancellation or stop behavior
- stale-state rules
- device/provider-loss behavior
- retry or recovery policy
- bounded work
- observable errors

An in-process event bus remains a long-term direction, not a reason for a broad
retrofit. Add it only when a demonstrated coordination problem justifies it.

## Configuration and Secret Handling

Configuration is typed, validated, centralized, and test-constructible.
Machine-specific paths belong in local YAML. Safe example values belong in
`config/rolling-thunder.example.yaml`.

Operator preferences that change through the running UI should normally use a
typed persistence boundary rather than rewriting YAML from Tkinter/application
controllers.

Never commit or display:

- passwords
- API keys
- access tokens
- private keys
- QRZ session keys
- authentication responses
- personal credentials

Optional credentials are loaded through centralized secret/environment
boundaries. Do not scatter environment lookups through feature modules.

## Git and Pull-Request Workflow

Never develop directly on `main`.

Use one focused branch for one logical change. Existing repository conventions
may use `feature/`, `fix/`, `docs/`, or automation-specific `agent/` branches,
but the branch must remain single-purpose and reviewable.

The AI assistant should normally:

1. verify repository, branch, and working-tree/remote state
2. inspect applicable issues, pull requests, documentation, code, and tests
3. propose the smallest clean slice
4. create the focused branch
5. implement code, tests, configuration examples, and documentation
6. run or verify:

   ```bash
   ruff check src tests
   mypy src
   pytest
   pre-commit run --all-files
   git diff --check
   ```

7. push the branch and open a draft pull request
8. inspect GitHub Actions and correct failures
9. provide a focused live-test procedure when hardware/UI/deployment is involved
10. keep the PR unmerged until significant hardware/UI behavior is approved
11. request explicit owner authorization before merge

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

GitHub issue bodies must also be reconciled when their original baseline is
superseded by merged work; an open umbrella issue must not continue to describe
completed checkpoints as future implementation.

## Current Development Direction: Milestone 10

Milestone 10 remains `Hardware-Backed Mapping and Operating Intelligence`, but
the original GPS-first/radio-second development guidance has been completed.
Do not restart those original phases as if the repository were still at its
pre-hardware baseline.

### Phase A: Real GPS Integration

Status: complete for installed current-position, speed, heading, loss, recovery,
and live-map use.

Follow-up GPS time work is intentionally separate:

- #158 adds trusted GPS UTC observations without changing the OS clock
- #159 adds bounded least-privilege GPS-assisted Pi clock verification/sync only
  after the real `anvilmobile` time-service/polkit state is inspected

### Phase B: Real Yaesu FT-891 Integration

Status: complete for the approved receive-only and shared POTA/DX scope.

The installed path includes read-only polling, exact receive frequency/mode
changes, shared single-press tuning, disconnect/recovery safety, and the manual
cross-band band/ATAS handoff. Issue #149 retains the unresolved automatic
front-panel band-context question.

Future six-meter repeater work must first prove each additional FT-891 FM/
repeater CAT capability in isolation under #168 before panel integration under
#169. Unsupported or unverifiable behavior must remain an explicit operator
handoff.

### Phase C: Mapping and Operating Intelligence

Status: active.

Issue #124 remains the map-specific umbrella for:

- broad Ohio and surrounding-state offline packages
- deterministic automatic day/night policy
- typed manual day/night override
- separate operating-overlay provider/snapshot architecture
- future PAD-US boundary work

The local-first foundation is already implemented through PRs #125, #126, #127,
and #152 and must be reused rather than rebuilt.

### Approved Post-PR-152 Workstream

Umbrella issue #154 defines the next approved sequence:

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
13. #169 — typed 6 m repeater radio configuration integration; later single-press operator activation supersedes its confirmation workflow

Issue #163 is a parking-lot item for future weather-radar map overlays and is not
part of the initial #154 completion sequence.

The sequence is intentional. Do not collapse the GPS trust/OS privilege boundary,
Forge write/weather boundary, repeater data/UI boundary, or FT-891 capability/
integration boundary into one large pull request.

## Callsign Information Guidance

Pending-callsign identity/history/weather enrichment is optional operator
intelligence and must remain outside durable Commit. The Pi may request one
bounded background lookup from the independent Forge callsign-info service, but
Tkinter must only consume immutable published state.

POTA park coordinates override QRZ home coordinates for the current-contact
mini-map and target weather. QRZ profile photographs are not used by this
feature. A missing previous Wavelog QSO is presented explicitly as FIRST CONTACT.

Late responses must be generation-checked against the current pending callsign,
and provider/network failure must produce no intrusive overlay.

See `docs/CALLSIGN_INFO.md`.

## Definition of Done

A feature is complete when all applicable criteria are satisfied:

- requested behavior works
- architecture remains clean
- no safety boundary is weakened
- application logic remains testable without hardware
- mocks and fakes remain usable
- normal and important failure behavior is tested
- Ruff passes
- strict MyPy passes
- pytest passes
- pre-commit passes
- `git diff --check` passes
- GitHub Actions passes
- relevant hardware, Forge, system-time, or full-screen testing is completed on
  the applicable real system
- the owner approves significant user-visible, deployment, privilege, or hardware
  behavior
- offline behavior is preserved
- errors are actionable and visible
- secrets are not committed or exposed
- documentation and roadmap are updated
- assumptions, limitations, and deferred work are recorded
- the pull request is focused and reviewable
- no merge occurs without explicit repository-owner authorization

## New AI-Assisted Session Checklist

At the start of a new session:

1. Confirm the repository is `spifford3472/rolling-thunder-v4`.
2. Confirm the intended local directory is `/home/geoff/projects/rolling-thunder-v4`.
3. Read the required documents in the order listed at the top of this file.
4. Follow links and file references in those documents that apply to the task.
5. Use connected GitHub access to inspect the current issue, PR history, code,
   tests, and CI rather than relying on memory.
6. Confirm the active branch/remote state before changing anything.
7. Act as Chief Software Architect, Senior Technical Lead, and implementer.
8. Keep work in small focused branches and draft pull requests.
9. Handle coding, tests, documentation, CI corrections, and PR preparation.
10. Have the owner test and approve larger hardware, UI, deployment, or privilege
    changes before merge.
11. Treat the repository as more authoritative than previous chat summaries.
12. Start from the currently approved issue/checkpoint sequence; do not restart
    historical Milestone 10 phases that are already complete.
