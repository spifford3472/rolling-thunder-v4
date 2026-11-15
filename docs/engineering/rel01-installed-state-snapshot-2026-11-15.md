# REL-01 installed-state snapshot — 2026-11-15

**Result:** production readiness remains **NO GO**.
**Method:** read-only Desktop Commander shell observations on AnvilMobile and
Forge. No process, service, radio, database, configuration, unit, wrapper, or
network was changed. Host timestamps below are America/New_York.

This record separates directly observed state from source/history and from
protected or otherwise inaccessible evidence. It is a snapshot, not continuous
health monitoring.

## AnvilMobile system and runtime

At 07:51:35 EST, AnvilMobile reported Raspberry Pi Linux `aarch64`, kernel
`6.18.34+rpt-rpi-v8`.

| Item | Direct observation | Limit / disposition |
| --- | --- | --- |
| systemd scope | System unit `rolling-thunder.service`: loaded, active/running, `MainPID=60400`, user `geoff`, cgroup `/system.slice/rolling-thunder.service`, fragment `/etc/systemd/system/rolling-thunder.service`. | This confirms the current manager/scope and unit state only; it does not prove UI or radio health. |
| Main process | PID 60400 runs `.venv/bin/python .../.venv/bin/rolling-thunder-ui`. Its start time is 2026-11-13 20:07:18 EST. The only listed child was DMR SSH PID 60445. | Installed checkout, runtime source bytes, package version, commit SHA, fresh UI heartbeat, and Python dependency hashes could not be read. Repository `main` is at `91315847e313d6b3f1e1eaad1f5a2b7dee7659e3`; that does not attest the installed tree. |
| unit policy | Base unit starts `/home/geoff/projects/rolling-thunder-v4/deploy/rolling-thunder-autostart`; `Restart=on-failure`, `RestartSec=10`, `TimeoutStopSec=20`, `KillSignal=SIGTERM`; `ROLLING_THUNDER_MIN_UPTIME_SECONDS=180`; working directory/app and venv paths point to the production checkout. | These values were visible in the installed base unit. Do not infer that the inaccessible protected drop-ins have no overrides. |
| installed drop-ins | `systemctl show` listed `50-ft8-evidence.conf`, `60-ft8-period.conf`, `70-ft8-attempt-delivery.conf`, and `r1a-timing.conf`. | `systemctl cat` returned permission denied while reading protected drop-ins after partial output. Their complete contents, owner/mode, and hashes are unverified. |
| external MeshCore process | PID 1078, parent PID 1005, started 2026-11-13 03:38:23 EST; command is the production venv's `rolling-thunder-meshcore-collector`, with USB by-path, observation database, GPS snapshot, collector socket, broker enabled, broker config/database/socket arguments. It is outside the system dashboard cgroup. | Process presence/arguments are verified. Its supervisor/unit, protected config, queues/databases, owner, installed SHA, and current functional state are not verified. Leave it untouched pending separately approved cutover. |
| deploy serialization | Unit launcher path is visible. | Production checkout, launcher contents/hash, `/usr/local/sbin/rolling-thunder-deploy`, lock domain, recovery journal, SSH identity, and restricted sudo rules could not be read. No serialization or rollback claim is verified. |
| config and application state | Paths in the unit identify the production checkout, `/etc/rolling-thunder`, and runtime directory. | `/home/geoff` is mode `0700`; the Desktop Commander shell runs as `rt-remote` and cannot read it. Protected configuration values and live application state remain inaccessible. |

`systemctl cat` exposed the base unit and part of `50-ft8-evidence.conf`, then
reported permission denied for protected drop-in content. We did not use
privilege escalation.

## USB and peripheral inventory

At 07:51 EST, `lsusb` showed VIA USB hubs, a SanDisk Extreme 55DD storage device,
two Silicon Labs CP210x UART bridge devices (`10c4:ea60`), one CP2105 dual UART
bridge (`10c4:ea70`), and one C-Media USB audio device (`0d8c:0012`). The
serial-by-id links were CP2102N serial `a67ea6d582f4ef11804abf1b6d9880ab`
to `ttyUSB3`, CP2102 serial `0001` to `ttyUSB0`, and CP2105 interfaces to
`ttyUSB1`/`ttyUSB2`. USB audio capture/playback nodes for the C-Media device
were present under `/dev/snd`.

These are bus-level observations only. The radio, controller, GPS, DigiRig,
reSpeaker, and microphone role assignments could not be compared with the
protected installed config. Enumeration is not proof of stable operation, audio
capture, fresh GPS, FT8 receive, or USB hub health. No device was opened or
reconfigured.

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
retry state, remote contact-sync backlog, Forge database content, service source
identities, and logs were not read. Provider service presence is not end-to-end
API/Wavelog health.

## Durable data, schemas, backups, and rollback

