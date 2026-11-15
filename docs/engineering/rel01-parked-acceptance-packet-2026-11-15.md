# REL-01 — parked production acceptance packet (prepared; NO GO)

**Preparation baseline:** merged `main`
`91315847e313d6b3f1e1eaad1f5a2b7dee7659e3` as of 2026-11-15.
**Status:** written and reviewable **only**. No deployment, restart, privileged
execution, CAT, physical PTT, USB reconfiguration, database copy, rollback or
RF test has been performed by this packet.

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

The read-only AnvilMobile and Forge evidence from 2026-11-15 is recorded in [`rel01-installed-state-snapshot-2026-11-15.md`](rel01-installed-state-snapshot-2026-11-15.md). It confirms the system-scoped dashboard unit and identifies an independent MeshCore collector process outside its cgroup. The protected checkout/configuration/databases remain inaccessible; installed SHA and data backup are still unverified.

## Immutable evidence record to populate before execution

| Evidence field | Required source and validation | Current evidence |
| --- | --- | --- |
| Release candidate | Exact merged commit SHA; exact-head CI link/checks; dependency/wheel and source digests | Current `main` SHA above is a *planning reference*, not an approved candidate |
| Previous production | Current installed source SHA, runtime executable and cgroup, installed unit/drop-in hashes, approved launch witness | Unit active; MainPID 60400 in `/system.slice/rolling-thunder.service`; launcher path and 4 drop-in names observed. Runtime source SHA, protected drop-in contents/hashes, and fresh heartbeat inaccessible. A separate MeshCore collector PID 1078 is outside this cgroup. See 2026-11-15 snapshot. |
| Host identity | System scope `rolling-thunder.service`, MainPID, one process, runtime heartbeats, current boot ID and monotonic start ticks | System service is active/running, MainPID 60400, cgroup `/system.slice/rolling-thunder.service`; one listed UI process plus DMR SSH child. UI heartbeat, boot ID and protected full process identity not verified. |
| Deploy path | Root-owned exact `/usr/local/sbin/rolling-thunder-deploy` contents/hashes, SSH identity, sudo allowlist, serialized lock and reconciliation approval | Unit launcher path visible; wrapper, lock, SSH identity, sudo allowlist and protected drop-in hashes remain inaccessible. |
| QSO persistence | Live schema, counts/max UUIDs, `PRAGMA integrity_check`, foreign keys, verified SQLite **online consistent backup with WAL** and encrypted/protected copy | DB paths, schemas, counts, retry/outbox state, WAL and backup are inaccessible; no copy or backup was taken. Never use a raw active-WAL copy as consistency proof. |
| Rollback | Original exact SHA and dependency compatibility; schema migration direction; wrapper rollback route, protected backup and responsible operator | Not tested against current release |
| Physical safety | FT-891 red TX indicator, manual safe receive/power-off plan, FT8 alarm inhibit after fault, no unrestricted rekey | Merged #474 disables unverified unlock; a separate owner-directed review restores deliberate in-app 1–3–1 override after acknowledgment, and session restart clears alarm; physical RX remains unverified |
| USB/GPS/FT8 RX | Actual controller serial, DigiRig/audio capture, GPS freshness, native decoder receive-only and local UI latency | Two CP210x, one CP2105 dual UART, C-Media USB audio, hubs and storage enumerated. Protected config-to-role mapping, GPS freshness, audio capture, native decoder and UI latency not verified. |
| Forge continuity | Read-only status for existing spots, weather, Wavelog/contact sync, PSK autoqueue timer/oneshot | Forge spots and contact-sync services active; PSK autoqueue oneshot at 08:04 EST succeeded (exit 0), next timer 08:05. End-to-end backlog and delivery remain unverified; prior oneshot failure is historical, not current proof. |

## Parked preflight — no mutation until separately authorized

1. Owner verifies vehicle parked, no ongoing contact/QSO/FT8, stable battery,
   reachable console and emergency physical radio power-off. Keep antenna/RF
   load state documented. Confirm who owns stop and rollback decisions.
2. Revalidate exact candidate commit and required GitHub CI, `ruff check .`,
   strict MyPy, full pytest, documentation guard, and release-gate exclusions.
   Treat historical diagnostic lint debt as an exception only if reviewed.
3. Independently read **system** `systemctl show` (not `--user`), unit
   MainPID/cgroup, drop-in file list, protected unit contents and hashes,
   runtime heartbeat, SHA plus source/dependency witness; compare every source
   with the signed candidate. Missing protected evidence means STOP.
4. Obtain protected, transactional SQLite backup using the approved SQLite
   backup mechanism, verify the backup opens and passes integrity/foreign-key
   checks, and preserve all live WAL/contact/retry data. Establish SHA,
   schema, count and last-QSO identifiers. Do not replace database from Git.
5. Inspect approved wrapper and its **single mutex domain**. A helper lock
   and inline wrapper lock must not be disjoint; crash journal and recovery
   inspector must refuse indeterminate transactions. No sudo expansion.
6. Validate native package trust/ABI. Two Raspberry Pi-patched archive pins
   remain quarantined pending authenticated historic signed package indexes;
   do not execute or silently treat those as equivalent. If release path
   requires this exact image, STOP until provenance resolved.
7. Recheck the current Forge interface and job state. The 2026-11-15 snapshot
   observed a successful PSK autoqueue oneshot, but did not establish end-to-end
   contact delivery or clear the durable contact-sync backlog.

## Approved deployment sequence (future only)

After *new* owner approval for a specific parked target SHA:

1. Freeze target, record previous SHA and immutable evidence manifest.
2. Invoke **only** the approved root-owned exact-SHA deployment wrapper via
   the existing restricted deployment identity, under its validated
   transaction lock. Refuse concurrent or uncertain runs.
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
| Protected wrapper, drop-ins, mutex and recovery | Not verified | NO GO |
| Consistent QSO/WAL backup plus rollback | Not performed | NO GO |
| One managed UI process and working controls | Not field-tested | NO GO |
| GPS, Digirig, FT8 receive-only | Not field-tested | NO GO |
| CAT/PTT/physical receive | Separate authorization not obtained | NO GO |
| Release disposition | No deployment authorized or executed | **NO GO** |

## Change control

This packet changes documentation only. No services, deploy wrappers, Pi,
Forge, 192.168.9.0/24, 192.168.10.0/24, OPNsense, credentials or radio
configurations are modified. A future change affecting the listed network
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
