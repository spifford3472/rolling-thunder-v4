# STAB-07 — integration review, documentation reconciliation and parked release plan

**Status: OFFLINE INTEGRATION CANDIDATE / PRODUCTION NO GO.** Written 2026-11-14.
No PR merge, privileged wrapper installation, service restart, deployment,
SQLite mutation, CAT command, RF test, or host configuration change is authorized
by this document. This is not a completed production acceptance certificate.

## Scope and provenance

The review uses source from GitHub `spifford3472/rolling-thunder-v4` and a
separate Forge-only working tree. Current `main` at the time of rehearsal was
`dab86ab907f49ca0f64683c8ec4b2cc350d10039`. The offline rehearsal
combined only proposed changes; no repository pull request was merged.

| Review PR | Function | Disposition |
| --- | --- | --- |
| #438 | System supervision singleton test / source reconciliation | Include in offline integration, keep original draft |
| #442 | STAB-06C separate deployment lock helper | Include in offline integration; also retain installed wrapper's inline lock under review |
| #443 | STAB-06D uninstalled candidate wrapper and UI heartbeat | Include via STAB-06F stack |
| #444 | STAB-06E durable transaction journal | Include via STAB-06F stack |
| #445 | STAB-06F read-only inspector, approval-gated attestation | Base for integration rehearsal |
| #439 | DOC-02 status/historical evidence corrections | Include documentation only |
| #440 | REL-01 parked acceptance/runbook | Include as nonexecuted NO GO checklist |
| #414 | DOC-03 architecture inventory and report-only CI changes | **Separate unfinished draft:** examine and split after exact-current-source inventory review |

Source-level merge rehearsal of #442 into #445 produced only
`docs/engineering/index.md` and `docs/engineering/test-index.md` conflicts.
Rehearsing #438 produced those same two documentation conflicts; #439 and #440
only conflicted in `docs/engineering/index.md`. Reconciled entries retain both
STAB-06C and STAB-06D–F tests; none of the above caused a source-code conflict.
The integration's exact-file inventory check initially found 13 absent source
module references and 42 absent test-file references, with no stale paths.
STAB-07 added those exact paths (401/401 source modules and 442/442 tests
indexed); their feature ownership and deployed usage remain review work for
#414. The original PRs and their owner approval boundaries remain intact.
This rehearsal does not establish that future retargeting will be conflict-free.

## Safety blockers and design review findings

1. **Installed privileged wrapper identity.** A private operator-authorized
   snapshot of `/usr/local/sbin/rolling-thunder-deploy` exists at
   `/home/geoff/rolling-thunder-review/installed-wrapper-20261114T035408Z.sh`,
   SHA256 `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`.
   Read-only remote access cannot independently hash the *installed root-owned*
   original; interactive owner authorization is still required. The source
   `deploy/rolling-thunder-deploy.candidate` is **not** installed or executable.
2. **Actual system service and private drop-ins.** Read-only AnvilMobile
   `systemctl show` (2026-11-14) reports `ActiveState=active`, MainPID `60400`,
   `User=geoff`, system service unit
   `/etc/systemd/system/rolling-thunder.service`, and the expected four drop-in
   paths including protected `60-ft8-period.conf`. Contents/sha256 of that
   protected drop-in have not been obtained or reconciled. Current unit exports
   `XDG_RUNTIME_DIR=/run/user/1000` and that directory is mode `0700`, satisfying
   a *necessary* heartbeat environment prerequisite, **not** a healthy dashboard
   assertion after a future deployment.
3. **No verified actual running SHA.** `git rev-parse HEAD`, systemd MainPID,
   `/proc/.../cmdline`, cgroup, and a fresh Tk heartbeat are complementary
   signals, but their combination is not independent proof that the executing
   Python process loaded all expected commit bytes. Require a signed or
   independent release identity assertion before accepting reconciliation;
   a human-written receipt flag alone is insufficient evidence of this fact.
4. **Recovery authorization and privilege model.** STAB-06F's local private
   approval receipt is not cryptographically authenticated human approval.
   Do not install any reconciliation CLI until an authenticated, audited,
   narrowly scoped owner approval route has been verified. Root-owned paths,
   private modes, exact argument allowlisting, nonce/expiration, and rollback
   authorization remain separate release gates. Never grant broad sudo.
