# REL-01 — parked production acceptance packet (prepared; NO GO)

**Preparation baseline:** merged `main`
`91315847e313d6b3f1e1eaad1f5a2b7dee7659e3` as of 2026-11-15.
**Status:** written and reviewable **only**. No deployment, restart, mutating
privileged operation, CAT, physical PTT, USB reconfiguration, database copy,
rollback or RF test has been performed by this packet. Owner-provided
passworded `sudo` was used only to read the installed unit/drop-ins, wrapper,
and filesystem metadata.

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

The read-only AnvilMobile and Forge evidence from 2026-11-15 is recorded in [`rel01-installed-state-snapshot-2026-11-15.md`](rel01-installed-state-snapshot-2026-11-15.md). Follow-ups identified the installed checkout at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, live QSO database/schema, device mappings, retries, MeshCore units, all system drop-in paths, and the deployed wrapper hash/source. The wrapper has no visible mutex, transaction journal, or independent UI readiness check and is not tracked on current `main`. The wrapper-target directory inventory now shows multiple backups. The newest is timestamped 2026-11-14 01:06:36Z, before the current dashboard process started; its SQLite integrity and data contents have not been validated, so no verified current backup is established. The verdict remains NO GO.

## Immutable evidence record to populate before execution

| Evidence field | Required source and validation | Current evidence |
| --- | --- | --- |
| Release candidate | Exact merged commit SHA; exact-head CI link/checks; dependency/wheel and source digests | Current `main` SHA above is a *planning reference*, not an approved candidate |
| Previous production | Current installed source SHA, runtime executable and cgroup, installed unit/drop-in hashes, approved launch witness | Clean editable checkout at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, Python 3.13.5, package 4.4.1; current `main` is 47 commits ahead. MainPID 60400 in the system service cgroup. Protected drop-in `60`, runtime loaded-byte witness and independent readiness heartbeat remain unverified. |
| Host identity | System scope `rolling-thunder.service`, MainPID, one process, runtime heartbeats, current boot ID and monotonic start ticks | Active `Type=simple` service, MainPID 60400, cgroup `/system.slice/rolling-thunder.service`; launcher flock is held. FT8 `arecord` and DMR SSH child are present. `NotifyAccess=none`; `active` is not application readiness. |
| Deploy path | Root-owned exact `/usr/local/sbin/rolling-thunder-deploy` contents/hash, SSH identity, sudo allowlist, single serialized lock and reconciliation | Wrapper is root-owned mode 0750, SHA-256 `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`. It validates exact SHA/clean checkout/remote containment, stops the unit, SQLite-backs up only the primary DB to `/var/backups/rolling-thunder-deploy`, validates integrity, deploys/migrates, then waits 3 seconds and checks systemd active state/SHA. No mutex, transaction journal, or independent readiness check is visible. Target dir exists root:root 0700; its contents remain unverified. Wrapper source is absent from current main; no production action taken. |
| QSO persistence | Live schema/counts, retry/outbox state, read-only integrity/FKs, verified consistent protected SQLite backup and rollback | At 09:29–09:33 EST, the live DB had schema metadata 22, 355 contacts (340 synced, 15 failed), 15 retry rows, and 693 synchronized FT8 outbox records; `integrity_check=ok` and zero FK violations. All retries had the same contact-upload error class, with counters 772–2,176 at 09:33. Deployment backup files exist; the newest is timestamped 2026-11-14 01:06:36Z, before the current process start, and has not been validated or copied. Wrapper backup targets only the main DB; optional outbox path and its data remain to be reconciled. |
| Rollback | Original exact SHA and dependency compatibility; schema migration direction; wrapper rollback route, protected backup and responsible operator | Not tested against current release |
| Physical safety | FT-891 red TX indicator, manual safe receive/power-off plan, FT8 alarm inhibit after fault, no unrestricted rekey | Merged #474 disables unverified unlock; a separate owner-directed review restores deliberate in-app 1–3–1 override after acknowledgment, and session restart clears alarm; physical RX remains unverified |
| USB/GPS/FT8 RX | Actual controller serial, DigiRig/audio capture, GPS freshness, native decoder receive-only and local UI latency | Configured radio CP2105/`ttyUSB1`, physical controls CP2102/`ttyUSB0`, GPS CP2102N/`ttyUSB3` are open by the dashboard process. FT8 capture process and C-Media device are present. Speech selects `CARD=Array`, not listed among capture devices. Operation and receive-only acceptance remain unverified. |
| Forge continuity | Read-only status for existing spots, weather, Wavelog/contact sync, PSK autoqueue timer/oneshot | Forge contact-sync is active, but 15 local contacts currently have HTTP 503 failures and are scheduled for retry; the last-24-hour unit journal query returned no entries. PSK autoqueue oneshot at 08:04 succeeded, which does not establish contact delivery. |

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
4. Validate the newest existing candidate
   `/var/backups/rolling-thunder-deploy/rolling-thunder-20261114T010636Z-179c005f0f7f61df1004641db75897f42b3dd8ad.db` read-only: verify it opens, passes integrity/FK checks,
   and compare schema, contact/sync counts, retry state and latest QSO with the
   current DB. It predates the current process start, so establish a fresh
   consistent backup as part of any separately approved deployment. Reconcile
   the optional outbox/durable state; preserve all WAL/contact/retry data. Do
   not replace a database from Git.
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
7. Resolve the observed 15 HTTP 503 contact-sync failures and verify delivery
   without deleting or manually replaying records. Recheck Forge service and
   job state; the successful PSK autoqueue oneshot is not end-to-end QSO
   delivery evidence.

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
| Protected wrapper, drop-ins, mutex and recovery | Unit/drop-ins and wrapper SHA/source read; no mutex/journal/readiness check in wrapper; wrapper-target backup contents unverified | NO GO |
| Consistent QSO/WAL backup plus rollback | Multiple copies listed; newest predates current process start and has not been validated | NO GO |
| One managed UI process and working controls | Not field-tested | NO GO |
| GPS, Digirig, FT8 receive-only | Not field-tested | NO GO |
| CAT/PTT/physical receive | Separate authorization not obtained | NO GO |
| Release disposition | No deployment authorized or executed | **NO GO** |

## Change control

This packet changes documentation only. Owner-provided privileged commands
read unit/drop-in/wrapper state and path metadata; no services, deploy wrappers,
Pi, Forge, 192.168.9.0/24, 192.168.10.0/24, OPNsense, credentials or radio
configurations were modified. A future change affecting the listed network
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
  directory. The newest listed backup predates the current process start and
  remains unvalidated; wrapper source is absent from current `main`. No
  deployment or other production mutation occurred;
  verdict remains NO GO.
