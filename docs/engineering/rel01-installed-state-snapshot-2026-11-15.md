# REL-01 installed-state snapshot — 2026-11-15

**Result:** production readiness remains **NO GO**.
**Method:** read-only Desktop Commander observations on AnvilMobile and Forge.
The 07:51 AnvilMobile session ran as `rt-remote`; a 08:49–09:03 follow-up ran
as `geoff` and could inspect user-owned checkout/configuration/data. Root-only
system files remained inaccessible without a passworded `sudo` command. No
process, service, radio, database, configuration, unit, wrapper, or network was
changed. SQLite checks used `mode=ro` and `PRAGMA query_only=ON`; no backup or
database copy was made. Host timestamps below are America/New_York.

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
| installed drop-ins | `systemctl show` listed `50-ft8-evidence.conf`, `60-ft8-period.conf`, `70-ft8-attempt-delivery.conf`, and `r1a-timing.conf`. | Follow-up read `50` (FT8 evidence environment file path), `70` (optional completed-QSO environment file path), and `r1a` (`RT_R1A_UI_TIMING=1`). `60-ft8-period.conf` is root-owned mode 0600 and unreadable. Secret environment values were not recorded. |
| external MeshCore process | PID 1078 is supervised by enabled, active user unit `meshcore-collector.service` under user systemd PID 1005; the broker drop-in is active. | Its configured by-path device does not currently exist, no serial device appears in its open descriptors, and its recent logs repeatedly report “MeshCore USB path is not present.” It remains outside the dashboard cgroup and continues its 5-second retry policy. The enabled traffic worker is currently inactive/dead. Leave both units and all databases untouched pending separately approved cutover. |
| deploy serialization | The user-owned launcher is readable and hashed. It takes an inherited `flock` at `/run/user/1000/rolling-thunder-ui-1000.lock`; `lslocks` showed PID 60400 holding that lock. | This verifies dashboard singleton protection only. `/usr/local/sbin/rolling-thunder-deploy` is root-owned mode 0750; `sudo -n` required a password, so wrapper bytes/hash, deployment lock, recovery journal, SSH identity, and rollback route remain unverified. No deployment serialization claim is established. |
| config and application state | The active config is `config/rolling-thunder.yaml`; its relative database path resolves against the config directory. | The user-owned config and device selectors were read without printing secrets. Root-only `/etc/rolling-thunder` contents remain inaccessible. See the follow-up evidence below. |

The 07:51 `rt-remote` session could not read `/home/geoff`. The later session
ran as `geoff`, which allowed the user-owned checks below. Read-only attempts to
inspect root-only files with `sudo -n` reported that a password is required;
no privileged command was run.

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

No current QSO backup was verified. A root-owned mode-0700
`/var/backups/rolling-thunder` directory exists but was unreadable. The
similarly named repository-root `data/rolling-thunder.db` is dated 2026-09-27,
and `data/rolling-thunder.pre182-20260809T195346Z.db` is dated 2026-08-09;
neither is accepted as a current backup. Historical MeshCore rollback DB files
exist but were not validated as backups.

