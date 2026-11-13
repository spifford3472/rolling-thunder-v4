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
| P0 | The repository contains `deploy/systemd/rolling-thunder.service` (system-level `User=geoff`, `Restart=on-failure`) invoking `deploy/rolling-thunder-autostart`, which uses `pgrep` duplicate detection, waits for system uptime >=180 s, then `exec`s `rolling-thunder-ui`. Issue #410 reported dashboard PID running without a matching *user* unit. | Verify installed system unit and process ancestry, exact-SHA wrapper, stop/kill behavior, and duplicate prevention; a missing user unit does not disprove a system unit. | **Template and launcher verified in source; installed supervision unresolved** |
| P0 | Actual FT-891 TX LED remained on during a stuck-transmit warning; radio power-cycle cleared TX, followed by FT8 overruns and controller-unlock failure. `ft8/ptt_alarm.py` latches TX inhibit until warning acknowledged plus 1-3-1 on FT8. **`ui_main.py` calls `unlock_step(..., radio_confirmed_receive=True)` unconditionally**, relying on manual operator recovery, not a verified physical RX readback. | Review watchdog independence, PTT release, CAT/audio failure paths, controller events and whether constant RX flag meets safety policy; add regression coverage in separate approved code change. | **Confirmed source-level safety gap; no unattended FT8 until accepted** |
| P1 | `meshcore-ohgo-incidents.md` presents a combined UI context but distinguishes passive MeshCore collection from independently fetched Forge OHGO incidents. | Trace MeshCore collector, broker, serial paths, configuration, UI and data consumers; trace OHGO dependencies separately. Document reversible removal preserving OHGO and historical data. | **Separation documented; full code dependency audit pending** |
| P1 | reSpeaker XVF3800 USB re-enumerated at full speed with `error -28` bandwidth allocation failures; Digirig playback failed; after microphone removal a completed FT8 QSO was reported. | Reconcile USB topology, audio capture/playback configuration, reconnect behavior, observer and kernel logs, and bounded recovery tests. | **Field evidence, cause not proven** |
| P1 | Contact display reported 15 unsynced of 352; Forge contact-sync process running. | Compare Pi contact and retry SQLite state with Forge UUID ledger and Wavelog records; distinguish FT8 attempt failures from sync failures. Preserve records. | **Unresolved** |
| P1 | Controller displayed command 1, 3, 1 unlock instruction, but operator reported it did not unlock. | Inspect physical control parser, lock state transitions, event telemetry, controller firmware and UI tests. | **Unresolved** |
| P2 | Engineering source index headline declared 340 modules, but its current module-list entries contain 386 distinct source paths and six repeated entries. Test index contains 383 distinct test paths, matching its headline. | Enumerate actual `src/rolling_thunder/**/*.py` and `tests/**/*.py` on current main and diff against both indexes; confirm missing/orphan entries. | **Document-count drift confirmed; filesystem comparison blocked** |

## Completion criteria

1. Pin and record GitHub main SHA and exact production SHA(s); classify source, installed, and observed claims separately.
2. Enumerate source modules, configuration, scripts, service units, entry points, data stores, jobs, external integrations, and tests; create a bidirectional documentation coverage matrix.
3. Correct proven documentation drift in focused commits, including source-file index, ownership, shared contracts, operator guide, Forge services, startup/shutdown and recovery. Mark unverified runtime assertions explicitly rather than inventing a configuration.
4. Record every code defect separately with severity, source evidence, regression coverage, and acceptance gates; do not conceal defects by editing documentation to match unsafe behavior.
5. Run documentation link/path checks, source-index comparison, `ruff check .`, `mypy src/rolling_thunder`, `pytest`, and `git diff --check` where available. Report any unavailable gate, never imply it passed.
6. Obtain review before merging. No production deployment or MeshCore removal is authorized by this document.

## Change history

- 2026-11-13: Initial reconciliation ledger created on a documentation branch; findings are explicitly preliminary.

## 2026-11-13 verified documentation changes

- Corrected `system-architecture.md` to identify the actual system-level template at `deploy/systemd/rolling-thunder.service`, its launcher and unverified installed state. Qwen's initial assertion that the service template was missing was rejected after locating the actual source file.
- Clarified `meshcore-ohgo-incidents.md` that independent MeshCore collection/broker and Forge OHGO incident APIs must be evaluated separately before removal.
- Corrected misleading module inventory headline in `source-file-index.md`; updated `test-index.md` to distinguish documented path references from actual file-tree verification; linked this ledger from engineering index.
- Added a source-verified FT8 stuck-TX and controller-lockout safety note to the operator guide. In particular, `ui_main.py` currently passes a constant receive flag to the alarm unlock handler; this is not independent RF-state verification.

## Blockers and continuation

1. The accessible Forge checkout is at old commit `a63e286`; the other Forge development checkout was `1062bfb`, not proven equivalent to current GitHub main. Git fetch over SSH from the remote account failed `Permission denied (publickey)`. **Do not run repository quality gates on those old trees and claim current-main validation.** GitHub connector supports targeted source reads and documentation commits, but does not provide a recursive tree listing through the used action. A current complete tree and CI run remain pending.
2. Live Pi system journal and protected runtime directory were not readable through the current remote account. No service or radio state was modified. Runtime assertions remain explicitly unverified.
3. Qwen `qwen3-coder:30b` via Forge Ollama completed a narrow architecture comparison, but incorrectly inferred the service unit was absent; independent source review found `deploy/systemd/rolling-thunder.service`. Treat its suggestions as hypotheses requiring source confirmation.
4. Required gates `ruff check .`, `mypy src/rolling_thunder`, `pytest`, and `git diff --check` have **not** run against the current PR head. Do not merge as fully validated until the current source tree is available and those checks are completed or an explicitly reviewed docs-only exception is approved.

## Audit change history

- 2026-11-13: Verified source template, PTT alarm, UI lockout handler, collector and OHGO boundaries; committed focused engineering/operator documentation corrections. Remaining tree-wide and production checks are blocked and explicitly open.
