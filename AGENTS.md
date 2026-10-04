# Rolling Thunder v4 Agent Instructions

## Required reading before any code change

Before modifying code, read:

1. `docs/engineering/index.md`
2. the feature guide for the area being changed
3. every shared-component guide identified as a dependency of that feature
4. the relevant existing subsystem documentation linked from the engineering guide
5. the tests that protect the affected behavior

Do not assume a component belongs to the screen where it is visible. Rolling Thunder intentionally shares services, state, widgets, overlays, logging, tuning, location, and Forge APIs across multiple screens.

## Shared-code protection rule

A feature-scoped task does **not** grant ownership of shared behavior.

Before editing any shared component, identify and review all documented consumers and their regression tests. Changes to shared components must preserve the contracts of every consumer unless the repository owner explicitly approves a cross-feature behavior change.

Examples include callsign/contact-information overlays, contact logging, GPS/current-grid state, radio control, map services, shared spot presentation/tuning, status messages, and Forge clients.

## Documentation is part of the code

Engineering documentation must remain synchronized with implementation.

If a change modifies module responsibility, public behavior, data ownership, lifecycle, dependencies, persistence, API contracts, hardware authority, UI behavior, or cross-feature consumers, update the applicable documentation in the **same branch and pull request**.

If a new source module/service/screen is added, add it to the engineering source catalog and the applicable feature/subsystem guide. If a module is removed or replaced, remove or correct stale documentation.

If a shared component gains or loses consumers, update `docs/engineering/shared-component-consumers.md`.

If operator-visible behavior changes, update `docs/ROLLING_THUNDER_OPERATORS_GUIDE.md`.

Documentation updates are part of Definition of Done. An agent must not claim a task is complete while its engineering or operator documentation is stale.

## Forge is a reusable backend platform

Forge processes must be designed as reusable backend services, not as private implementation details coupled only to the Rolling Thunder dashboard.

New or modified Forge functionality should expose stable, typed/service-oriented boundaries that can be called by other authorized programs in the future. Keep provider credentials, persistence, polling/streaming lifecycles, normalization, caching, and failure handling behind those service boundaries.

Do not place Rolling-Thunder-screen-specific presentation logic into Forge. Do not require a Rolling Thunder UI process to invoke reusable Forge capabilities. Preserve API compatibility where practical and document intentional contract changes.

## Project purpose

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system. The primary client runs on Raspberry Pi `anvilmobile`; Forge provides reusable backend APIs and heavier network/provider processing.

The Pi remains local-first and must retain useful operation when Forge, WireGuard, cellular service, or public internet services are unavailable.

## Development environment

Production Pi checkout:

```text
/home/geoff/projects/rolling-thunder-v4
```

Python environment:

```text
/home/geoff/projects/rolling-thunder-v4/.venv
```

Do not develop directly on `main`. Use a focused branch/worktree.

## Quality gates

Before a change is considered complete, run the repository's full current gates:

```bash
ruff check .
mypy src/rolling_thunder
pytest
git diff --check
```

Relevant targeted tests must also pass. Hardware, full-screen UI, radio, audio, GPS, networking, systemd, or Forge changes require controlled live acceptance when automated tests cannot prove installed behavior.

Do not bypass hooks or validation with `--no-verify` unless explicitly directed by the repository owner.

## Architecture principles

Preserve separation between:

1. presentation/UI
2. application controllers and services
3. typed domain models and contracts
4. hardware/network/persistence ports
5. concrete adapters
6. Forge backend services

Business logic must not depend directly on GUI widgets, serial ports, USB devices, network sockets, or operating-system device paths.

Slow hardware, network, database, filesystem, provider, or audio work must not block the Tkinter/UI thread.

## Hardware and radio authority

Physical hardware must be accessed through typed interfaces/adapters. Application and UI code must not directly open device paths.

Do not casually broaden transmit authority. FT8 has deliberately bounded transmit capabilities with explicit authorization/session/timing controls. Other application paths must not gain PTT/MOX/keying/tuner/power authority merely because a radio adapter technically supports it.

## Local-first data safety

A locally committed QSO is successful independently of Forge/Wavelog/network availability. Remote synchronization must not be inside the local commit transaction and must not delete or roll back a valid local contact on remote failure.

Pending/uncertain remote state must be preserved and recoverable.

## Configuration and secrets

Use typed centralized configuration. Never commit passwords, API keys, bearer tokens, private keys, or personal credentials.

## Scope control

Make only changes needed for the assigned task. Do not perform unrelated refactoring, rename modules, restructure directories, replace dependencies, or redesign shared UI without explicit scope.

When implementation and old prose disagree, current code/tests plus explicitly accepted production behavior are authoritative; correct the documentation as part of the change.

## Definition of Done

A task is complete only when:

1. requested behavior is implemented;
2. relevant targeted tests exist and pass;
3. full Ruff, strict MyPy, pytest, and diff checks pass;
4. affected shared consumers were reviewed;
5. engineering documentation is synchronized;
6. operator documentation is updated for user-visible behavior;
7. applicable live acceptance passes;
8. no secrets are committed;
9. the change remains within approved scope.
