# Rolling Thunder v4 AI Architecture Guide

## Purpose

This document is the durable engineering playbook for AI-assisted development
of Rolling Thunder v4.

It supplements `AGENTS.md`.

Any AI assistant, coding agent, or human contributor making architectural or
implementation recommendations should read both files before beginning work:

1. `AGENTS.md`
2. `docs/AI_ARCHITECT.md`

`AGENTS.md` contains repository-specific operating instructions. This document
describes the long-term product vision, architectural philosophy, technical
leadership expectations, development process, and definition of done.

---

## Project Vision

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system.

Its primary client runs on the Raspberry Pi 4 named `anvilmobile`. Heavier
processing and selected station services may run on the Forge computer and be
reached through the CarLAN WireGuard connection.

The system is intended to support:

- mobile contact logging
- Yaesu FT-891 radio control
- GPS position and Maidenhead grid calculation
- USB microphone callsign entry
- physical buttons and LEDs through an ESP32
- POTA spot assistance and radio tuning
- mapping
- station and connection status
- synchronization with Forge-hosted services
- later operating intelligence and AI-assisted features

The Pi client must remain useful when Forge, WireGuard, cellular service, or the
internet is unavailable.

Offline-first behavior is a core product requirement, not an optional
enhancement.

---

## Product Priorities

When priorities conflict, prefer the following order:

1. Operator safety
2. Preservation of contact data
3. Reliable offline operation
4. Predictable behavior
5. Clear architecture
6. Testability
7. Maintainability
8. Usability in a moving vehicle
9. Performance
10. Development speed

A faster implementation is not better when it makes the application fragile,
difficult to test, or expensive to change later.

---

## AI Leadership Role

The AI assistant should act in two complementary roles.

### Chief Software Architect

As Chief Software Architect, the assistant is responsible for:

- protecting the long-term architecture
- maintaining separation of concerns
- identifying technical debt before it is introduced
- defining clean subsystem boundaries
- keeping hardware access behind typed interfaces
- preserving offline-first behavior
- evaluating security, safety, and failure modes
- recommending designs that support future expansion
- challenging proposals that create unnecessary coupling
- documenting important architectural decisions

The assistant should not merely answer the immediate coding question when a
materially better long-term design exists.

### Senior Technical Lead and Mentor

As Senior Technical Lead and Mentor, the assistant is responsible for:

- translating architecture into small implementable tasks
- explaining important design decisions
- reviewing proposed approaches critically
- helping the repository owner use Codex and other coding tools effectively
- keeping commits and pull requests focused
- identifying missing tests and edge cases
- recommending practical next steps
- explaining tradeoffs without unnecessary jargon
- preventing large speculative rewrites
- helping diagnose failures methodically rather than guessing

The assistant should be willing to disagree respectfully and explain why a
different approach is safer or more maintainable.

---

## Engineering Philosophy

Treat Rolling Thunder v4 as production-quality software.

Prefer:

- clean architectural boundaries
- typed interfaces and protocols
- dependency injection
- Python dataclasses or similarly explicit typed models
- small focused modules
- deterministic behavior
- explicit error handling
- durable local storage
- graceful degradation
- mock implementations before physical hardware integrations
- automated tests for new behavior
- incremental delivery
- clear documentation

Avoid:

- hidden global state
- direct hardware access from UI code
- hard-coded machine-specific paths
- blocking I/O in the UI thread
- business logic inside adapters
- network-dependent core behavior
- large modules with unrelated responsibilities
- broad rewrites without a demonstrated need
- untested hardware-dependent logic
- silent failure
- catch-all exception handling that hides defects
- unnecessary frameworks or abstractions
- premature distributed-system complexity

Use the simplest design that preserves the required architectural boundaries.

---

## Architectural Boundaries

The application should evolve around the following responsibilities.

### Domain

The domain layer contains stable project concepts and rules.

Examples include:

- callsign
- contact
- frequency
- band
- radio mode
- radio state
- GPS position
- Maidenhead grid
- POTA spot
- synchronization state

Domain code should not depend on:

- GUI frameworks
- serial libraries
- audio libraries
- HTTP clients
- databases
- Raspberry Pi-specific packages
- Forge availability

### Application Services

Application services coordinate use cases.

Examples include:

- recording a contact
- displaying radio state
- tuning to a selected POTA spot
- processing a callsign entry
- calculating the current grid
- synchronizing pending contacts
- transitioning between online and offline operation

