# MeshCore installed-service cutover plan

**Status: PLAN ONLY — no cutover authorized or performed.** PR #479 removed
MeshCore from the Rolling Thunder source while preserving Forge-backed OHGO.
The merge did not stop installed user services or remove their configuration,
credentials, SQLite databases, or queued observations. This plan treats their
retirement as a separate owner-approved operational change.

## Current verified boundary

The current source baseline is merged `main` at
`3328c27d5eb41e4417fe6305d1942002a3488106`. Source inventory and tests confirm
that Rolling Thunder no longer composes MeshCore serial, GPS snapshot, broker,
traffic, or database components; OHGO remains on the independent Forge spots
route and has no MeshCore/GPS dependency.

On 2026-11-17, a read-only inspection through the Unix account that owns the
user systemd manager found:

- `meshcore-collector.service` is enabled and active. Its effective
  configuration replaces the base command and enables the message broker.
- `meshcore-traffic-worker.service` is enabled but inactive.
- Both effective unit configurations permit systemd to send SIGKILL after
  their stop timeouts. The collector's effective stop timeout is 90 seconds;
  the inactive worker's is 20 seconds. The collector's installed SIGTERM
  handling and SQLite-close behavior have not been validated against the
  executable currently running on the host.
- The owner checkout is clean at an older source revision and still contains
  the legacy collector entrypoint. Its on-disk SIGTERM path sets a stop event,
  closes the local servers, joins service threads with finite waits, and then
  stops the serial reader and persistence worker. This is useful source
  evidence, but does not prove the Python bytes loaded by the long-running
  process or prove that all production operations will finish within those
  waits. The collector has `Restart=on-failure`; confirm a clean zero exit and
  no restart after any future approved stop.
- The MeshCore receiver USB identity recorded in historical acceptance is not
  present in current enumeration. The collector's service state therefore
  cannot be used as evidence of functional collection.
- The inspection did not read message payloads, change databases, or alter
  unit state. Earlier verified database integrity and queue counts are dated
  evidence only; recapture current counts during approved preflight.

An observation made under a different remote-tool Unix account showed these
user units as absent/inactive. This is a manager-ownership mismatch, not
evidence of a completed cutover. All future checks and actions must use the
actual service-owning user's systemd manager. Do not infer service absence from
`systemctl --user` run under another UID.

The cutover is currently **BLOCKED**: the collector is active despite the
receiver being absent, its loaded code identity is not established, and
systemd may send SIGKILL after 90 seconds. No stop request should be issued
until the installed code's bounded exit behavior is validated in a disposable
test and the approved stop procedure prevents accepting a forced kill. If
necessary, a temporary `SendSIGKILL=no` unit override with a reviewed bounded
stop policy must be staged under separate approval before the cutover.

The historical source tests cover fake-reader close, missing-device
degradation, and the local read-only API. They do not exercise the collector
entrypoint's full SIGTERM path under systemd, assert clean process exit, or
verify the combined databases after shutdown. That end-to-end stop test is a
required pre-cutover offline check against the exact retained legacy source;
it must use temporary databases and fake serial, with no live device or
network.

## Cutover objectives and preserved behavior

- Stop and disable only the identified MeshCore collector and traffic worker
  user units after separate explicit approval.
- Preserve all collector, broker, and traffic-ledger data, including SQLite
  WAL state, pending/quarantined messages, credentials, unit files, and logs.
- Keep the first cutover reversible. Do not uninstall packages, remove files,
  migrate schemas, delete credentials, purge queues, or replay messages.
- Leave Rolling Thunder, shared GPS, radio/CAT/PTT, QSO database, and Forge
  OHGO services untouched.
- Do not manipulate the USB receiver, initiate MeshCore protocol commands, or
  cause any radio/RF activity as part of deactivation.

## Required owner authorization

Before execution, obtain approval tied to a specific parked maintenance window
and exact host/service-owner identity. The approval must name both units,
authorize stop and disable, state the retention location/period for their
data and credentials, name the operator who can restore service, and confirm
that no MeshCore service is required by another local consumer. Approval for
source removal, a radio acceptance test, or a Rolling Thunder deployment does
not imply this cutover approval.

