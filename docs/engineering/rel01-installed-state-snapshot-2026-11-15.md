# REL-01 installed-state snapshot — 2026-11-15

**Result:** production readiness remains **NO GO**.
**Method:** read-only Desktop Commander observations on AnvilMobile and Forge,
plus the owner-provided privileged read-only terminal output from AnvilMobile
at approximately 10:00 EST. No process, service, radio, database, configuration,
unit, wrapper, or network was changed. SQLite checks used `mode=ro` and
`PRAGMA query_only=ON`; no database backup or copy was made. Host timestamps
below are America/New_York.

This record separates directly observed state from source/history and from
protected or otherwise inaccessible evidence. It is a snapshot, not continuous
health monitoring.

## AnvilMobile system and runtime

At 07:51:35 EST, AnvilMobile reported Raspberry Pi Linux `aarch64`, kernel
`6.18.34+rpt-rpi-v8`.

| Item | Direct observation | Limit / disposition |
| --- | --- | --- |
| systemd scope | System unit `rolling-thunder.service`: loaded, active/running, `MainPID=60400`, user `geoff`, cgroup `/system.slice/rolling-thunder.service`, fragment `/etc/systemd/system/rolling-thunder.service`. | This confirms the current manager/scope and unit state only; it does not prove UI or radio health. |
| Main process | PID 60400 runs `.venv/bin/python .../.venv/bin/rolling-thunder-ui`. Its start time is 2026-11-13 20:07:18 EST. Cgroup children include FT8 `arecord` PID 60424 and DMR SSH PID 60445. | Follow-up found the checkout at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`, clean and detached; package `rolling-thunder 4.4.1` is editable from this checkout. Current `main` `91315847e313d6b3f1e1eaad1f5a2b7dee7659e3` is 47 commits ahead. This identifies installed checkout/package provenance but does not attest which source bytes the already-running process loaded at startup. |
| unit policy | Base unit starts `/home/geoff/projects/rolling-thunder-v4/deploy/rolling-thunder-autostart`; `Restart=on-failure`, `RestartSec=10`, `TimeoutStopSec=20`, `KillSignal=SIGTERM`; `ROLLING_THUNDER_MIN_UPTIME_SECONDS=180`; working directory/app and venv paths point to the production checkout. | These values were visible in the installed base unit. Do not infer that the inaccessible protected drop-ins have no overrides. |
| installed drop-ins | The owner-provided `sudo systemctl cat` output confirms the base unit and all four installed drop-ins: `50`, `60`, `70`, and `r1a-timing.conf`. `60` points to `/etc/rolling-thunder/ft8-period.env`; `70` points to the optional `completed-qso-delivery.env`. `r1a` sets `RT_R1A_UI_TIMING=1`. | Drop-in paths/content are now verified; environment-file values were not printed or inspected. |
| external MeshCore process | PID 1078 is supervised by enabled, active user unit `meshcore-collector.service` under user systemd PID 1005; the broker drop-in is active. | Its configured by-path device does not currently exist, no serial device appears in its open descriptors, and its recent logs repeatedly report “MeshCore USB path is not present.” It remains outside the dashboard cgroup and continues its 5-second retry policy. The enabled traffic worker is currently inactive/dead. Leave both units and all databases untouched pending separately approved cutover. |
| deploy serialization | The dashboard launcher has its own user-runtime `flock`, held by PID 60400. The installed root-owned wrapper is mode 0750, SHA-256 `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`. | The inspected wrapper has no visible mutex/`flock`, transaction journal, or readiness heartbeat. It stops the system unit, backs up only the primary QSO DB to `/var/backups/rolling-thunder-deploy` using SQLite `Connection.backup`, validates backup integrity, checks out and installs the exact SHA, initializes/validates the DB, starts the unit, waits 3 seconds, and checks systemd active state and SHA. The target directory exists root:root mode 0700. Its inventory includes files;
the newest listed backup is timestamped 2026-11-14 01:06:36Z and remains
unvalidated. No deployment lock or recovery transaction is established. |
| config and application state | The active config is `config/rolling-thunder.yaml`; its relative database path resolves against the config directory. | The user-owned config and device selectors were read without printing secrets. Root-only `/etc/rolling-thunder` contents remain inaccessible. See the follow-up evidence below. |

The 07:51 `rt-remote` session could not read `/home/geoff`. A later
AnvilMobile session ran as `geoff` and inspected user-owned state. The
owner then supplied output from passworded, read-only `sudo` commands on
AnvilMobile, which exposed the installed system unit/drop-ins and privileged
wrapper source/hash. No mutating privileged command was run.

## Follow-up AnvilMobile evidence (08:49–09:03 EST)

The production checkout is detached at `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62`
(`v4.4.1-140-gba58b0b`), clean, and installed editable as `rolling-thunder`
4.4.1 from its local venv. Python is 3.13.5 on ARM64; `pip check` reported no
broken requirements. Current `main` is 47 commits ahead. The running
`rolling-thunder.service` is `Type=simple`, `NotifyAccess=none`, so systemd
`active` confirms a process, not application/UI readiness. No independent
startup-ready heartbeat was verified.

The launcher SHA-256 is
`eb6448589a13c4dae35fdd584be260b2535c1fe200fae5413bb943d76970437a`.
Its source requires `/usr/bin/flock`, guards the dashboard with a user runtime
lock and `pgrep` checks, enforces a 180-second minimum uptime, then execs the UI.
The lock file was held by PID 60400. This does not establish the privileged
deployment wrapper's lock or recovery behavior.

The active config maps radio CP2105 interface 0 to `ttyUSB1`, physical controls
CP2102 serial `0001` to `ttyUSB0`, and GPS CP2102N serial
`a67ea6d582f4ef11804abf1b6d9880ab` to `ttyUSB3`. All three device nodes were
open in PID 60400. FT8 audio is configured as `plughw:CARD=Device,DEV=0`; an
`arecord` child and matching USB capture device were present. Speech capture is
configured as `plughw:CARD=Array,DEV=0`, but the capture-device listing showed
only USB Audio Device `Device`; voice capture mapping remains unverified.
Enumeration/open descriptors do not prove GPS freshness, usable audio, FT8
decoding, or radio receive behavior.

The independent MeshCore user unit is enabled and active with `Restart=on-failure`
and a 5-second delay. Its configured `/dev/serial/by-path/...usb-0:1.1.1:1.0`
link is absent from the current serial inventory, and no serial descriptor is
open in PID 1078. Recent service messages repeatedly report that the receiver
path is absent. The enabled `meshcore-traffic-worker.service` is inactive/dead;
systemd recorded an ordering cycle involving that unit and `default.target` on
2026-07-23. Neither service was changed. Exact unit paths, queue counts and
database evidence are in the preservation section below.

## Privileged deployment-wrapper follow-up (approximately 10:00 EST)

The owner-provided terminal output came from `geoff@anvilmobile`, confirmed by
`hostname`. `systemctl cat rolling-thunder.service` showed the system unit
and all installed drop-ins. The active base unit is `Type=simple`,
`Restart=on-failure`, `RestartSec=10`, `TimeoutStopSec=20`, and
`KillSignal=SIGTERM`. It has `NotifyAccess=none`. The drop-ins reference
FT8 evidence, FT8 period, optional completed-QSO delivery environment files, and
set `RT_R1A_UI_TIMING=1`. Environment-file values were not displayed.

The installed `/usr/local/sbin/rolling-thunder-deploy` is root-owned mode
0750, 7,257 bytes, SHA-256
`476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`. The
inspected source requires one exact 40-character lowercase SHA, a clean
production worktree, and target containment on a pushed origin branch. It logs
the previous/target SHA, stops `rolling-thunder.service`, creates a SQLite
backup of only `config/data/rolling-thunder.db` with Python's
`Connection.backup` API, checks backup `integrity_check`, checks out
the target, refreshes the editable install, initializes/validates the database,
starts the service, waits three seconds, then verifies only systemd active state
and the final SHA.

No mutex/`flock`, transaction journal, or application-readiness heartbeat
appears in the inspected wrapper source; no separate outer lock was identified.
The source has a rollback function that preserves the live database and restores
the prior code only when its schema signature remains compatible, then restarts
the service. That path is not exercised or verified here. The service-active
check after three seconds does not prove Tk/UI readiness.

The wrapper target is `/var/backups/rolling-thunder-deploy`, a separate
root:root mode-0700 directory. The owner inventoried it and validated its
newest listed candidate read-only:
`rolling-thunder-20261114T010636Z-179c005f0f7f61df1004641db75897f42b3dd8ad.db`
(5,455,872 bytes; filename timestamp 2026-11-14 01:06:36Z). On 2026-11-15,
both live and backup databases reported schema 22, `integrity_check=ok`,
zero foreign-key violations, 355 contacts (340 synchronized, 15 failed),
15 retry rows, 693 synchronized FT8 outbox rows, and the same latest QSO
timestamp, `2026-11-13T09:38:52.594808Z`. All 355 contact IDs matched, with
zero IDs present only in either database. The backup therefore matches the
observed live QSO/contact state and passed these read-only checks. Per-retry
field values and FT8 outbox IDs/payloads were not compared, and optional
outbox/durable stores remain to be reconciled. The wrapper source is not
present at `deploy/rolling-thunder-deploy` on current GitHub `main`;
installed wrapper provenance is therefore not tied to a tracked, tested
repository source. No service, wrapper, or database was changed.

## Contact-sync retry follow-up (16:43 EST)

At 16:43:33 EST on 2026-11-15, a SQLite read-only inspection on AnvilMobile
still showed 355 contacts: 340 synchronized and 15 failed, with 15 retry rows.
Each retry's stored error remained the generic
`Home Station Platform contact upload returned HTTP 503.`; the persisted retry
counts had advanced to 858–2,262 and the next attempts were due at 16:48:22–26
EST. This confirms the normal retry loop is running, but none of these contacts
has recovered.

The Forge contact-sync unit remained active (MainPID 788703). A read-only
`GET http://192.168.9.170:8767/health` returned HTTP 200 with
`availability=available` at 16:43:31 EST. This verifies the health path's
Wavelog authentication and configured target resolution at that time; it does
not exercise the Wavelog QSO import POST.

