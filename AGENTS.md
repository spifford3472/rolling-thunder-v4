# Rolling Thunder v4 Agent Instructions

## Purpose

Rolling Thunder v4 is a production in-vehicle amateur-radio operating, logging,
situational-awareness, and radio-control system. The primary mobile runtime is
the Raspberry Pi host `anvilmobile`; the Forge host provides reusable backend
services and heavier/provider-facing work.

This file is intentionally concise. It is a routing and guardrail document, not
the full engineering manual.

## Required Reading

Before changing code, read:

1. `AGENTS.md`
2. `docs/engineering/index.md`
3. `docs/engineering/ownership-and-dependencies.md`
4. `docs/engineering/shared-component-contracts.md`
5. the feature/service guide named for the area being changed
6. the relevant existing subsystem document(s) linked by the engineering index
7. the source files and tests for the requested change

For Forge work, also read `docs/engineering/forge-services.md`.
For operator-visible behavior, also read `docs/ROLLING_THUNDER_OPERATORS_GUIDE.md`.

The current branch and repository code are authoritative. Historical checkpoint
documents are context, not permission to undo later behavior.

## Scope and Ownership

Do not develop directly on `main`. Make the smallest change that satisfies the
assigned task. Do not perform unrelated refactors, renames, dependency changes,
or architecture rewrites.

A feature-scoped task does **not** grant ownership of shared code.

Before modifying a shared component:

1. identify its documented consumers;
2. inspect the relevant regression tests for those consumers;
3. preserve the shared contract unless the task explicitly changes it; and
4. update the shared-component documentation when the contract or consumer set changes.

Examples of shared boundaries include callsign information, contact logging,
GPS/current grid, shared spot presentation/tuning, map state, status messages,
radio control, physical controls, Forge clients, and persistence.

## Documentation Is Part of the Change

Documentation maintenance is mandatory.

A code change is not complete when it leaves the engineering or operator
documentation stale.

In the same branch/PR:

- update the appropriate engineering guide when responsibility, dependencies,
  lifecycle, data ownership, API behavior, hardware behavior, persistence, or
  failure semantics change;
- update `docs/engineering/source-file-index.md` when modules are added,
  removed, renamed, or materially repurposed;
- update `docs/engineering/ownership-and-dependencies.md` and
  `docs/engineering/shared-component-contracts.md` when consumers or shared
  contracts change;
- update the operator guide for operator-visible screen, control, alert, status,
  workflow, or startup changes;
- remove or clearly mark superseded documentation rather than leaving
  contradictory instructions.

Agents must not claim a task is complete while required documentation is stale.

## Architecture Rules

Maintain separation between:

1. UI/presentation
2. application controllers and services
3. domain/value models
4. persistence and network adapters
5. hardware adapters

Tkinter must consume already-published state and invoke application/controller
boundaries. Do not put blocking HTTP, SQLite, filesystem, audio, serial, CAT, or
provider work in the UI thread.

Use typed interfaces, immutable published state, dependency injection, bounded
work, explicit lifecycles, and deterministic mocks/fakes.

The Raspberry Pi remains local-first. Loss of Forge, WireGuard, cellular
service, or public internet must not unnecessarily disable local radio, GPS,
logging, or other locally available functions.

## Shared Radio and Safety Authority

Do not create parallel radio-command paths merely for one feature.

Respect the existing typed radio/control services and the feature-specific
authorization boundaries documented in the engineering guides.

Never broaden transmit authority as a side effect of unrelated work. FT8
transmission remains an explicitly authorized, bounded workflow. Other features
must not acquire unattended/general PTT, MOX, keying, tuner, or power authority
without an explicitly approved design change.

## Forge Service Contract

Forge processes are reusable backend services, not private helper processes for
one Rolling Thunder screen.

Any Forge capability that is useful outside the local process should expose a
stable, documented, programmatic interface so other authorized programs can
consume it in the future.

Forge code must:

- separate provider adapters from published service/domain contracts;
- avoid Tkinter/UI layout concepts in backend APIs;
- avoid assumptions that Rolling Thunder is the only client;
- expose truthful independent health/status;
- keep external-provider connectivity, etiquette, rate limits, credentials, and
  persistence on the Forge side when that is the established architecture;
- use versioned/stable contracts where practical.

Do not design a Forge API around one screen's widget structure. See
`docs/engineering/forge-services.md`.

## Hardware Abstraction

Physical hardware must be accessed through typed interfaces/adapters. Application
and UI code must not directly open device paths such as `/dev/ttyUSB*`,
`/dev/ttyACM*`, or `/dev/snd/*`.

Hardware/network failure must be visible and isolated rather than crashing the
application.

## Configuration and Secrets

Use the typed configuration system. Do not scatter hard-coded configuration.

Never commit passwords, API keys, private keys, access tokens, or personal
credentials. Forge credentials remain on Forge; client code receives only the
data required by its contract.

## Tests and Quality Gates

New behavior requires tests. Bug fixes should include a regression test when
practical.

Tests must run without requiring live radio hardware, Forge, or internet unless
explicitly identified as deployment/hardware acceptance tests.

Before completion, run the repository-standard gates:

```bash
ruff check .
mypy src/rolling_thunder
pytest
git diff --check
```

Use the active project virtual environment. Do not bypass pre-commit or CI with
`--no-verify` unless the repository owner explicitly directs it.

Passing automated tests does not replace hardware/full-screen/operator
acceptance where the change affects installed behavior.

## Git and Release Workflow

Use focused feature/fix/docs branches and clear imperative commits.

Do not merge a PR without explicit repository-owner authorization.

Release/deployment changes must preserve an exact rollback point. Production
configuration and durable databases must not be replaced casually by repository
checkout operations.

## Definition of Done

A task is complete only when:

1. requested behavior is implemented;
2. ownership and shared-component boundaries are preserved;
3. relevant tests are included and pass;
4. Ruff, strict MyPy, pytest, and `git diff --check` pass;
5. engineering documentation reflects the code;
6. the operator guide reflects operator-visible changes;
7. Forge changes preserve the reusable-service contract;
8. no secrets or machine-specific credentials are committed;
9. required live acceptance has been completed; and
10. the change remains limited to the approved scope.
