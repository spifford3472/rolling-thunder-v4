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

## STAB-07B security review addendum (2026-11-14)

Offline candidate validation now requires Ed25519-signed recovery approval receipts, a root-controlled verification public key, strict project/host/operation scoping, and bounded validity. The signer service, trusted verification key, and independent actual running-code SHA proof are **not** installed or independently accepted. A noninstalled read-only root-wrapper/drop-in evidence script exists with redaction, but no privileged file read has been executed. Physical FT8 PTT release remains an explicit NO GO because the current UI sets `radio_confirmed_receive=True` without independent receive evidence. See `stab07-security-acceptance.md`.

## STAB-07D source/witness status (2026-11-14)

An exact-Git source archive is reproducible offline and a verifier can reject signed process-start observations with wrong boot ID, PID or start ticks. These are candidate components only. A hash-pinned dependency environment, protected release installation, actual trusted launch observer and independent in-memory Python code evidence are still missing; production remains NO GO. See `stab07d-protected-release-and-launch-witness.md`.

## STAB-07E ARM64 dependency-layer status (2026-11-14)

An offline SHA-pinned wheelhouse for 26 Pi CPython 3.13 ARM64 packages, including Vosk and reproducibly locally built `srt`, is now verified with independent no-index pip hash resolution. A deterministic 46 MB source-and-wheel transport archive was produced twice. This is not a complete pinned interpreter, installed noneditable app, signed release, trusted launch attestation, or physical safety acceptance. Production NO GO; see `stab07e-arm64-wheelhouse-and-release.md`.

## STAB-07F offline stage (2026-11-14)

An exact-source noneditable app wheel built reproducibly and an unprivileged Forge-only transport candidate was staged with atomic no-replace and post-stage hash verification. **No native ARM64 interpreter launch, production unit integration, privileged immutable installation or physical radio validation occurred.** Forge lacks accessible ARM64 emulation; Docker access is restricted. See `stab07f-isolated-runtime-staging.md`. Production remains NO GO.

## STAB-07G isolated ARM64 execution (2026-11-14)

Isolated QEMU ARM64 in a private, network-disabled Forge namespace now executes Debian Python 3.13.5, installs 26 hash-locked dependencies and the noneditable app wheel, and passes native imports and installed RECORD checks. This is an emulated Debian `deb13u5` build, **not** an exact Pi (`deb13u4`) OS image. A real Tk event-loop startup, independent loaded-byte runtime identity, protected root-owned installation, SQLite/WAL, PTT physical RX and owner authorization remain mandatory NO-GO gates. See `stab07g-isolated-arm64-execution.md`.

## STAB-07H mock Tk lifecycle validation (2026-11-14)

Isolated ARM64/QEMU using a private Xvfb virtual display exercised genuine Tk callbacks, current heartbeat and shutdown helper boundaries with inert fake runtime/peripherals. Normal, runtime-error, peripheral-error and delayed cleanup cases passed; a stalled fake worker deliberately returned status 75/refused, and the original 30-file staged candidate passed independent integrity verification. This does **not** start full dashboard composition, prove RF receive, or validate protected production rollback. See `stab07h-hardware-disabled-tk-lifecycle.md`. Production remains NO GO.

## STAB-07I ARM64 full mock dashboard (2026-11-14)

Real `run_dashboard` under isolated Forge QEMU/Xvfb reached Tk readiness and clean shutdown with a mock radio and synthetic SQLite. The first version exposed duplicate post-runtime-stop preference flushing; a narrow runtime-owned drain-before-stop correction passed ARM64 retest and startup-failure mock-radio rollback. No real radio, production service, WAL or privileged install acceptance occurred. See `stab07i-mock-full-dashboard-lifecycle.md`. Production NO GO.

## STAB-07J read-only native Pi runtime provenance (2026-11-14)

