# Rolling Thunder v4 — documentation/code reconciliation (2026-11-13)

## Purpose and scope

This is a **read-only reconciliation ledger**, not a declaration that production is healthy or that documentation is already synchronized. Before any MeshCore removal, redesign, or release, compare the exact current GitHub source, tests, deployment wrapper, and observed production configuration. Do not silently substitute historical documentation for current code.

## Evidence and confidence

- **Repository documentation verified**: `AGENTS.md`, `docs/engineering/index.md`, `ownership-and-dependencies.md`, `shared-component-contracts.md`, `source-file-index.md`, `forge-services.md`, `system-architecture.md`, `production-baseline-and-recovery.md`, `meshcore-ohgo-incidents.md`, `tron-voice-control.md` were fetched from GitHub main on 2026-11-13.
- **Production state not verified by this document**: remote account restrictions prevent reading the protected Pi runtime tree and journal. A running process is not evidence that its workers or radio safety path are healthy.
- **No production changes**: no service restart, transmit, CAT action, database mutation, permission change, or MeshCore removal was performed by this audit.

## Open reconciliation items

| Priority | Documented assertion / concern | Required source/live verification | Disposition |
| --- | --- | --- | --- |
| P0 | `system-architecture.md` states `rolling-thunder.service` invokes `deploy/rolling-thunder-autostart`. Issue #410 reported dashboard PID running with no matching independently queried user unit. | Inspect exact-SHA wrapper, system vs user unit, launcher, process ancestry, restart/shutdown semantics and duplicate prevention. Do not infer service supervision from process existence. | **Unverified; do not rewrite as settled** |
| P0 | Actual FT-891 TX LED remained on during a stuck-transmit warning on 2026-11-13; subsequent reboot of radio cleared TX, but FT8 overruns and controller-unlock failures followed. | Inspect FT8 PTT release and watchdog code, CAT/audio failure paths, timeout independence, hardware controller state machine, relevant tests and timestamped logs. | **Safety incident; no unattended FT8 until accepted** |
| P1 | `meshcore-ohgo-incidents.md` presents a combined UI context but distinguishes passive MeshCore collection from independently fetched Forge OHGO incidents. | Trace MeshCore collector, broker, serial paths, configuration, UI and data consumers; trace OHGO dependencies separately. Document reversible removal preserving OHGO and historical data. | **Separation documented; full code dependency audit pending** |
| P1 | reSpeaker XVF3800 USB re-enumerated at full speed with `error -28` bandwidth allocation failures; Digirig playback failed; after microphone removal a completed FT8 QSO was reported. | Reconcile USB topology, audio capture/playback configuration, reconnect behavior, observer and kernel logs, and bounded recovery tests. | **Field evidence, cause not proven** |
| P1 | Contact display reported 15 unsynced of 352; Forge contact-sync process running. | Compare Pi contact and retry SQLite state with Forge UUID ledger and Wavelog records; distinguish FT8 attempt failures from sync failures. Preserve records. | **Unresolved** |
| P1 | Controller displayed command 1, 3, 1 unlock instruction, but operator reported it did not unlock. | Inspect physical control parser, lock state transitions, event telemetry, controller firmware and UI tests. | **Unresolved** |
| P2 | Engineering source index declares 340 Python modules. | Enumerate actual `src/rolling_thunder/**/*.py` on current main and diff against index, identify orphan/stale entries, tests, configuration and deployment files. | **Not yet verified** |

## Completion criteria

1. Pin and record GitHub main SHA and exact production SHA(s); classify source, installed, and observed claims separately.
2. Enumerate source modules, configuration, scripts, service units, entry points, data stores, jobs, external integrations, and tests; create a bidirectional documentation coverage matrix.
3. Correct proven documentation drift in focused commits, including source-file index, ownership, shared contracts, operator guide, Forge services, startup/shutdown and recovery. Mark unverified runtime assertions explicitly rather than inventing a configuration.
4. Record every code defect separately with severity, source evidence, regression coverage, and acceptance gates; do not conceal defects by editing documentation to match unsafe behavior.
5. Run documentation link/path checks, source-index comparison, `ruff check .`, `mypy src/rolling_thunder`, `pytest`, and `git diff --check` where available. Report any unavailable gate, never imply it passed.
6. Obtain review before merging. No production deployment or MeshCore removal is authorized by this document.

## Change history

- 2026-11-13: Initial reconciliation ledger created on a documentation branch; findings are explicitly preliminary.