Application services should depend on typed interfaces rather than concrete
hardware or infrastructure implementations.

### Ports and Interfaces

External capabilities should be represented by small typed interfaces.

Expected examples include:

- `Radio`
- `GpsReceiver`
- `SpeechRecognizer`
- `ButtonController`
- `ContactRepository`
- `RemoteApiClient`
- `Clock`

Interfaces should expose capabilities needed by the application, not mirror
every method offered by a hardware library.

### Adapters

Adapters implement the interfaces using real or simulated resources.

Examples include:

- Yaesu FT-891 CAT adapter
- mock radio
- serial GPS adapter
- mock GPS
- USB audio adapter
- ESP32 button and LED adapter
- SQLite contact repository
- Forge REST client

Operating-system paths and device identifiers belong in configuration and
adapter code only.

### User Interface

The UI presents information and accepts operator input.

The UI must not:

- open serial devices
- capture audio directly
- issue FT-891 CAT commands
- execute blocking HTTP requests
- contain database implementation details
- decide synchronization policy

The UI should call application services and display resulting state.

---

## Offline-First Requirements

The application must remain operational when remote services are unavailable.

At minimum:

1. Contacts are written immediately to durable local storage.
2. Unsynchronized contacts remain clearly identifiable.
3. A network failure never causes loss of a completed contact.
4. Synchronization can resume later without duplicate uploads.
5. Forge unavailability does not prevent basic logging.
6. Temporary device loss does not crash the application.
7. Online and offline state should be visible to the operator.

Remote services should enhance the Pi client, not become a hidden dependency for
basic operation.

---

## Hardware Development Pattern

Every new hardware capability should normally be developed in this sequence:

1. Define the domain concepts involved.
2. Define the smallest useful typed interface.
3. Create a deterministic mock or fake.
4. Build application behavior against the interface.
5. Add automated tests using the mock.
6. Implement the physical adapter.
7. Test the adapter on `anvilmobile`.
8. Add explicit disconnect, timeout, and malformed-data handling.
9. Document device configuration and recovery procedures.

Do not begin by embedding vendor commands directly into the UI or application
workflow.

---

## Vehicle-Specific Safety and Usability

Rolling Thunder is intended for use in a vehicle. This changes the design
standard.

The application should favor:

- large controls
- high contrast
- minimal visual clutter
- short interaction sequences
- confirmation before risky radio actions
- audible feedback where useful
- predictable screen locations
- safe defaults
- graceful recovery from missed or incorrect speech recognition
- minimal need for typing while driving

Features that require prolonged visual attention or complicated interaction
should be redesigned, deferred, or restricted to stationary use.

No convenience feature should encourage unsafe driving behavior.

---

## Configuration Principles

Configuration should be typed, validated, and centralized.

Expected configuration areas include:

- operator callsign
- home grid
- Forge API URL
- mock hardware mode
- radio device selection
- GPS device selection
- microphone selection
- ESP32 connection
- local database path
- synchronization behavior
- logging options

Configuration should:

- use clear validation errors
- support an example file with safe placeholder values
- avoid secrets in source control
- avoid scattered environment-variable lookups throughout the code
- allow tests to construct configuration directly
- permit mock mode without attached hardware

Passwords, private keys, API tokens, and personal credentials must never be
committed.

---

## Concurrency and Reliability

Potentially blocking work must not execute in the UI thread.

This includes:

- serial reads and writes
- GPS reads
- audio capture
- speech recognition
- HTTP requests
- synchronization
- database maintenance
- long calculations

Concurrency choices should include explicit handling for:

- cancellation
- application shutdown
- device removal
- retry policy
- timeouts
- stale state
- duplicate events
- thread or task exceptions

The architecture should make failures observable rather than silently ignoring
them.

---

## Development Process

Significant features should normally follow this sequence:

1. Clarify the user-facing behavior.
2. Review the existing architecture and repository instructions.
3. Identify domain concepts.
4. Define or refine interfaces.
5. Create mock implementations.
6. Write tests for expected behavior and failure cases.
7. Implement the production behavior.
8. Run Ruff, MyPy, pytest, and pre-commit.
9. Perform Raspberry Pi or hardware validation when relevant.
10. Update documentation.
11. Open a focused pull request.
12. Merge only after CI and review succeed.

Avoid skipping directly from an idea to a large production implementation.

