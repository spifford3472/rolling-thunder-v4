# DOC-X — current source/document reconciliation and change ledger

**Baseline:** `main` merge commit `b792151313e60596e6ff3ad51f6ed4e260078718`
(PR #472), 2026-11-15. **Classification:** source-verified documentation
and offline tests only. **Not** a claim of installed Pi/Forge equivalence, live
radio safety, production readiness, or approved deployment.

## Executive findings

1. The source and test indexes already covered every Python file on merged
   `main`: **401 of 401 modules**, **459 of 459 tests** before DOC-X. The
   `source-file-index.md` displayed count was **340**, a verified documentation
   defect, now corrected. Adding DOC-X's own test makes **460 tests**. No
   speculative catalog rewrite is warranted.
2. At this report's 2026-11-15 baseline, the real FT8 alarm UI passed a
   fabricated `radio_confirmed_receive=True`; PR #477 later corrected the
   production path to pass `False` and a separately named explicit
   `operator_recovery_override=True`. The isolated visual-test path still
   uses `True` only for its mock alarm. The current operator override is a
   manual recovery choice, **not** physical receive proof, and sends no CAT/PTT
   command or FT8 transmission.
3. The MeshCore intelligence document began with a historical *pure classifier*
   that did not store messages, while current source includes optional
   `meshcore_message_broker.py` and `meshcore_broker_drain.py`, with separate
   durable public/private streams. Its beginning is now explicitly scoped as
   historical foundation. The OHGO API remains Forge-owned and independent;
   sharing an operator context does not create a common source or lifecycle.
4. The prior STAB-04/05/06/07 *candidate/not deployed* language must be
   separated into **merged source**, **historical observations**, **installed
   SHA not reverified**, and **parked physical acceptance incomplete**. The
   operator and current architecture guides are corrected accordingly.
5. The existing DOC-02 PR #439 is largely merged or editorially reconciled in
   current `main`; do **not** merge blindly. DOC-03 PR #414 contains useful
   early safety and MeshCore findings but an obsolete incomplete-tree claim,
   duplicated current text and a report-only CI approach that fails to stop
   future index drift. DOC-X extracts the verified findings, preserves the
   original draft for review and implements deterministic enforcement instead.

## Operational ownership/dependency map (source verified)

| Boundary | Source authority | Consumers and invariant | Evidence / live limit |
| --- | --- | --- | --- |
| System startup | `deploy/systemd/rolling-thunder.service` → `deploy/rolling-thunder-autostart` → UI console | System-level unit template, 180-second minimum host uptime, inherited advisory `flock`, secondary unmanaged `pgrep` | Installed unit/drop-ins may differ; do not infer live SHA or modify service |
| UI and shutdown | `ui_main.py` owns Tk, contexts, one close worker; `application_runtime.py` owns service composition and radio cleanup | FT8 cleanup / polling stop / radio disconnect before slow nonradio workers; preference executor drained once, retry skips an already stopped queue | Simulated and ARM64 lifecycle verified; physical de-key not verified |
| Radio and FT8 | `ft891_radio.py`, typed CAT transport, FT8 authorization/hardware-transmit services | One radio command path; FT8-only bounded transmit; unresolved CAT release is not RF proof | RX/green indicator requires parked operator acceptance |
| FT8 alarm | `ft8/ptt_alarm.py` and `ui_main.py` action routing | Alarm dismissal ≠ uninhibited TX; 1–3–1 gesture requires independent operator-confirmed receive, but UI currently passes constant true | Source-level design gap; requires separately approved code fix and tests |
| Local QSO durability | `contact_logging.py`, `contact_repository.py`, `storage.py`, contact sync/outboxes | POTA, DX, Browse, DMR, FT8 share local-first SQLite; Forge/Wavelog failure must not erase durable local QSO | Synthetic migration/WAL and backup tests passed; live QSO copy/restore is not certified |
| GPS | `gps_polling.py`, `gps.py`, `maidenhead.py` | Shared published position/grid for mapping, logging, FT8 and optional collector; no second GPS reader permitted | Mock disconnect verified; real USB hot-unplug separate |
| MeshCore | `meshcore_collector_main.py`, optional broker/drain, traffic worker | Exclusive dedicated serial owner; protected local health API and classified public/private broker streams; no new RF authority | Feature config and current device installation not reverified |
| OHGO | `forge_ohgo_incidents.py`, `forge_ohgo_api.py`, `forge_spot_main.py` | Provider/cache on Forge; Pi presentation via `meshcore_ohgo_panel.py` / `_ui.py`; does not depend on MeshCore collector | API key and provider field state separately gated |
| Forge providers | `forge_spot_main.py`, `forge_contact_sync_main.py`, separate provider/worker entrypoints | Screen-neutral APIs, health, source-specific credentials/retention; Pi local-first behavior independent of Forge | 2026-11-13 PSK autoqueue oneshot failure remains historical observation, not presumed fixed |
| Offline ARM64 validation | `deploy/rolling-thunder-arm64-dashboard-{probe,runner}.py`, STAB-07 fake adapters | Tk keyboard navigation, single shutdown owner, startup rollback, nonblocking source-only tests and expected no-go on blocked worker | Does not attest Pi native library parity or production FT8 physical release |

Read the maintained `ownership-and-dependencies.md`,
`shared-component-contracts.md`, `shared-component-consumers.md`,
`forge-services.md`, and `system-architecture.md` for detailed contracts.
These are the owners; DOC-X introduces **no additional runtime manager**.

## Source startup, jobs, and integration inventory

The merged source has **18 declared Python CLI entry points** in
`pyproject.toml` and **18 repository service/timer template files** under
`deploy/` (14 `.service`, four `.timer`). These are **source packaging and
installation candidates**, not evidence of installed/enabled units. The
inventory includes these separate groups:

- Pi dashboard template `deploy/systemd/rolling-thunder.service`, with the
  `deploy/rolling-thunder-autostart` launcher, local UI entry point, and
  local storage. This template has a 20-second systemd stop timeout.
- Forge provider/worker templates for spots, callsign, contact sync,
  propagation and QSO worker, PSK Reporter/autoqueue, VOACAP baseline,
  NOAA refresh and FT8 readiness. Corresponding declared entrypoints live
  under `rolling_thunder.forge_*` rather than Tk.
- User-service templates for the passive MeshCore collector and independent
  traffic worker, plus an optional USB diagnostic observer. The source
  templates are not permission to install, activate or read private messages.
- Four source `.timer` templates: `rolling-thunder-forge-ft8-readiness`,
  `rolling-thunder-forge-noaa-refresh`, `rolling-thunder-forge-psk-autoqueue`,
  and `rolling-thunder-forge-voacap-baseline`.

Production inventory remains pinned to the dated read-only
`production-inventory-2026-11-13.md` until separately authorized inspection
reconciles installed systemd service paths, drop-ins, user/system scopes,
process identities, active jobs and enabled settings with the actual SHA.
There is **no safe inference** that all templates or entry points are active.

## Prioritized defect / complexity register

| Priority | ID | Finding | Status / next action |
| --- | --- | --- | --- |
| P0 safety | DOCX-PTT-01 | Historical production UI passed unconditional RX confirmation | **Corrected by merged PR #477**; retained as historical evidence. Current source uses explicit operator recovery and does not claim physical RX proof. See the current FT8-RX-02 guide. |
| P1 runtime | DOCX-PROD-01 | Exact installed Pi/Forge SHA and protected drop-ins not verified in this documentation-only workstream | Read-only production evidence under separate authorization; until then source ≠ installed state |
| P1 reliability | DOCX-PSK-01 | Dated PSK autoqueue oneshot failure observed while timer scheduled | Preserve historical observation; follow a read-only Forge job diagnosis, no auto-restart by DOC-X |
| P1 release | DOCX-NATIVE-01 | STAB-07K/L two Raspberry Pi native archives remain unauthenticated; real physical release tests outstanding | Quarantined; Track B deferred. Do not use unsigned archives or claim parity |
| P2 documentation | DOCX-DOC-01 | Source catalog headline 340 vs actual 401; stale STAB-07 candidate wording and historical MeshCore blanket claims | **Corrected in DOC-X** and covered by automated inventory regression |
| P2 maintainability | DOCX-CI-01 | Documentation references can drift unnoticed | Source/test bidirectional index, displayed count and local Markdown link guard added to CI, with synthetic tests |
| P2 scope | DOCX-PR-01 | #414 and #439 contain historical useful findings but overlap current main and have stale baseline assumptions | Treat as review material only; do not merge wholesale or close without explicit owner direction |

## 2026-11-16 source-status reconciliation

PR #477 merged at `80eb66295ebaff8b5a9821c7e592e16e95e7bb93`. It implements
the owner's requested session-local recovery: Voice Cancel acknowledges the
alarm; an explicit FT8-screen 1–3–1 sequence clears the software inhibit after
the operator chooses recovery; a process restart creates a fresh alarm
instance. Neither action proves physical de-key. The production UI passes
`radio_confirmed_receive=False`, logs the manual override with
`physical_rx_verified=false`, and starts no transmit. The old source finding
above is historical and no longer an open defect on current `main`.

## DOC-01, DOC-02, DOC-03 disposition

- **DOC-01:** Inventory independently enumerated on exact merged baseline.
  No missing/stale Python paths. Existing merged evidence register stays
  historical; its earlier shutdown order is not an instruction to revert
  subsequently merged STAB-07 runtime code.
- **DOC-02:** Source-verified existing fixes in #439 are present on merged
  `main` (launcher lock description, paragraphs, Forge inbox, FT8 guide),
  except remaining source/current-status corrections documented here. The
  production-install identity and PSK job status cannot be fixed editorially.
- **DOC-03:** Selected high-confidence #414 findings reviewed against current
  source. This DOC-X work makes index drift **blocking in GitHub CI**, not
  report-only; no speculative MeshCore removal, PTT patch or new launch path.
  #414 remains a separate unmerged draft, with no CI branch changes imported.

## Reproducible documentation checks

`python tools/docx_inventory.py` compares every current
`src/rolling_thunder/**/*.py` and `tests/**/*.py` in both directions against
their engineering indexes. It also enforces the displayed module count and
validates local Markdown links inside `docs/` and `AGENTS.md` without network
access. Remote HTTP references are intentionally not fetched. It does not
attempt to parse arbitrary backtick references, Markdown generated at runtime,
or installed host configuration; a passing result is **documentation hygiene**,
not an architectural correctness proof. It runs in GitHub CI before Ruff,
MyPy and the full pytest suite. The regression tests use an isolated disposable
fixture to exercise missing/stale paths and broken local links.

The repository's standard Python tests, Ruff, strict MyPy, and GitHub CI must
pass on the review head. If the source/test inventory changes, update the
indexes and displayed count in the same commit. Never suppress a confirmed
missing entry merely to obtain green CI.

## Scope, rollback, and change history

**Authorized:** offline documentation, deterministic check/tests, isolated
Forge development, draft PR creation. **Not authorized by DOC-X:** merge,
privileged installation, production service restart, Pi/Forge config change,
network/firewall/OPNsense change, access to radio hardware, CAT/PTT, RF tests,
mutation of local/production QSO databases, or purging historical records.

Rollback is a single revert of the DOC-X documentation/checker PR; no
production process is touched. Preserve earlier dated incident ledgers and
locked provenance samples as evidence. No changes affecting the specified
QTH networks or OPNsense were made, so no infrastructure-repository change
record is required.

- **2026-11-15:** DOC-X exact-source audit: index 401/401, prior test index
  459/459, documented current ownership, corrected misleading headings,
  clarified PTT visual/unlock safety, scoped historical MeshCore assertions,
  added CI enforcement and synthetic regression tests.

- **2026-11-15 source-status follow-up:** Corrected the operator guide's
  STAB-04/05 headings and engineering guide statuses from unmerged candidates
  to merged source with physical acceptance outstanding. The older DOC-02
  checkpoint now points to this ledger. CI Ruff explicitly checks the new
  inventory validator as well as source and tests.