Source inspection explains why the Pi's retry row lacks a more specific cause:
`http_home_platform.py` raises an error containing only the HTTP status for
non-2xx contact responses and discards the response body. Forge's `/contacts`
handler can return HTTP 503 for either `wavelog_unavailable` or
`sync_ledger_unavailable`. The currently available Pi-side error therefore
cannot distinguish a Wavelog QSO-write failure from a Forge ledger-storage
failure. Forge ledger state and Wavelog application logs around the 16:43 retry
must be inspected read-only before selecting a repair. No manual sync, state
reset, database write, service change, or contact replay was performed.


## Contact-sync routing follow-up (16:49 EST)

Forge's journal records 15 `POST /contacts` responses with HTTP 503 around
16:43 and again around 16:48, while periodic `GET /health` requests continue
returning HTTP 200. The Forge contact-sync ledger passed `integrity_check` and
contained 349 entries, all `synchronized/imported`, with no pending entries.

A grouped AnvilMobile query found all 15 failed contacts have NULL/absent
`my_grid`, `my_state`, `my_cq_zone`, and `my_itu_zone`. Source inspection
shows these route through `Mobile - Unknown Location`; target resolution,
including fallback station verification/creation/logbook linking, happens
before the ledger claim.

This narrows the likely fault to resolving or provisioning the
`Mobile - Unknown Location` Wavelog target (or writing its Forge station
binding), before contact upload is recorded in the ledger. It is not yet
proven: the failed UUIDs have not been correlated against the 349 ledger rows,
and the unknown-location binding/profile/logbook membership have not been
checked. Do not create or edit a profile until those read-only checks are done.