AnvilMobile's sampled Debian 13 native runtime differs materially from the private emulated Forge ARM64 sysroot (27/52 ELF hashes identical; 10 different, 15 absent; 6/16 package revisions identical). A new bounded offline verifier refuses to infer complete runtime equivalence, signed release or loaded Python identity. Existing protected-release and witness candidates remain uninstalled. See `stab07j-native-runtime-provenance-and-release-readiness.md`. Production NO GO.

## STAB-07K signed exact native OS package reconstruction (2026-11-14)

14/16 sampled Pi exact package versions have been obtained from independently signed current/historical Debian ARM64 indexes and their exact SHA256-verified archives. Six are from current Debian, two from 2026-08-01 signed `trixie`, and six Python 3.13 `deb13u4` from signed 2026-07-20 `trixie-updates`. The remaining two Raspberry Pi-patched libc6/OpenSSL versions are not authenticated against signed historical Pi repository metadata. Extracted incomplete 14-package overlay matches 17/52 sampled Pi files and is not bootable. **NO GO for complete emulator, loaded-code attestation or production deployment.** See `stab07k-authenticated-exact-arm64-os-reconstruction.md`.

## STAB-07L historical Raspberry Pi package byte-equivalence (2026-11-14)

Exact ARM64 libc6 and libssl3t64 .deb bytes are available in the official Raspberry Pi pool and five unexecuted extracted ELF files match the Pi read-only SHA sample. The required historical signed RPi package index linking these .debs was not found, so they remain quarantined. Authenticated OS archive count stays 14/16, and the combined partial extracts match 22/52 Pi native-file samples with 30 absent. No executable complete image or production approval. See `stab07l-rpi-historical-package-quarantine.md`.

## STAB-07 focused Track A — unexpected worker-start exception (2026-11-15)

**Confirmed defect, offline mock-only.** `ApplicationRuntime.start()` caught
only `OSError`, `RuntimeError`, and `ValueError` after mock radio polling began.
A synthetic `LookupError` raised by an initializing worker bypassed the startup
rollback; deterministic reproduction left the mock radio `CONNECTED` and
`_started=True`. This is not proof of actual RF keying, but it violates runtime
startup resource ownership. The smallest correction catches ordinary `Exception`
for rollback and re-raises the original failure; `BaseException` such as
`KeyboardInterrupt`/`SystemExit` is intentionally outside the handler. Existing
`stop()` performs radio/FT8-first release and reports cleanup failures. A
second pre-fix reproduction showed that an `ExceptionGroup` from rollback
masked the original startup error; the handler now reports the cleanup error
while preserving the initiating exception.

`tests/test_stab07_functional_startup_recovery.py` reproduces the failure against
the previous code and requires a disconnected mock radio after recovery. The
isolated worktree test invocation **must use checked-out source**:
`PYTHONPATH="$PWD/src" /home/rt-remote/workspaces/rt-stab06c/.venv/bin/python -m pytest`.
An initial run without `PYTHONPATH` misleadingly imported an older installed
package (4,346 passed, 2 failed, 7 skipped); the correct checked-out pre-fix
baseline was **4,348 passed, 7 skipped**. The faulty baseline is not a confirmed
source regression. No real radio, production SQLite, network or deployment
changed. The new fix needs exact-head CI and further Track A acceptance.

Track A outstanding: navigation responsiveness, duplicate shutdown requests,
blocked cleanup, SQLite transactional/persistence scenarios, GPS disconnection,
FT8 fake-adapter PTT failure and real ARM64 rerun of the rebuilt application.
Track B historical signed Raspberry Pi index authenticity remains independent,
blocked pending authenticated evidence; quarantined archive files cannot be used
for an executable runtime. PR #414 remains a separate unreviewed draft.

**Polling-start follow-up (same Track A defect family):** `polling.start()` was
outside the exception rollback boundary. A synthetic failure *after* its mock
radio connection and poll registration reproduced a connected radio with an
active scheduler despite the unsuccessful `ApplicationRuntime.start()`. The
runtime now attempts polling cancellation, then pre-start FT8/radio release,
without masking the initial exception if either cleanup path reports a failure.
The additional regression asserts disconnected mock radio and no active poll.