## Execution plan after approval

1. **Freeze the change scope.** Reconfirm current `main`, unit states, unit
   files, all effective drop-ins, process ownership, open device/socket
   handles, and enabled targets through the service-owning user manager.
   Record private paths and file hashes only in the owner's protected change
   record. Confirm the traffic worker is not running and no other unit or
   application consumes its sockets or databases.
2. **Take an initial consistent backup.** While services are active, use the
   SQLite backup API for each observation, broker/message, and traffic-ledger
   database. This captures each database consistently, including logical
   contents represented by WAL, but timestamps may differ across stores. Do
   not copy a live `.db` file by itself or checkpoint/truncate source WAL.
   Keep source databases and sidecars in place.
3. **Stop in dependency order.** Stop the traffic worker first and confirm
   it is inactive. Then stop the collector/broker service. If the collector
   does not exit cleanly within the effective systemd stop bound recorded at
   preflight, systemd may send SIGKILL under the currently installed policy.
   **Do not issue the collector stop until its exact installed SIGTERM and
   database-close behavior has been reviewed and a graceful-exit bound has
   been established.** If the installed behavior cannot be verified, the
   cutover is blocked pending a separately reviewed, owner-approved stop
   policy. Never accept a forced kill as successful shutdown. Do not remove
   runtime sockets or files to force success.
4. **Take and verify the frozen backup.** With all writers stopped, confirm no
   process has the MeshCore SQLite files open. Create a second SQLite
   backup-API snapshot for each store. Check `integrity_check`, foreign keys,
   schema version, row counts, queue/cursor counts, file ownership/modes, and
   the backup hash for each final snapshot. Checkpoint none of the source
   databases. Keep payloads out of the public change record. If a store is
   missing, locked, corrupt, or not represented by a verified final backup,
   do not disable units or remove any data.
5. **Disable autostart.** Only after clean stop and verified frozen backups,
   disable the traffic worker
   and collector. Do not mask units or remove unit files in this initial
   reversible cutover. Confirm both units are inactive and disabled using the
   owning user manager, no collector process/socket remains, and the USB
   receiver was not opened.
6. **Check preserved applications/data.** Recheck the three database backups
   and source file counts without reading message content. Confirm local
   Rolling Thunder starts/continues without MeshCore configuration and that
   the OHGO client remains bound to Forge. Do not restart the production
   dashboard unless separately approved.
7. **Close the change record.** Record exact previous/final unit states,
   service stop results, backup verification evidence, data retention owner,
   rollback instructions, and any failures. Keep private artifact paths and
   identifiers outside this public repository.

## Rollback and retention

The first cutover does not delete source data or units. If an owner-authorized
rollback is required, restore only the prior enabled state under the owning
user manager and only if the previous MeshCore executable, configuration,
credential, database, and receiver path are still compatible and available.
The receiver is currently absent, and the removed Rolling Thunder source does
not supply a collector replacement; do not restart into an uncontrolled retry
loop merely to prove rollback. If compatibility is uncertain, preserve the
disabled state and escalate for a separately reviewed restoration package.

Keep the verified snapshots, original unit and drop-in files, credentials,
and logs for the owner-approved retention period. Any later uninstall or data
deletion requires a distinct change record and explicit approval after the
retention decision. Do not expire or purge old queued records as a side effect
of this cutover.

## Acceptance criteria

Cutover is complete only when both units are inactive and disabled in the
correct user manager, the collector has no open USB/socket handles, each
database has a verified consistent backup, no data/credential/unit file was
deleted, Rolling Thunder's shared services remain untouched, and OHGO remains
independent. A mismatch, uncertain unit owner, failed backup, unexpected
consumer, forced kill, or missing evidence is **NO GO**.

No production service state, database, credential, USB device, network, CAT,
PTT, or RF state was changed for this plan.