## USB and peripheral inventory

At 07:51 EST, `lsusb` showed VIA USB hubs, a SanDisk Extreme 55DD storage device,
two Silicon Labs CP210x UART bridge devices (`10c4:ea60`), one CP2105 dual UART
bridge (`10c4:ea70`), and one C-Media USB audio device (`0d8c:0012`). The
serial-by-id links were CP2102N serial `a67ea6d582f4ef11804abf1b6d9880ab`
to `ttyUSB3`, CP2102 serial `0001` to `ttyUSB0`, and CP2105 interfaces to
`ttyUSB1`/`ttyUSB2`. USB audio capture/playback nodes for the C-Media device
were present under `/dev/snd`.

These are bus-level observations. The later `geoff` session compared the
user-owned config with device serials and process descriptors (see follow-up
above). Radio, controller, and GPS mappings were identified, but enumeration
and open descriptors are not proof of stable operation, audio capture, fresh
GPS, FT8 receive, or USB hub health. The speech microphone mapping remains
unverified. No device was reconfigured.

## Forge service snapshot

At 08:04:12 EST, Forge's system manager listed these Rolling Thunder services
active: callsign-info, contact-sync, propagation QSO worker, propagation
collector, PSK evidence forwarder, PSK evidence listener, PSK Reporter worker,
and spots. The spots service had MainPID 2689642; the contact-sync service was
active with PID 788703. The PSK autoqueue timer's most recent invocation was
08:04:07 EST and its oneshot reported `Result=success`, exit status 0, and
inactive/dead after completion. Its next scheduled run was 08:05:07 EST.
FT8-readiness, NOAA-refresh, and VOACAP-baseline timers were also listed.