## STAB-07 prior focused baseline — November 15, 2026 (superseded)

**Historical checkpoint only; superseded by the final Track A acceptance below.**
At this earlier point, Track A was PARTIAL / TESTED and Track B was
BLOCKED / DEFERRED. Production release was and remains NO GO. This status
supersedes any interpretation that the STAB-07G–I proof of two smoke paths
established full application acceptance. Continue the Track A independent
application tests without reconstructing the exact Pi OS.

### Confirmed defect ledger

| Defect / reproduction | Small correction | Deterministic result |
| --- | --- | --- |
| Unexpected `LookupError` from post-radio worker initialization skips narrowly typed startup exception handler, leaves mock radio connected | Roll back on any ordinary `Exception`, re-raise original | Red before / green after, synthetic mock only |
| `stop()` raises `ExceptionGroup` during failed startup rollback, masking initiating `LookupError` | Report rollback exception while re-raising original failure | Red before / green after, no real device |
| Radio polling raises after radio connection and callback registration, before `_started` assignment; connection and callback remain live | Cancel partial radio polling and run existing pre-start FT8/radio cleanup, preserving original cause | Red before / green after; disconnected mock radio, no scheduled poll |

All changes are in the existing `ApplicationRuntime.start()` lifecycle; no new
radio-control owner, manager, watchdog, queue, service or CAT path was added.
`tests/test_stab07_functional_startup_recovery.py` owns these synthetic
regressions. No operator-visible behavior change or shared consumer interface
change was made. Previous STAB-07I preference-flush correctness is preserved.

### Measured validation and provenance