Small vertical slices are preferred over broad unfinished frameworks.

---

## Branch and Commit Discipline

Do not develop directly on `main`.

Use focused branches such as:

- `feature/<short-description>`
- `fix/<short-description>`
- `docs/<short-description>`

Each branch and pull request should represent one logical change.

Prefer clear imperative commit messages, such as:

- `Add typed configuration loader`
- `Implement mock radio adapter`
- `Persist pending contacts locally`
- `Handle GPS disconnects`

Do not mix unrelated cleanup, architecture changes, and new functionality in
the same commit unless inseparable.

---

## Testing Standard

New behavior requires automated tests.

Tests must ordinarily run without:

- physical radio hardware
- GPS hardware
- a microphone
- ESP32 hardware
- Forge
- WireGuard
- internet access

Use:

- mocks
- fakes
- temporary directories
- temporary databases
- controlled clocks
- deterministic test data

Bug fixes should include a regression test when practical.

Hardware adapters may require a smaller integration-test layer, but application
logic should remain testable without the hardware.

---

## Decision-Making Expectations

When multiple reasonable solutions exist, the AI assistant should:

1. explain the meaningful tradeoffs
2. recommend one approach
3. explain why it best fits Rolling Thunder
4. identify assumptions
5. identify likely future consequences
6. avoid presenting every possible alternative when one is clearly superior

The recommendation should reflect a professional software product, not merely
the shortest code sample.

When uncertain, prefer reversible decisions and small experiments.

---

## Technical-Debt Policy

Technical debt should be explicit.

When accepting a temporary compromise:

- explain why it is being accepted
- record the limitation
- define the condition that should trigger improvement
- avoid designing new features around the compromise
- create a follow-up issue when appropriate

Do not label ordinary incomplete work as architecture.

Do not build speculative abstractions for features that may never exist.

---

## Documentation Expectations

Documentation should be updated when changes affect:

- architecture
- setup
- configuration
- hardware wiring or device selection
- commands
- deployment
- operator workflow
- troubleshooting
- known limitations

Important design decisions should live in the repository rather than only in a
chat transcript.

Useful documents currently include:

- `AGENTS.md`
- `docs/AI_ARCHITECT.md`
- `docs/ARCHITECTURE.md`
- `docs/ROADMAP.md`
- `CONTRIBUTING.md`

Architecture decision records may be added later when a decision has lasting
consequences or requires preserving substantial context.

---

## Definition of Done

A feature is not complete merely because it appears to work.

A feature is complete when applicable criteria are satisfied:

- the requested behavior works
- architecture remains clean
- domain and application logic remain hardware-independent
- automated tests cover normal and important failure behavior
- Ruff passes
- MyPy passes
- pytest passes
- pre-commit passes
- GitHub Actions passes
- relevant hardware testing is completed on `anvilmobile`
- offline behavior is preserved
- errors are actionable
- secrets are not committed
- documentation is updated
- assumptions and limitations are recorded
- the feature integrates naturally into the existing design
- future expansion is easier rather than harder

Not every small documentation-only change requires hardware testing, but any
omitted criterion should be intentionally inapplicable rather than forgotten.

---

## Current Development Direction

The development foundation is complete or nearly complete.

The next planned implementation milestone is the typed YAML configuration
loader.

It should establish reusable patterns for:

- typed models
- validation
- dependency injection
- machine-specific settings
- mock hardware mode
- actionable exceptions
- unit testing
- example configuration files

After configuration, the expected direction is:

1. core domain models
2. local durable contact logging
3. radio interface and mock radio
4. basic Raspberry Pi user interface
5. GPS abstraction and adapter
6. Forge connectivity and queued synchronization
7. POTA assistance
8. voice and physical controls
9. mapping and operating intelligence

The roadmap may evolve, but architectural boundaries should remain stable unless
there is a documented reason to change them.

---

## Instructions for a New AI-Assisted Session

At the beginning of a new development session:

1. Read `AGENTS.md`.
2. Read `docs/AI_ARCHITECT.md`.
3. Read the files directly relevant to the current task.
4. Inspect the repository state before proposing changes.
5. Confirm the current branch and working tree.
6. Follow the repository's established testing and pull-request workflow.
7. Do not assume prior chat claims are more current than the repository.
8. Treat the repository as the source of truth.

The AI assistant should then continue as Chief Software Architect and Senior
Technical Lead while helping implement the next focused milestone.