This updates the dated historical observation of a PSK autoqueue oneshot failure:
that old failure is not evidence of a current failure, and the successful
08:04 run is not proof that every queued event has been delivered. Local Pi
retry state was read and is detailed below. Remote contact-sync backlog, Forge
database content, service source identities, and the last-24-hour contact-sync
journal output remain unverified. Provider service presence is not end-to-end
API/Wavelog health.

## Durable data, schemas, backups, and rollback

The active Rolling Thunder database resolves to
`/home/geoff/projects/rolling-thunder-v4/config/data/rolling-thunder.db`.
At approximately 08:50 it was 5,545,984 bytes with a 4,157,112-byte WAL and a
32,768-byte SHM file. A SQLite read-only connection including the live WAL
reported application schema metadata version 22, **355 contacts** (340
synchronized, 15 failed), 693 synchronized FT8 performance-outbox records,
`PRAGMA integrity_check = ok`, and zero foreign-key violations. `PRAGMA
user_version` is 0; schema version is stored in `schema_metadata`.

All 15 failed contacts had HTTP 503 as their last error. Recorded retry counters
were 766–2,170; updates occurred around 08:58 EST and the next scheduled retries
were around 09:03 EST. The Forge contact-sync service was active (PID 788703),
but its last-24-hour journal query returned no entries; the cause of the 503s
and end-to-end delivery remain unresolved. The default resolved
`config/data/completed-qso-outbox.db` was absent. A protected optional
`/etc/rolling-thunder/completed-qso-delivery.env` is listed by systemd but was
not readable, so an alternate configured outbox cannot be ruled out.

The independent MeshCore observation DB reports schema 2, 568 observations,
236 nodes and 4,074 signal samples. Its broker DB contains 236 messages (228
public, 8 quarantined) and a public cursor at ID 199, leaving 34 public
messages beyond that cursor. The traffic ledger contains 194 records, all
marked `ignored`. Read-only integrity checks passed with zero foreign-key
violations for the Rolling Thunder DB and all three active MeshCore databases.
No database, WAL or SHM file was copied or altered.

