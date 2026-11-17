# REL-01 — parked production acceptance packet (prepared; NO GO)

**Preparation baseline:** merged `main`
`e31285240e8ea9dc193db235b1dbacc5c53e5f2d` (PR #484) as of 2026-11-17.
Earlier reconciliation recorded PR #480 and the 2026-11-16 owner-reported
field test; neither changes this packet's full-Pi NO GO verdict.
**Status:** written and reviewable **only**. No deployment, restart, mutating
privileged operation, source-database mutation, database restore, rollback,
CAT, physical PTT, USB reconfiguration or RF test has been performed by this
packet. At the owner's request, a protected SQLite online-backup snapshot of
the primary QSO database was written under
`/home/geoff/rolling-thunder-review`; see the evidence below. Owner-provided
passworded `sudo` was used only for read-only inspection of the installed
unit/drop-ins, wrapper and filesystem metadata.

## Authority and release decision

This document separates four approvals: **(1)** merges (if new fixes),
**(2)** privileged helper installation/change (if any), **(3)** a specific
parked exact-SHA production deployment/restart, and **(4)** any radio-powered
CAT/PTT/RF test. Each requires explicit owner authorization, with a parked
attestation close to the actual operation. Approval for this documentation
is not approval for any of those actions. No unattended transmission.

**Current release verdict: NO GO.** Green offline CI is not installed-image
attestation, independent physical RX, complete native package provenance,
or a tested data-preserving rollback. Do not schedule a release automatically.

## Verified installed-state snapshot

The read-only AnvilMobile and Forge evidence from 2026-11-15 is recorded in [`rel01-installed-state-snapshot-2026-11-15.md`](rel01-installed-state-snapshot-2026-11-15.md). Follow-ups identified the installed checkout at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, live QSO database/schema, device mappings, retries, MeshCore units, all system drop-in paths, and deployed wrapper hash/source. The installed wrapper has no visible mutex, transaction journal, or independent UI readiness check and is not tracked on current `main`. A fresh protected SQLite online-backup snapshot of the primary QSO DB was created and verified on 2026-11-17; its manifest and limits are recorded below. This snapshot is a consistent point-in-time backup, not a restore over the live DB. Separate MeshCore and optional outbox stores are outside its scope. PR #484's code-only rollback checks are covered by offline tests, but its candidate wrapper is not installed; the production rollback route therefore remains unaccepted. The verdict remains NO GO.

## Immutable evidence record to populate before execution

| Evidence field | Required source and validation | Current evidence |
| --- | --- | --- |
| Release candidate | Exact merged commit SHA; exact-head CI link/checks; dependency/wheel and source digests | Preparation baseline was `91315847e313d6b3f1e1eaad1f5a2b7dee7659e3`. PR #480 advanced current `main` to `3cfad7bc20a83a951617b0d45080af0064b85080`, deployed to Forge contact-sync only. This SHA is a planning reference for AnvilMobile, not an approved or installed Pi candidate. |
| Previous production | Current installed source SHA, runtime executable and cgroup, installed unit/drop-in hashes, approved launch witness | Clean editable checkout at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, Python 3.13.5, package 4.4.1; current `main` is 47 commits ahead. MainPID 60400 in the system service cgroup. Protected drop-in `60`, runtime loaded-byte witness and independent readiness heartbeat remain unverified. |
| Host identity | System scope `rolling-thunder.service`, MainPID, one process, runtime heartbeats, current boot ID and monotonic start ticks | Active `Type=simple` service, MainPID 60400, cgroup `/system.slice/rolling-thunder.service`; launcher flock is held. FT8 `arecord` and DMR SSH child are present. `NotifyAccess=none`; `active` is not application readiness. |
| Deploy path | Root-owned exact `/usr/local/sbin/rolling-thunder-deploy` contents/hash, SSH identity, sudo allowlist, single serialized lock and reconciliation | Installed wrapper is root-owned mode 0750, SHA-256 `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`. It validates exact SHA/clean checkout/remote containment, stops the unit, SQLite-backs up only the primary DB to `/var/backups/rolling-thunder-deploy`, validates integrity, deploys/migrates, then waits 3 seconds and checks systemd active state/SHA. No mutex, transaction journal, or independent readiness check is visible. Target dir exists root:root 0700. PR #484's serialized/journaled/readiness-aware candidate is merged at current `main` but is not installed. |
| QSO persistence | Live schema/counts, retry/outbox state, read-only integrity/FKs, verified consistent protected SQLite backup and rollback | At 09:29–09:33 EST, the live DB had schema metadata 22, 355 contacts (340 synced, 15 failed), 15 retry rows, and 693 synchronized FT8 outbox records; `integrity_check=ok` and zero FK violations. The newest AnvilMobile deployment backup also passed read-only integrity/FK checks and matched all 355 contact IDs and reported aggregate state, though per-retry fields and FT8 outbox IDs/payloads were not compared. Following the 18:53 EST Forge contact-sync deployment of PR #480 (`3cfad7bc20a83a951617b0d45080af0064b85080`), a read-only AnvilMobile check at about 18:55 EST reported schema 22, 355 synchronized contacts, zero retry rows, `integrity_check=ok`, and no foreign-key violations. Latest QSO time remained `2026-11-13T09:38:52.594808Z`. On the morning of 2026-11-16, the owner reported the field test went well and every contact synchronized without issue; exact test count/UUIDs and independent post-test DB evidence were not provided. The Forge backup created by that component deploy is `/var/backups/rolling-thunder-forge-deploy/contact-sync-20261115T235326Z-a6c9fa9d87d90ce9dbcfb7b46456563d9fdeeb4f.db`; it is distinct from the Pi QSO database. On 2026-11-17, an online SQLite backup was made from a read-only connection to the live primary DB while WAL mode was active and a WAL file was present (78,312 bytes observed at backup start). Artifact `/home/geoff/rolling-thunder-review/rolling-thunder-qso-20261117T041046Z.sqlite3`, SHA-256 `7780ea7a7d80abd53367e6a9946323ef185ad0a96d4c7063ce710ebb3d2e6883`, size 5,693,440 bytes, mode 0600 in a mode 0700 owner-only directory. Protected manifest: `/home/geoff/rolling-thunder-review/rolling-thunder-qso-20261117T041046Z.manifest.json`. Verification: schema 22, 367 contacts, 29 user tables, `integrity_check=ok`, zero FK violations, no WAL/SHM sidecars; the backup reopened into memory and every user-table row fingerprint matched the restored copy. The online backup API captured committed WAL state consistently; uncommitted test data was excluded in a separate offline WAL rehearsal. Snapshot covers only the primary QSO database, not separate MeshCore databases or alternate optional outbox stores. |
| Rollback | Original exact SHA and dependency compatibility; schema migration direction; wrapper rollback route, protected backup and responsible operator | PR #484 is merged at `e31285240e8ea9dc193db235b1dbacc5c53e5f2d`. Its offline coverage establishes a code-only rollback path that checks schema compatibility and readiness while preserving the live DB; CI #4056 passed (4,124 passed, 7 skipped). This candidate wrapper is not installed, and no production rollback was attempted. Existing installed wrapper remains the legacy hash above. Do not restore the snapshot over a newer live DB; production rollback remains NO GO pending separately approved installation and parked acceptance of the candidate path. |
| Physical safety | FT-891 red TX indicator, manual safe receive/power-off plan, FT8 alarm inhibit after fault, no unrestricted rekey | Merged #474 disabled the prior unverified unlock; merged #477 implements deliberate in-app 1–3–1 recovery after acknowledgment, and session restart clears the alarm; neither proves physical RX/de-key |
| USB/GPS/FT8 RX | Actual controller serial, DigiRig/audio capture, GPS freshness, native decoder receive-only and local UI latency | Configured radio CP2105/`ttyUSB1`, physical controls CP2102/`ttyUSB0`, GPS CP2102N/`ttyUSB3` are open by the dashboard process. FT8 capture process and C-Media device are present. Speech selects `CARD=Array`, not listed among capture devices. Operation and receive-only acceptance remain unverified. |
| Forge continuity | Read-only status for existing spots, weather, Wavelog/contact sync, PSK autoqueue timer/oneshot | At 18:55 EST after PR #480, Forge contact-sync was active and `GET http://192.168.9.170:8767/health` returned `availability=available`; AnvilMobile reported all 355 contacts synchronized and zero retry rows. An immediate probe during service startup had failed to connect and was followed by the successful health check. The earlier 08:04 PSK autoqueue oneshot is separate and does not establish contact delivery. |

## Parked preflight — no mutation until separately authorized

1. Owner verifies vehicle parked, no ongoing contact/QSO/FT8, stable battery,
   reachable console and emergency physical radio power-off. Keep antenna/RF
   load state documented. Confirm who owns stop and rollback decisions.
2. Revalidate exact candidate commit and required GitHub CI, `ruff check .`,
   strict MyPy, full pytest, documentation guard, and release-gate exclusions.
   Treat historical diagnostic lint debt as an exception only if reviewed.
3. The owner has now read the system unit, all drop-ins, and wrapper source/hash
   as root. Current wrapper SHA-256 is recorded above. Its lack of mutex,
   transaction journal, and independent UI readiness check remains a STOP
   condition; the wrapper is absent from current repository `main`.
   Verify effective configuration paths and runtime/source/dependency witness.
   `Type=simple`/`active` is not UI readiness.
4. A protected SQLite online-backup snapshot of the live primary database was
   created on 2026-11-17 at
   `/home/geoff/rolling-thunder-review/rolling-thunder-qso-20261117T041046Z.sqlite3`.
   Its SHA-256 is
   `7780ea7a7d80abd53367e6a9946323ef185ad0a96d4c7063ce710ebb3d2e6883` and its
   verified manifest is
   `/home/geoff/rolling-thunder-review/rolling-thunder-qso-20261117T041046Z.manifest.json`.
   It was captured through a read-only SQLite connection while the database
   used WAL mode and the WAL file was present. Integrity, foreign keys,
   schema/counts and a full in-memory restore fingerprint check passed. This
   snapshot covers only the primary QSO DB; separately reconcile other durable
   stores. Do not restore it over a newer live DB. For comparison, the newest
   existing candidate
   `/var/backups/rolling-thunder-deploy/rolling-thunder-20261114T010636Z-179c005f0f7f61df1004641db75897f42b3dd8ad.db` has passed read-only integrity/FK checks and matched schema, contact/sync counts, retry count, FT8 outbox count, latest QSO time, and all contact IDs. Per-retry field values and FT8 outbox IDs/payloads were not compared. Obtain a fresh verified backup as part of any separately approved deployment; reconcile optional outbox/durable state and preserve all WAL/contact/retry data. Do not replace a database from Git.
5. The inspected wrapper has no visible mutex or transaction journal, and no
   independent readiness check. Do not deploy through it until a tracked,
   reviewed wrapper (or another verified gate) serializes invocations, records
   recoverable transaction state, verifies the protected backup, and attests
   application readiness. No sudo expansion or production wrapper changes are
   authorized by this packet.
6. Validate native package trust/ABI. Two Raspberry Pi-patched archive pins
   remain quarantined pending authenticated historic signed package indexes;
   do not execute or silently treat those as equivalent. If release path
   requires this exact image, STOP until provenance resolved.
7. The 15-contact backlog is resolved after the approved PR #480 Forge
   contact-sync deployment: the 2026-11-15 read-only snapshot showed all 355
   local contacts synchronized, zero retry rows, and Forge health available.
   On the morning of 2026-11-16, the owner reported a successful field test and
   that every contact synchronized without issue. The exact test count/UUIDs,
   independent post-test DB evidence, and saved Wavelog city/grid/state values
   were not supplied. The owner-provided profile screenshot showed city `Ohio`
   and grid `EM79XM`; document whether those values were cleared, together
   with CQ 4 / ITU 8, before treating unknown-location metadata as verified.
   The successful PSK autoqueue oneshot remains unrelated to this
   contact-sync result.

## Approved deployment sequence (future only)

After *new* owner approval for a specific parked target SHA:

1. Freeze target, record previous SHA and immutable evidence manifest.
2. Invoke an exact-SHA deployment path only after its source and hash are
   reviewed, one transaction mutex is validated, recovery state is journaled,
   and independent application readiness is checked. The currently installed
   wrapper does not establish these gates. Refuse concurrent or uncertain runs.
3. Read wrapper's transaction outcome, commit identity and **actual**
   installed/running SHA from an independent attestation. Do not equate a
   successful shell exit, checkout SHA or systemd `active` with healthy UI.
4. Verify one managed dashboard PID/cgroup, fresh Tk heartbeat, status and
   controlled UI navigation; test GPS/controller and FT8 **receive only**
   before any separately approved powered-radio or transmission scenario.
5. Verify local contacts, retry ledger, SQLite WAL/integrity, Forge reachability
   and non-loss of any QSO stored during the release. Retain before/after
   counts and exact UUID set changes.
6. Observe orderly stop/start evidence and bounded timing, distinguish
   `RT_PTT_RELEASE` command log from physical de-key, and inspect exact
   installed `TimeoutStopSec` (historically 20 seconds).
7. Record PASS/NO GO per gate, operator observation, time, hashes and
   journal. No automatic promotion if a required gate is missing.

## Physical FT8 gate: separate authorization only

Merged #474 stops unverified automatic-style release; a separate owner-directed
recovery proposal permits Voice Cancel followed by deliberate 1–3–1 in FT8,
and a process restart intentionally starts a clear session alarm. These are
operator-controlled recovery actions, **not** independent physical RX proof.
Neither procedure issues CAT/PTT or starts an FT8 QSO. On any red TX indicator, unclear radio power, stuck CAT, unexpected
FT8 audio or uncertain release: cease automation, physically de-key/power down
using the owner's safe procedure, preserve logs and STOP the release. Software
TX0 success or polled `transmitting=False` never substitutes for observation.
Any deliberate transmit/RF test requires a *distinct* owner-approved parked
plan, appropriate antenna/dummy load, safety observer and hard abort.

## Failure and rollback — preserve data and physical safety

- If install is indeterminate, the journal is missing/invalid, two dashboards
  exist, launch witness is stale, wrapper identity differs, readiness missing,
  or there is any PTT uncertainty: **STOP**, no retry loop, no force kill as
  a supposed RF de-key.
- Independently assess schema compatibility before application rollback. Do
  not restore an older SQLite over newly completed QSOs, lose WAL frames,
  truncate retry metadata, or delete transaction receipts to unblock a run.
- Roll back *application code* only through the verified serialized wrapper,
  and separately restore privileged *helper code* only under its own grant.
  Record returned exact SHA, genuine UI health, database preservation and
  original issue reproduction. Refuse rollback if it risks data loss.
- Preserve immutable audit receipts/logs and the preflight/rollback evidence
  packet. A missing ability to revert safely is **NO GO** before deploying.

## Acceptance record — deliberately unfilled

| Gate | Actual evidence | Result |
| --- | --- | --- |
| Owner parked approval and operator readiness | Not obtained | NO GO |
| Exact release SHA, native identity, trusted install | Not verified | NO GO |
| Protected wrapper, drop-ins, mutex and recovery | Unit/drop-ins and wrapper SHA/source read; no mutex/journal/readiness check in wrapper; newest DB backup validated read-only; no wrapper mutex/journal/readiness check | NO GO |
| Consistent QSO/WAL backup plus rollback | New protected online backup made and verified (manifest records artifact/hash/checks); only primary QSO DB included. PR #484 code-only rollback passes offline CI, but candidate wrapper is not installed and production rollback remains unaccepted. No restore performed. | NO GO |
| One managed UI process and working controls | Not field-tested | NO GO |
| GPS, Digirig, FT8 receive-only | Not field-tested | NO GO |
| CAT/PTT/physical receive | Separate authorization not obtained | NO GO |
| Release disposition | No AnvilMobile application deployment/restart authorized or executed; the separately approved Forge contact-sync component deployment for PR #480 completed and passed its health/data checks | **NO GO for full AnvilMobile release** |

## Change control

This packet records the owner-approved PR #480 exact-SHA deployment to the
Forge contact-sync service and the owner-requested protected primary-QSO
SQLite snapshot. The backup operation read the source database and wrote a
separate artifact; it did not mutate the live database or stop/restart the
service. The installed AnvilMobile service/wrapper, Pi runtime, MeshCore units,
network configuration, OPNsense, credentials and radio configuration were not
changed. A future change affecting the listed network
infrastructure must be committed in the private
`spifford3472/ki5vnb-qth-infrastructure` repository with paths, jobs,
validation, rollback and change history. Roll back this document by reverting
its Git commit. Source of truth remains installed observations and approved
transaction receipts, not this planning checklist.

- 2026-11-15: Prepared exact-main parked readiness, rollback and separate
  physical-radio gates. All execution fields intentionally remain NO GO.
- 2026-11-15 read-only update: recorded the live system-scoped Pi unit,
  independent MeshCore collector PID, USB enumeration, Forge active services,
  and successful PSK autoqueue invocation; protected state and backups remain
  unverified, so the verdict remains NO GO.
- 2026-11-15 follow-up: identified installed source SHA/package, dashboard
  launcher lock and configured/open serial device mappings; read-only SQLite
  checks verified schema 22, 355 contacts, clean integrity/FKs, and 15 HTTP 503
  retries. Identified the enabled user MeshCore collector (currently retrying
  with its USB path absent), inactive enabled traffic worker, and preserved
  broker/observation/traffic DB counts. No backup or production mutation was
  performed.
- 2026-11-15 privileged read-only follow-up: confirmed all system-unit drop-ins,
  wrapper SHA-256 and source. The installed wrapper has no visible mutex,
  transaction journal or independent UI-ready check, backs up only the primary
  DB, and targets the separate root-only `/var/backups/rolling-thunder-deploy`
  directory. The newest listed backup now passes read-only integrity/FK checks and matches
  the live contact IDs and reported aggregate state; wrapper source is absent
  from current `main`. No
  deployment or other production mutation occurred;
  verdict remains NO GO.

- 2026-11-15 read-only database comparison: the newest deployment backup and
  live database both passed integrity and foreign-key checks and matched schema
  22, 355 contacts and all contact IDs, 340 synchronized/15 failed contacts,
  15 retry rows, 693 synchronized FT8 outbox records, and latest QSO time.
  Per-retry field values and FT8 outbox IDs/payloads were not compared. No
  production state was changed; overall release verdict remains NO GO.

- 2026-11-15 16:43 EST read-only sync follow-up: AnvilMobile still had 15
  failed contacts after a scheduled retry (counts advanced to 858–2,262); Forge
  contact-sync remained active and its health endpoint returned available.
  Source inspection found the Pi client drops the Forge 503 response body, while
  Forge can return 503 for either Wavelog or ledger unavailability. Exact cause
  remains unresolved; inspect Forge ledger and Wavelog application logs before
  repair. No manual sync or production mutation was performed.

- 2026-11-15 16:49 EST read-only follow-up: Forge logged 15 `/contacts` 503s
  around 16:43 and 16:48 while `/health` remained 200. Its ledger integrity
  check passed with 349 synchronized/imported entries and no pending entries.
  All 15 failed Pi contacts lack grid/state/CQ/ITU metadata and route through
  `Mobile - Unknown Location` before the ledger claim. This narrows the fault
  domain but does not prove the cause; failed UUID correlation and fallback
  station binding/profile/logbook checks remain. No production data or profile
  was changed.

- 2026-11-15 read-only follow-up: confirmed the Forge station-binding table has
  no row for `Mobile - Unknown Location`. Profile existence/visibility,
  compatibility, and `KI5VNB Main` membership remain unverified; no profile
  creation or binding write was performed.

- 2026-11-15 17:20 EST read-only follow-up after owner-reported Wavelog
  station addition: the Pi still showed 15 failed contacts and retry rows.
  Three Forge health checks returned unavailable because configured station
  `Mobile` could not be found. The exact station added and the reason the
  legacy profile is missing remain unknown. No further Wavelog or Rolling
  Thunder production changes were made during this inspection.

- 2026-11-15 18:53–18:55 EST follow-up: PR #480 commit
  `3cfad7bc20a83a951617b0d45080af0064b85080` was deployed to the isolated
  Forge `contact-sync` component with the exact-SHA wrapper. The wrapper reported
  deployment success and created
  `/var/backups/rolling-thunder-forge-deploy/contact-sync-20261115T235326Z-a6c9fa9d87d90ce9dbcfb7b46456563d9fdeeb4f.db`.
  The first health probe ran during startup and could not connect; a later
  read-only check at 18:55:19 EST confirmed the service active and health
  `availability=available`. A read-only AnvilMobile DB check then reported
  schema 22, 355 contacts all synchronized, zero retry rows,
  `integrity_check=ok`, no foreign-key violations, and unchanged latest QSO
  time `2026-11-13T09:38:52.594808Z`. No AnvilMobile app deployment/restart,
  manual retry/replay, or QSO rewrite occurred. Full AnvilMobile release remains
  NO GO under the independent wrapper, provenance, backup/rollback, and
  receive-only acceptance gates. The unknown-location Wavelog profile's saved
  grid/city/state values were not independently read; the owner-provided
  screenshot showed `Ohio` and `EM79XM`, so verify those before field
  acceptance.

- 2026-11-16 morning owner-reported field test: the owner said the test went
  well and every contact synchronized without issue. Exact test count/UUIDs,
  independent post-test database output, and whether the Wavelog fallback
  profile city/grid/state fields were checked were not provided. This confirms
  reported end-to-end behavior for the test but does not change the full
  AnvilMobile release NO GO disposition.

- 2026-11-16 repository reconciliation: current merged `main` is
  `3cfad7bc20a83a951617b0d45080af0064b85080`. PR #478 was updated onto current `main` as draft head
  `b9413a81d87e849b0b1cacfa9d54f6037bd7f6ee`. Exact-head CI run #4033 passed
  documentation inventory/local-link validation, Ruff, MyPy, and pytest for
  the updated review state. The PR remains a draft pending review. PR #479 remains a separate draft; its proposed
  MeshCore removal is neither merged nor deployed, and the proposal does not
  stop/uninstall already-installed MeshCore user services or remove their data.
  The 15-contact retry backlog was resolved by the isolated Forge contact-sync
  deployment of #480 and the 2026-11-15 read-only Pi database check. The
  2026-11-16 field test is owner-reported, without count/UUID or independent
  post-test DB evidence. The screenshot confirmed CQ 4 / ITU 8 and displayed
  `Ohio` / `EM79XM`; saved Wavelog city/grid/state values remain unverified.

- 2026-11-17 source-status reconciliation: current merged `main` is
  `b9f1b2c5149ea8ebf811b519568b136c36686adf`. PR #481's GPS polling
  quiescence fix merged at `438894deab3dff3adcfffbd3b1447ac460bb8184`, and
  PR #479's MeshCore application-source removal merged at the current `main`
  SHA while retaining Forge-backed OHGO. Neither source merge was deployed to
  AnvilMobile. No independent MeshCore service was stopped, disabled, or
  uninstalled, and no MeshCore database was changed or deleted. The last
  installed-state observation remains the dated 2026-11-15 snapshot, not a
  current host check. Full AnvilMobile release disposition remains **NO GO**;
  deployment, parked peripheral/receive-only acceptance, and any service
  cutover require their existing separate owner approvals.

- 2026-11-17 post-merge reconciliation: PR #478 merged at
  `2632dc8b4445ed84644d9324f7fe91bb6175b106`; this is the current `main`
  baseline at that point. PR #482 was still a draft documentation
  reconciliation then, and was not a deployment approval. The installed-state
  evidence above remains the dated 2026-11-15 inspection plus owner-reported
  2026-11-16 field result; no current
  host or hardware verification is implied. Full AnvilMobile release remains
  **NO GO**.

- 2026-11-16 22:01 EST read-only refresh: PR #482 has since merged. Current
  `main` is `a806ab65470c345ccb7acfaaf00c71e9dc262cc6`; its tree matches the
  CI-tested PR #482 head `8a4a9cfaaf1da9d14939d7464a33bd2abfc75112`, whose
  workflow run #4051 passed. The installed AnvilMobile checkout remained
  detached and clean at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, 88 commits
  behind current `main`. The system service was active with MainPID `60400`,
  cgroup `/system.slice/rolling-thunder.service`, launcher
  `/home/geoff/projects/rolling-thunder-v4/deploy/rolling-thunder-autostart`,
  and `TimeoutStopSec=20s`. Its tracked launcher file hash matched the Git
  object in the installed checkout. These facts do not prove which Python code
  is loaded by the running process. Systemd listed four drop-ins
  (`50-ft8-evidence.conf`, `60-ft8-period.conf`,
  `70-ft8-attempt-delivery.conf`, and
  `r1a-timing.conf`); their protected contents and hashes were not readable in
  this refresh. The current privileged deployment wrapper was also not
  reverified; its previously captured hash/source is historical evidence.

- The user-level `meshcore-collector.service` remained enabled and active
  (MainPID `1078`) while `meshcore-traffic-worker.service` was enabled but
  inactive. This is installed-service drift after source removal in #479; it
  does not establish whether a serial device was open at inspection time.
  Resolve service ownership through a separately approved plan before physical
  USB acceptance.

- A read-only immutable-mode query returned 367 contacts, zero contact retry
  rows, 721 synchronized FT8 performance-outbox rows, schema metadata version
  22, and two `uncertain` FT8 transmit-intent rows. A later filesystem check
  found an active `rolling-thunder.db-wal` sidecar of 309,032 bytes. Immutable
  mode does not include WAL frames, so those SQL results describe only the
  main database file and are **not current database, integrity, backup, or
  QSO-preservation evidence**. The main-file integrity result is not evidence
  for the live database. Do not rely on those counts for release acceptance;
  a parked, approved SQLite-consistent snapshot and its verification remain
  mandatory. **Update:** an owner-requested online SQLite backup was
  subsequently created and verified; it captured the live primary QSO database
  consistently while WAL mode was active. See the manifest and checks in the
  evidence record above. That backup does not include separate MeshCore or
  optional outbox databases. The two intent rows are not evidence of physical
  PTT state.

- The fresh Forge health check was not completed because the authorized
  Desktop Commander connection failed. Earlier Forge health output remains
  historical and is not current service verification.

**Disposition remains NO GO.** The primary QSO database now has a verified
consistent backup, but the installed legacy wrapper and unverified protected
drop-ins, installed/source gap, residual MeshCore service, incomplete
Raspberry Pi native-package provenance, separate durable stores, and
uncompleted parked USB/GPS/FT8 receive and physical-safety acceptance remain
gates. The candidate serialized wrapper and code-only rollback path from PR
#484 are not installed or production-accepted. The operator must retain the
ability to clear the application lockout; a system restart restores operator
control, but software status or restart is not proof that physical PTT has
released. No deployment or restart is authorized by this refresh.