5. **SQLite/WAL and QSO protection.** The inspector refuses active WAL because
   immutable read-only SQLite cannot safely claim a consistent live WAL view.
   Parked consistent snapshot or equivalent independently validated database
   view must be provided. Compare schema, integrity, backup QSO rows and newly
   committed contacts; never overwrite current SQLite with a pre-deploy backup.
   A failed migration or reboot must keep the journal blocked for reviewed
   recovery. An older version lacking the Tk marker remains `unverified`.
6. **Radio transmit safety.** The source still passes
   `radio_confirmed_receive=True` at two FT8 UI paths, which is not independent
   physical receive/PTT confirmation. STAB-04/05 shutdown and CAT timeout
   evidence must be independently accepted with a parked radio and appropriate
   physical observation before any release involving actual transmit control.
   A queued `TX0;` is not proof of de-key; no unattended RF tests authorized.
7. **Full repository Ruff.** Existing unrelated findings under
   `deploy/diagnostics/rt-usb-observer.py` block `ruff check .` even though CI's
   scoped `ruff check src tests` passes. Keep the existing USB observer behavior
   intact; either make a separately tested lint-only correction or explicitly
   record this quality-gate exception before a release.
8. **Documentation issue #410.** Historical Nov 13 prose must remain dated;
   current code has inherited-flock singleton protection. The wrapper capture
   supersedes the assertion that its contents are wholly unreadable, but does
   not independently certify the installed original hash or its runtime safety.
9. **PR #414 cannot be silently incorporated.** Its broad inventory, operator
   FT8 warning and report-only CI audit need independent source review, especially
   the literal `radio_confirmed_receive=True` handling. Do not duplicate or
   overwrite the proposed audit without verification.

## Preferred sequencing — review first, merge only upon separate approval

1. Freeze a candidate exact commit SHA after review. Recheck `main` and all
   branch diffs. Keep #414 separate until its source/index audit is accepted.
2. Review and independently approve STAB-06C lock helper and #438 launcher
   regression; confirm the helper and inline privileged wrapper lock do not
   accidentally create *different* mutex domains. Both must serialize through
   the **same** fixed root-owned lock if both entrypoints can deploy.
3. Review #443 candidate, #444 journal and #445 inspector/reconciliation in
   dependency order. They must be integrated *as one reviewed release series*
   while retaining the individual PR audit trail. Apply #439 and #440's verified
   documentation sections without overwriting later source-derived corrections.
4. Resolve #414 only after exact current code inventory and safety audit. A
   report-only CI step must remain non-blocking until mismatches are resolved;
   it must not rewrite files silently.
5. Require full Python checks and a new GitHub Actions run at **the exact final
   integrated commit** after resolving documentation/source conflicts. CI for
   #445's earlier stacked SHA is useful evidence, not acceptance of a new merge
   SHA. Do not collapse branch histories or auto-merge drafts.

## Parked production PRE-FLIGHT — all gates are mandatory

- Obtain explicit owner approval for the *selected merge(s)*, separate
  approval for privileged installation, separate approval for a parked exact
  SHA deployment/restart, and **distinct** approval for any live RF test.
- Owner attests stationary vehicle, no active QSO/FT8/TX, stable power, access
  to radio physical power/PTT controls, and safe immediate recovery path.
- Freeze current operating SHA, backup checksum and SQLite schema/integrity,
  free disk space, exact target source SHA, service/unit and protected drop-in
  checksums, installed root wrapper checksum and backup path. No production
  commands should run while the radio is transmitting.
- Validate a protected, user-approved local backup of the original root-owned
  wrapper, journal state and any existing root-owned helper files before
  proposing replacement. Validate installation ownership and modes **before**
  installing; use atomic, reversible and least-privileged path staging.