No Rolling Thunder or MeshCore SQLite path, schema, row count, maximum QSO ID,
contact-sync retry state, WAL/SHM state, backup, or integrity result was read.
The production home-directory permissions blocked file inventory. No active-WAL
file was copied. The existing application's source-level schema expectations
and historical backup reports are not live database evidence.

A future authorized parked release must use the approved online SQLite backup
mechanism for each durable database, not a raw copy of a live database/WAL pair.
Verify backup schema, `PRAGMA integrity_check`, `PRAGMA foreign_key_check`,
QSO/contact/retry counts and identifiers, and verify the backup opens from its
protected destination. Keep the original database and WAL untouched through
validation. Determine schema compatibility before any rollback; never replace
a database with a repository copy or discard QSOs/queues to recover code.

The exact previous AnvilMobile source SHA, trusted native package set, rollback
wrapper, dependency compatibility, and verified backup are unknown. Therefore
rollback readiness is **not established**.

## Focused safety and reliability matrix

| Gate | Evidence now | Remaining acceptance |
| --- | --- | --- |
| FT8 shutdown/PTT/recovery | Merged source and deterministic tests include command inhibition, shutdown ordering, bounded CAT work and operator recovery policy. Current installed code and physical radio are unverified. | Parked, separately approved operator-visible receive confirmation; actual red TX indication, de-key and receive behavior. Software `TX0`/poll status is not physical proof. |
| Supervision/duplicates | One UI MainPID appears in system service cgroup; one separate MeshCore collector process is outside it. | Verify all UI/collector/worker supervisors, exact executable/source identity, singleton locks and recovery wrapper from protected paths. Collector must be cut over separately before a package no longer contains its entry point is installed. |
| Startup/shutdown | Installed base unit has 20-second stop timeout, SIGTERM and restart-on-failure. Source concurrency tests pass on the reviewed baseline. | Protected drop-ins, actual launcher outcome/readiness, and parked bounded stop/start observation. Do not restart now. |
| Controller command and override | Source tests cover dispatch gates and owner recovery; no physical command action was made. | Actual controller serial mapping, command delivery, cancellation/override and restart behavior during parked acceptance. |
| USB/audio/GPS | USB bridges and C-Media device are present; several serial paths enumerate. | Protected config-to-device mapping, hub/reSpeaker/DigiRig stability, captured audio, fresh GPS and receive-only FT8. Historical USB faults remain a caution, not proof of a current failure. |
| QSO/contact sync | Forge contact-sync and supporting services are active. PSK autoqueue's 08:04 oneshot succeeded. | Inspect local outbox/retry state and end-to-end Wavelog delivery without mutation; verify database/WAL backup and no lost QSO. |
| Installed source vs STAB-07 | `main` source baseline is `91315847...`; previous merged source tests and exact-head CI are recorded in GitHub. | Installed source SHA, runtime bytes, venv/dependency provenance, wheel hashes and readiness heartbeat are not available. |
| Native ARM64/provenance | Historical STAB-07K/L evidence leaves two Raspberry Pi-patched archives quarantined pending authenticated signed indexes. | Do not deploy if the candidate requires those untrusted artifacts; validate exact installed/runtime dependency identity first. |

## Exact-SHA deployment and rollback plan (not authorized or executed)

1. Reconfirm the vehicle is parked and owner/operator is present. Obtain a new,
   explicit approval for a named merged target SHA and the deployment/restart.
2. Before mutation, retrieve protected service/drop-in and wrapper evidence by
   the approved access path. Verify the wrapper's exact bytes, one serialized
   lock domain, journal/reconciliation behavior, current/target SHA handling,
   and rollback route. Missing evidence means NO GO.
3. Create and validate protected, consistent online backups of contacts/QSOs,
   retry/outbox state, and any other durable database. Record schemas, integrity,
   foreign keys, row counts, identifiers, backup hashes and destinations.
4. If MeshCore removal is included in the source candidate, separately approve
   a parked stop/cutover of PID 1078 using its actual supervisor. Confirm broker
   consumers and queue retention. Preserve all observation, message, and traffic
   SQLite data; uninstall no unit and delete no data without separate explicit
   authorization.
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

**Current recommendation: NO GO.** The live system manager and service process
were identified, but exact installed source, protected unit/config/wrapper,
durable databases/backup, device mappings, and physical acceptance remain
unverified. The separate MeshCore process observed on AnvilMobile adds an
independent cutover requirement; the MC-REMOVE source PR does not stop or uninstall
it.

Next approval, when the evidence blockers are resolved: explicit owner approval
for one parked exact-SHA deployment/restart. Separate approval is still required
for stopping/removing the installed MeshCore service or deleting its history, and
for any powered-radio/CAT/PTT/RF procedure. None of those operations occurred in
this snapshot.