The root-level inventory confirms multiple deployment backup files under
`/var/backups/rolling-thunder-deploy`. The newest listed file is
`/var/backups/rolling-thunder-deploy/rolling-thunder-20261114T010636Z-179c005f0f7f61df1004641db75897f42b3dd8ad.db`, 5,455,872 bytes; its embedded UTC timestamp is
2026-11-14 01:06:36Z. It predates the current dashboard process start on
2026-11-13 at 20:07 EST by about a minute. On 2026-11-15, read-only inspection
of both live and backup databases showed schema 22, `integrity_check=ok`,
zero foreign-key violations, 355 contacts (340 synchronized, 15 failed),
15 retry rows, 693 synchronized FT8 performance-outbox records, and the same
latest QSO timestamp (`2026-11-13T09:38:52.594808Z`). All 355 contact IDs
matched; no contact IDs were present only in either database. The file is
therefore a validated candidate backup of the observed QSO/contact state.
Per-retry field values and FT8 outbox IDs/payloads were not compared, and the
optional completed-QSO outbox path and other durable stores remain to be
reconciled. The earlier listing of `/var/backups/rolling-thunder` covered a
separate directory containing subsystem backups. The similarly named
repository-root `data/rolling-thunder.db` is dated 2026-09-27, and
`data/rolling-thunder.pre182-20260809T195346Z.db` is dated 2026-08-09;
neither is accepted as current. Historical MeshCore rollback DB files were not
validated as backups.

The installed wrapper uses SQLite's backup API after stopping the service and
checks only `PRAGMA integrity_check` on that backup. The script does not
verify backup foreign keys, row counts/identifiers, or a backup hash, and it
covers only the primary QSO DB path; the optional completed-QSO outbox path and
other durable stores remain to be reconciled. Any future approved backup must
also verify schema, `PRAGMA foreign_key_check`, QSO/contact/retry counts and
identifiers, and that the protected copy opens. Do not raw-copy a live WAL pair
or replace a database from Git. Preserve the live database and WAL; test schema
compatibility before any rollback.

The previous checkout SHA and editable package path are identified. The process's
loaded source bytes, native package provenance/hashes, environment-file values,
and per-retry field values plus FT8 outbox IDs/payloads in the newest deployment backup remain unverified. The
installed wrapper hash/source are known, but its missing mutex/journal and absence
from the repository leave deployment serialization and provenance unresolved.
Rollback readiness for the primary QSO database now has a validated candidate
snapshot matching the observed live contact set and aggregate sync state.
Full retry-row/outbox content comparison, optional durable stores, and a tested
code/schema rollback path are still outstanding.

## Focused safety and reliability matrix

| Gate | Evidence now | Remaining acceptance |
| --- | --- | --- |
| FT8 shutdown/PTT/recovery | Merged source and deterministic tests include command inhibition, shutdown ordering, bounded CAT work and operator recovery policy. Current installed code and physical radio are unverified. | Parked, separately approved operator-visible receive confirmation; actual red TX indication, de-key and receive behavior. Software `TX0`/poll status is not physical proof. |
| Supervision/duplicates | One dashboard MainPID is in `/system.slice/rolling-thunder.service`; the launcher lock is held. Collector is a separate enabled user unit, active but missing its configured USB path; traffic worker is enabled but inactive. | The installed deploy wrapper has no visible lock or transaction journal; no outer serialized mutex was identified. Separately approve and cut over both installed MeshCore units before installing a package without the collector entry point. |
| Startup/shutdown | Installed base unit has 20-second stop timeout, SIGTERM and restart-on-failure. Source concurrency tests pass on the reviewed baseline. | Protected drop-ins, actual launcher outcome/readiness, and parked bounded stop/start observation. Do not restart now. |
| Controller command and override | Source tests cover dispatch gates and owner recovery; no physical command action was made. | Actual controller serial mapping, command delivery, cancellation/override and restart behavior during parked acceptance. |
| USB/audio/GPS | Configured radio, controls and GPS serial ports are open as `ttyUSB1`, `ttyUSB0`, and `ttyUSB3`; FT8 capture process is present. Speech selects `CARD=Array`, absent from the current capture listing. | Parked receive-only validation, actual mapping/operation, speech microphone, hub/reSpeaker/DigiRig stability, GPS freshness and FT8 decode remain unverified. |
| QSO/contact sync | Main DB integrity and foreign keys pass. 355 contacts: 340 synced, 15 failed; all 15 report HTTP 503 with retry counters 766–2,170. Forge sync service is active; 693 FT8 performance records are synced. | Resolve 503 source and end-to-end delivery without deleting/retrying records; inspect protected outbox settings, verify a consistent backup and preserve all QSOs/retry state. |
| Installed source vs STAB-07 | Editable production checkout is clean at `ba58b0b2...`; current `main` `91315847...` is 47 commits ahead. Python 3.13.5 and `pip check` clean. | Attest loaded source bytes, native dependency provenance/hashes, protected drop-in and startup readiness; the installed code is not the current tested main candidate. |
| Native ARM64/provenance | Historical STAB-07K/L evidence leaves two Raspberry Pi-patched archives quarantined pending authenticated signed indexes. | Do not deploy if the candidate requires those untrusted artifacts; validate exact installed/runtime dependency identity first. |