A future authorized parked release must use the approved online SQLite backup
mechanism for each durable database, not a raw copy of a live database/WAL pair.
Verify backup schema, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`,
QSO/contact/retry counts and identifiers, and verify the backup opens from its
protected destination. Keep the original database and WAL untouched through
validation. Determine schema compatibility before any rollback; never replace
a database with a repository copy or discard QSOs/queues to recover code.

The previous checkout SHA and editable package path are now identified, but
the process's loaded source bytes, native package provenance/hashes, protected
drop-in `60`, privileged wrapper/hash and recovery journal remain unverified.
No verified current backup exists. Therefore rollback readiness is **not
established**.

## Focused safety and reliability matrix

| Gate | Evidence now | Remaining acceptance |
| --- | --- | --- |
| FT8 shutdown/PTT/recovery | Merged source and deterministic tests include command inhibition, shutdown ordering, bounded CAT work and operator recovery policy. Current installed code and physical radio are unverified. | Parked, separately approved operator-visible receive confirmation; actual red TX indication, de-key and receive behavior. Software `TX0`/poll status is not physical proof. |
| Supervision/duplicates | One dashboard MainPID is in `/system.slice/rolling-thunder.service`; launcher lock is held. Collector is a separate enabled user unit, active but missing its configured USB path; traffic worker is enabled but inactive. | Deployment wrapper lock and recovery are unverified. Separately approve and cut over both installed MeshCore units before installing a package without the collector entry point. |
| Startup/shutdown | Installed base unit has 20-second stop timeout, SIGTERM and restart-on-failure. Source concurrency tests pass on the reviewed baseline. | Protected drop-ins, actual launcher outcome/readiness, and parked bounded stop/start observation. Do not restart now. |
| Controller command and override | Source tests cover dispatch gates and owner recovery; no physical command action was made. | Actual controller serial mapping, command delivery, cancellation/override and restart behavior during parked acceptance. |
| USB/audio/GPS | Configured radio, controls and GPS serial ports are open as `ttyUSB1`, `ttyUSB0`, and `ttyUSB3`; FT8 capture process is present. Speech selects `CARD=Array`, absent from the current capture listing. | Parked receive-only validation, actual mapping/operation, speech microphone, hub/reSpeaker/DigiRig stability, GPS freshness and FT8 decode remain unverified. |
| QSO/contact sync | Main DB integrity and foreign keys pass. 355 contacts: 340 synced, 15 failed; all 15 report HTTP 503 with retry counters 766–2,170. Forge sync service is active; 693 FT8 performance records are synced. | Resolve 503 source and end-to-end delivery without deleting/retrying records; inspect protected outbox settings, verify a consistent backup and preserve all QSOs/retry state. |
| Installed source vs STAB-07 | Editable production checkout is clean at `ba58b0b2...`; current `main` `91315847...` is 47 commits ahead. Python 3.13.5 and `pip check` clean. | Attest loaded source bytes, native dependency provenance/hashes, protected drop-in and startup readiness; the installed code is not the current tested main candidate. |
| Native ARM64/provenance | Historical STAB-07K/L evidence leaves two Raspberry Pi-patched archives quarantined pending authenticated signed indexes. | Do not deploy if the candidate requires those untrusted artifacts; validate exact installed/runtime dependency identity first. |

## Exact-SHA deployment and rollback plan (not authorized or executed)

1. Reconfirm the vehicle is parked and owner/operator is present. Obtain a new,
   explicit approval for a named merged target SHA and the deployment/restart.
2. Before mutation, retrieve protected `60-ft8-period.conf`, environment,
   backup inventory and wrapper evidence by an approved read-only/root path.
   Verify wrapper bytes, one serialized lock domain, journal/reconciliation,
   current/target SHA handling and rollback route. Missing evidence means NO GO.
3. Create and validate protected, consistent online backups of contacts/QSOs,
   retry/outbox state, and any other durable database. Record schemas, integrity,
   foreign keys, row counts, identifiers, backup hashes and destinations.
4. If MeshCore removal is included in the source candidate, separately approve
   a parked stop/cutover through the verified `systemctl --user` supervisor.
   Identify the unavailable USB path and the inactive enabled traffic worker;
   confirm queue consumers and retention. Preserve all observation, message,
   and traffic SQLite data; uninstall no unit and delete no data without
   separate explicit authorization.
5. Invoke only the approved serialized exact-SHA wrapper. Record transaction
   receipt, previous and target SHAs, package provenance, and runtime executable.
   A successful checkout/systemd `active` state is insufficient.
6. Validate one dashboard PID/cgroup and fresh heartbeat, UI status/navigation,
   receive-only GPS/controller/audio/FT8 behavior, Forge endpoints, contact-sync
   backlog, and durable data before/after. Any PTT uncertainty is STOP.
7. Roll back application code only through the verified wrapper after schema and
   QSO preservation checks. Preserve newly completed QSOs and all retry/queue
   state. Refuse rollback that would discard data or bypass an indeterminate
   deployment journal.

## Recommendation and approvals

**Current recommendation: NO GO.** The production checkout and live databases
are now identified and passed read-only integrity checks, but there is no
verified current backup; 15 QSOs have HTTP 503 sync failures; protected
drop-in/wrapper/recovery evidence and native provenance remain incomplete; and
physical acceptance is unperformed. The enabled MeshCore collector is retrying
against a missing USB path and its enabled traffic worker is inactive. MC-REMOVE
does not stop or uninstall either unit.

Next approval, when the evidence blockers are resolved: explicit owner approval
for one parked exact-SHA deployment/restart. Separate approval is still required
for stopping/removing the installed MeshCore service or deleting its history, and
for any powered-radio/CAT/PTT/RF procedure. None of those operations occurred in
this snapshot.