- Prepare privileged paths only after approval:
  `/usr/local/sbin/rolling-thunder-deploy`,
  `/usr/local/libexec/rolling-thunder-deployment-journal.py`,
  `/usr/local/libexec/rolling-thunder-recovery-inspect.py`,
  `/usr/local/libexec/rolling-thunder-reconcile.py`,
  `/run/rolling-thunder-deploy.lock`,
  `/var/lib/rolling-thunder-deploy/transaction.json` plus private history,
  `/var/backups/rolling-thunder-deploy/` and the existing `geoff` application
  checkout. Do not create a new competing unit, daemon, timer, or CAT path.
- Verify that the approved wrapper starts journaling and lock acquisition
  **before** any mutable operation; fail closed on missing journal helper,
  invalid private directory, stale journal or conflicting recovery identity.
- Commit the QTH infrastructure change record (source paths, service/drop-ins,
  permissions, integration and job inventory, exact SHA, backups, validation,
  stop conditions, rollback, and history) to private
  `spifford3472/ki5vnb-qth-infrastructure` **before** the host change can be
  considered complete. No infrastructure files were modified for this draft.

## Parked validation after explicitly approved installation and release

1. Run a second parallel deployment as an isolated simulated invocation; it
   must reject before Git, backup, service or database mutation. Do not initiate
   real overlapping deployments. Confirm single service-owned MainPID/cgroup,
   exact expected checkout and independently attested runtime code identity.
2. Verify a fresh, real Tk event-loop heartbeat **and** operator-visible
   response, GPS/controller detection, logging/QSO integrity, bounded shutdown
   and restart timing. Missing or old-version heartbeat is not success.
3. Capture actual service journal and `RT_SHUTDOWN`, `RT_RUNTIME_SHUTDOWN`,
   `RT_PTT_RELEASE` evidence without conflating software command issue with
   physical radio RX. Confirm no duplicate or unmanaged dashboard.
4. Validate read-only database integrity, schema compatibility, all preexisting
   and newly committed QSOs, backup integrity, and absence of overwritten data.
   If WAL is active, obtain a correctly isolated snapshot rather than use
   immutable SQLite against a live database.
5. Execute controlled no-RF failure scenarios where separately approved;
   unverified CAT/PTT, journal corruption, timeout, missing backup or runtime
   identity mismatch are **STOP / NO GO**, not silent automatic rollback.
6. Only after separate owner authorization, test relevant receive/PTT behavior
   while parked with independently observed radio state. Do not treat these
   instructions as permission to transmit now.

## Rollback and refusal criteria

Rollback is **two separate domains**: (a) wrapper/helper privileged
installation, restored from verified protected original files, and (b)
application release SHA, reverted only through the approved serialized wrapper
when database/schema and process state permit. Do not modify installed scripts
or systemd on the basis of a Git checkout alone. Preserve current SQLite,
newer QSOs, active journal/history and backup artifacts after any failure.
An interrupted or indeterminate journal stays blocked until separately approved
read-only inspection and reconciliation. Never bypass or delete an incomplete
record to make deployment appear successful. Physical TX/receive uncertainty,
missing running-code assurance, lost QSO, incompatible migration, unsafe lock,
corrupt audit record, unreadable protected drop-in or unauthorized receipt means
**NO GO** and owner-controlled recovery. A rollback's systemd-active status is
not proof of health.

## Evidence and release status ledger (2026-11-14)

- Scratch-only integration rehearsal: completed; **not merged into `main`**.
- Root wrapper capture checksum: known for copied snapshot only; installed
  source hash still needs privileged verified comparison.
- System manager and XDG runtime prerequisite: observed read-only on Pi.
- Protected `60-ft8-period.conf` contents: **not independently inspected**.
- GitHub CI for prior #445 SHA: passed, but new integrated SHA requires CI.
- Parked operator/vehicle and RF state: **not confirmed**.
- Privileged reconciliation authentication and runtime SHA proof: **not accepted**.
- Actual wrapper install, code deployment, crash/rollback and RF testing:
  **not performed**.
- **Release decision: NO GO.**

## Change history

- 2026-11-14: Created standalone offline integration rehearsal; resolved
  index/test-index overlap while preserving earlier docs; refreshed exact
  source/installed evidence boundaries; prepared this nonexecuted release plan.
  Undo by abandoning this scratch integration branch. No host rollback exists
  because no host or service change was made.