## Exact-SHA deployment and rollback plan (not authorized or executed)

1. Reconfirm the vehicle is parked and owner/operator is present. Obtain a new,
   explicit approval for a named merged target SHA and the deployment/restart.
2. The base unit, drop-ins, wrapper SHA/source, target backup path, and current
   source/target SHA checks are now observed. Before mutation, verify the
   wrapper-target backup inventory and environment-dependent data paths. The
   inspected wrapper lacks a mutex, transaction journal, and independent app
   readiness check; require a reviewed, tested serialized transaction and
   readiness/recovery path before any deployment. Missing these means NO GO.
3. Create and validate protected, consistent online backups of contacts/QSOs,
   retry/outbox state, and any other durable database. Record schemas, integrity,
   foreign keys, row counts, identifiers, backup hashes and destinations.
4. If MeshCore removal is included in the source candidate, separately approve
   a parked stop/cutover through the verified `systemctl --user` supervisor.
   Identify the unavailable USB path and the inactive enabled traffic worker;
   confirm queue consumers and retention. Preserve all observation, message,
   and traffic SQLite data; uninstall no unit and delete no data without
   separate explicit authorization.
5. Do not invoke the currently installed wrapper for a release until its source
   is tracked/reviewed, one transaction mutex and recovery journal are tested,
   and readiness is independently established. Then invoke only the approved
   exact-SHA path and record prior/target SHA, package provenance, runtime
   executable, and transaction evidence. systemd `active` alone is
   insufficient.
6. Validate one dashboard PID/cgroup and fresh heartbeat, UI status/navigation,
   receive-only GPS/controller/audio/FT8 behavior, Forge endpoints, contact-sync
   backlog, and durable data before/after. Any PTT uncertainty is STOP.
7. Roll back application code only through the verified wrapper after schema and
   QSO preservation checks. Preserve newly completed QSOs and all retry/queue
   state. Refuse rollback that would discard data or bypass an indeterminate
   deployment journal.

## Recommendation and approvals

**Current recommendation: NO GO.** The production checkout and live databases
are identified and passed read-only integrity checks, and the newest deployment backup now passes read-only integrity/FK checks and
matches the live contact IDs and reported aggregate QSO state. Fifteen QSOs
still fail with HTTP 503 despite the normal retry loop; Forge health is green,
but the exact POST failure source is hidden by the Pi client's generic error. The deployed wrapper hash
and source are known, but it is untracked in the repository and contains no
visible mutex, transaction journal, or independent app-readiness check. Its
separate target-backup directory inventory and environment-dependent data paths
remain unresolved. Native provenance and physical acceptance are also
incomplete. The enabled MeshCore collector is retrying against a missing USB
path and its enabled traffic worker is inactive. MC-REMOVE does not stop or
uninstall either unit.

Next approval, when the evidence blockers are resolved: explicit owner approval
for one parked exact-SHA deployment/restart. Separate approval is still required
for stopping/removing the installed MeshCore service or deleting its history, and
for any powered-radio/CAT/PTT/RF procedure. None of those operations occurred in
this snapshot.