- Reviewed parent STAB-07L GitHub commit:
  `6c97dc0d2730eee6d564ed3b9ee238d856fb9191` (draft PR #469).
- Source-correct baseline on Forge: **4,348 passed, 7 skipped**.
- Three startup rollback cases fixed and validated on host x86 with a
  synthetic database and fake radio, followed by **4,351 passed, 7 skipped**.
- Strict MyPy: all 401 source modules pass; scoped Ruff passes;
  `git diff --check` passes. Whole-repo Ruff still reports four prior diagnostics
  in the unrelated USB observer; no observer changes were made.
- Forge isolated worktree:
  `/home/rt-remote/projects/rt-stab07-focused-20261115`.
  Run the reused development venv with `PYTHONPATH="$PWD/src"` to avoid
  importing a stale installed package.
- Draft review PR #471 is stacked on #469, never merged. The GitHub-generated
  first change commit was `f39fc3477c7f9f2a5a813741b26629b14e0af198`;
  the additional polling fix commit is
  `1f78668207ce63a8015c3f79ed1c4d221bf12fc8`.
  GitHub tree digest `12d69762e71b2d77139f729929e323888b107362`
  matches the independent Forge worktree commit tree exactly.
- Exact-head CI is via a *CI-only* `feature/**` ref pointing at the review
  commit because `.github/workflows/ci.yml` triggers on `feature/**` pushes
  and `main` PRs, not on stacked draft PRs. GitHub CI must be checked on
  the *latest* head, not inferred from a previous successful head.

### Track A acceptance coverage and unfinished gates

- Tested: existing single clean ARM64 mock-dashboard startup/heartbeat/shutdown
  and injected startup failure (STAB-07I); the three additional isolated mock
  startup rollback cases; existing broad Python regression coverage.
- Not yet demonstrated with the updated wheel in ARM64/Xvfb: full dashboard
  navigation responsiveness, every worker ownership combination, duplicate
  startup/shutdown under contention, partially initialized GUI teardown,
  permanently blocked worker stop/recovery, and unexpected Tk callbacks.
- Not yet independently accepted in the new scenario matrix: synthetic
  SQLite transaction/WAL and schema rollback across runs, GPS hot-unplug,
  fake FT8 state/PTT release under failure, and full GUI recovery.
- Physical screen, GPS/USB, CAT/PTT receive proof, production QSO/WAL safe
  rollback, trusted release/launch identity and parked systemd acceptance
  remain production-only gates with separate owner authorization.

### Track B bounded research conclusion — BLOCKED / DEFERRED

The exact Pi target remains `libc6:arm64 2.41-12+rpt1+deb13u3` and
`libssl3t64:arm64 3.5.6-1~deb13u2+rpt1`. **Only 14 of 16 exact candidate
archives are publisher-index-authenticated.** The other two `.deb` archives
are quarantined; five extracted native file hashes match Pi observations but
neither the archive signatures nor a complete executable native closure is
proven. Approaches checked without recovering a signed historical chain:

1. Signed current Raspberry Pi `trixie` InRelease and Packages indexes:
   cryptographically valid but do not contain the installed historical
   revisions.
2. Historical third-party snapshot discovery, including prior Internet
   Archive CDX queries and subsequent public snapshot/mirror research:
   no independently authenticated matching historical InRelease and Packages
   pair found.
3. Direct dated historical publisher index path attempts and publisher pool
   discovery: guessed historical index returned no signed metadata; official
   pool still supplies candidate bytes but cannot authenticate historical
   publisher release intent.

**Research stop rule invoked.** Do not run a fourth equivalent search or
execute quarantined ELF files. More complete Pi loaded-library and native
file inventory and a new isolated exact-image rebuild remain deferred until
new publisher-signed evidence or separately approved equivalent proof appears.
The earlier STAB-07G/I Debian ARM64 test image remains suitable for functional
mock application testing, with its OS non-equivalence clearly recorded.

### Integration, dependency and release dispositions

- PR #469 (STAB-07L) remains open draft; #471 depends on its exact head.
  Merge order after **separate** owner approval and successful exact-head CI:
  review earlier STAB-07 parent chain, then #469, then #471. Retarget/retest
  after any upstream merge before considering integration complete.
- PR #414 (DOC-03 architecture reconciliation) remains an unfinished separate
  draft; do not silently incorporate its unpublished observations or CI changes.
- DOC-01/DOC-02/DOC-03 inventory and responsibility reconciliation remain
  pending beyond the precise runtime startup ownership updated here.
- No production service, radio, SQLite/QSO data, RF, OPNsense, or network
  configuration was changed. No infrastructure repository commit is required
  for these offline code/documentation changes.
- Rollback: leave drafts unmerged or discard the specific review branch;
  private synthetic databases/worktrees are disposable after manual review.
  No production rollback was executed or is implied.

### Track A follow-up: shutdown retry and disposable persistence (2026-11-15)

A separate deterministic mock test exposed a confirmed shutdown retry defect:
when the first attempt fails to disconnect the radio, `ApplicationRuntime`
correctly retains `_started=True` and continues stopping unrelated services,
including the preference executor. On a second shutdown attempt, radio release
can succeed, but a second preference flush on that already-stopped executor
reports a **false new shutdown failure**. The first failure is still reported
truthfully. The minimum fix adds a lock-protected read-only
`OperatorPreferenceService.is_stopped` property and skips repeat preference
flush/stop during a retry; it does not bypass radio disconnect or FT8 cleanup.
New deterministic tests validate first-attempt failure reporting, successful
retry, duplicate-start rejection, and radio release before a deliberately
blocked nonradio cleanup callback. They use mock radio/GPS only; an indefinitely
blocked callback still requires external supervision and remains an acceptance
limitation, not a proven recoverable operation.

Disposable SQLite tests independently exercised transactional migration rollback
of an injected partial schema update, recovery by replaying the genuine v22
migration, repeat initialization, and synthetic WAL commit/rollback/reopen
integrity. This is **not** a production QSO rollback rehearsal and does not
assert that all application's runtime connections use WAL by default.

Test ownership: `tests/test_stab07_functional_shutdown.py` and
`tests/test_stab07_functional_persistence.py`. The new preference service
property is a read-only lifecycle observation, not a new public write path.

**Expanded current Forge gate (2026-11-15):** The complete source-correct
suite after the shutdown retry, SQLite and GPS fake-failure tests is
**4,357 passed, 7 skipped**. Strict MyPy covers **401 source files**, and
`ruff check src tests` plus `git diff --check` pass. The separate legacy
whole-repository USB-observer Ruff findings are unchanged. This establishes
host deterministic regression coverage only; the new source has not yet been
rebuilt and re-executed as a freshly installed ARM64 dashboard wheel.


## Consolidated STAB-07 offline acceptance — 2026-11-15 (current)

**Track A: COMPLETE for the explicitly hardware-disabled mock application and
standalone deterministic fake-adapter scope, pending final exact-head CI.
Track B: BLOCKED / DEFERRED under the three-approach research stop rule.
Overall offline workstream: READY FOR DRAFT PR REVIEW once exact-head CI passes.
Production: NO GO. Owner-authorized merge and parked physical acceptance remain
separate gates.**

### Confirmed defects and smallest corrections

1. Ordinary unexpected startup exception bypassed rollback and left a mock
   radio connected; `ApplicationRuntime.start()` now performs owned cleanup.
2. Rollback `ExceptionGroup` masked the original startup cause; it is recorded
   while the initiating exception is preserved.
3. `polling.start()` failed after radio connection but before runtime `_started`
   assignment; partial poll registration and connected radio are now released.
4. After failed radio disconnect, retry re-flushed a previously stopped
   preference executor and reported a false new failure; the existing runtime
   owner now skips only that already-completed preference cleanup, using a
   lock-protected read-only `is_stopped` status. No radio/PTT priority changes.

Each defect was reproduced in deterministic fake-device tests before its
correction. No new manager, daemon, watchdog, queue, CAT path or privilege
boundary was added. Other confirmed behavioral defects: **none** in the tested
cases. Separate theoretical unverified production risks are not defects.

### Exact test evidence and scope

| Test requirement | Evidence and result | Scope/limitation |
| --- | --- | --- |
| Real complete Tk dashboard startup/shutdown | Private ARM64 QEMU/Xvfb updated wheel normal PASS twice; real heartbeat, SIGTERM and ordered cleanup, no errors | Disabled physical radio, FT8, sound, network, GPS device, radar and Forge adapters |
| Screen navigation and responsiveness | Updated ARM64 mock dashboard real Tk key dispatch `2`, `b`, `1` produced **DX → Browse → POTA**; heartbeat and orderly close PASS | Headless Xvfb, not the vehicle display/touchscreen |
| Worker start/stop ownership | Mock full runtime starts; ordering tests confirm radio release before blocked nonradio cleanup and one runtime-owned preferences drain | Not proof every possible worker is enabled simultaneously |
| Duplicate launch/close | Second `ApplicationRuntime.start()` refused without disrupting first; existing `_request_close_once` concurrent close test passes | One Tk close worker; no independent second process launched |
| Unexpected initialization/partial rollback | Three red-before-green startup regressions; ARM64 injected failure returns expected `3`, mock radio disconnected and no Tk root | No physical transmission test |
| Delayed, failed, permanently blocked cleanup | Fake cleanup error reporting/continuation tests, held-worker ordering test; private ARM64 Tk stalled-worker returns **75, NO GO**, never false success | No forced physical CAT/PTT recovery established |
| SQLite schema/data | Synthetic partial migration rollback retains schema v21, authentic v22 retry/idempotence succeeds, WAL commit/rollback/reopen and integrity check pass | Never touched production contacts/QSO/WAL; WAL explicitly enabled for synthetic trial |
| GPS/hardware disconnection | Mock GPS disconnect exception reported while radio already disconnected, safe isolation PASS | Actual USB hot-unplug remains parked acceptance |
| FT8 state and failed PTT release | Existing fake FT8 alarm/PTT timing and STAB-04 shutdown tests PASS, attempted radio release even when FT8 cleanup fails | Full FT8 UI disabled in ARM64 dashboard; physical RX cannot be certified |
| Exception recovery | Startup rollback preserves original error, cleanup attempts recorded; all fake tests PASS | Systemd crash recovery and hardware-specific exceptions remain production gates |

Fresh local package built only for private testing:
`rolling_thunder-4.4.1-py3-none-any.whl` SHA256
`d9ede5a4384794ac797bf77eeef856b038eb6df681d936e3f43be19c635dc28d`.
The installed ARM64 `application_runtime.py` and `operator_preferences.py`
were independently byte-compared with reviewed source. The installation used
an exact-hash, no-index, no-dependencies wheel into a **new clone** of the
existing STAB-07G/I sysroot and venv, never replacing that original evidence.
The embedded dashboard probe was separately hash-checked against checked-in
source. The native test sysroot is Debian-based and **not** Pi-byte-equivalent.

Private Forge evidence locations:

- Updated ARM64 sysroot and venv:
  `/home/rt-remote/workspaces/rt-stab07-focused-arm64`.
- Initial normal dashboard:
  `/home/rt-remote/workspaces/rt-stab07-focused-display/normal.log`.
- Injected startup failure:
  `/home/rt-remote/workspaces/rt-stab07-focused-display-failure/result.log`.
- Genuine Tk navigation:
  `/home/rt-remote/workspaces/rt-stab07-focused-display-navigation/result.log`.
- Repeated normal dashboard:
  `/home/rt-remote/workspaces/rt-stab07-focused-display-normal-repeat/result.log`.
- Expected blocked-worker NO-GO:
  `/home/rt-remote/workspaces/rt-stab07-focused-display-stalled-worker/result.log`.
- Source-correct host suite:
  `/tmp/rt-stab07-tracka-navigation-final.log` — **4,358 passed, 7 skipped**.

Tested Forge displays left no Xauthority or X95 socket residue, and no
`qemu-aarch64-static` / private Xvfb test process remained after completion.
Strict MyPy: 401 source files PASS. `ruff check src tests` plus scoped ARM64
runner/probe Ruff PASS, and `git diff --check` PASS. Whole-repo Ruff's four
existing USB-observer diagnostics remain unrelated and unchanged. The preceding
code commit `9a5d3acae0b84307514de49d7393cc359828db32` passed GitHub
Actions run `43681085328` on the exact commit; the final documentation/probe
head **must** receive its own independent CI result before acceptance.

### Integration decisions, deferred work and production gates

- Draft PR #471 contains functional fixes, deterministic tests and this
  consolidated status. It depends on open draft PR #469 and the earlier STAB-07
  parent chain. No merge is approved or performed. Check each parent CI and
  integration conflicts at the actual proposed merge heads. A CI-only feature
  ref enables exact-head GitHub Actions for the stacked draft branch.
- DOC-01/02/03 reconciliation remains separate. PR #414 is a **draft and
  unreviewed** and was not merged or silently imported. The scoped lifecycle
  ownership and test indexes were updated here; full historical architectural
  reconciliation is not a blocker for these reviewed functional corrections.
- Track B historical publisher metadata was sought by three materially distinct
  approaches and not found. The two Raspberry Pi-patched archives remain
  quarantined; 14/16 source-authenticated package count is unchanged, with
  only 22/52 sampled native bytes matching across the two partial extracts.
  Exact Pi reconstruction is **deferred** and not a gate for Track A.
- No live AnvilMobile state, service, CAT/PTT, RF, QSO database, privileged
  installer, network, or OPNsense configuration was accessed or changed in
  this focused validation. Accordingly, no infrastructure repository change
  was required.
- Parked acceptance still requires separate owner approval for the actual
  protected release, process supervision/identity, real-screen responsiveness,
  full physical USB/GPS/FT8 receive and de-key proof, QSO/WAL preservation,
  stop-deadline behavior and a real rollback. An abnormal physical transmit
  state must not be inferred safe from any fake run. **Production NO GO.**
- Rollback of this unmerged offline work is to abandon the review branch and
  retain or explicitly remove only its newly created private Forge test
  directories after reviewing provenance. Original STAB-07G/I scratch and
  all production state remain untouched.
