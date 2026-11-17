# MeshCore installed-service cutover plan

**Status: CUTOVER COMPLETED — 2026-11-17, owner authorized.** The two MeshCore
user services were stopped, disabled, and removed from the user systemd search
path. Their unit files were archived. SQLite-consistent backups were created
after shutdown and verified. Source databases, broker configuration, credentials,
and queued observations remain in place. This records service retirement only;
it does not approve a Rolling Thunder deployment.

## Current verified boundary

The current source baseline is merged `main` at
`a24d7d2a14cd1ea110696249e889a42fb0dc42c1`. Source inventory and tests confirm
that Rolling Thunder no longer composes MeshCore serial, GPS snapshot, broker,
traffic, or database components; OHGO remains on the independent Forge spots
route and has no MeshCore/GPS dependency.

On 2026-11-17, an authorized change was performed through the Unix account that
owns the user systemd manager:

- Before the change, `meshcore-collector.service` was enabled and active with
  the message broker enabled by a drop-in. The traffic worker was enabled but
  inactive. The receiver was physically removed, as confirmed by the owner.
- Both units were stopped; systemd reported a successful collector stop with
  exit status 0 and no restart. Both units were disabled. Their unit files and
  collector drop-in were copied to a protected owner archive, then removed from
  the user systemd configuration and reloaded. Both unit names now resolve as
  `not-found`; no MeshCore process or unit remains active/enabled in that user
  manager.
- The SQLite backup API created consistent copies of the observation, broker,
  and traffic-ledger databases after the writers stopped. All three copies
  passed `PRAGMA integrity_check` (`ok`) and had zero foreign-key violations.
  Table counts and SHA-256 hashes are recorded in a private manifest. Database
  payloads, private paths, and hashes are intentionally omitted here. Source
  databases and their data remain in place. Broker configuration and credentials
  were preserved. No messages or database rows were deleted.
- The Rolling Thunder system service remained active. No Rolling Thunder or OHGO
  service was stopped, restarted, or modified. No USB device was manipulated;
  the MeshCore receiver had already been physically removed by the owner.

The prior user-manager mismatch has been resolved by performing all service
checks through the correct owner manager. This cutover is reversible from the
protected unit archive if an owner later authorizes restoration and the physical
receiver and compatible runtime are available. No service has been restored.

The old collector's loaded Python identity was not established before the stop;
however, it exited with status zero under systemd and the post-stop backups
passed integrity checks. The stop result does not establish readiness of the
Rolling Thunder application or physical radio state.

## Completed change and preserved behavior

- Only the MeshCore collector and traffic-worker user units were stopped,
  disabled, archived, and removed from systemd's user-unit search path.
- Observation, broker/message, and traffic-ledger SQLite data were preserved
  both in place and as verified SQLite-backup-API copies, including logical
  state represented by WAL. The private manifest records hashes and row counts.
- Broker configuration and credentials remain in place. Unit files and the
  collector drop-in are retained in the protected owner archive. No packages,
  credentials, databases, queues, or source files were deleted.
- Rolling Thunder remains under its existing system service; its process was
  observed active after the cutover. OHGO was not modified.
- The receiver was physically removed by the owner before service retirement.
  No USB manipulation, MeshCore protocol command, CAT/PTT action, or RF activity
  occurred during this service cutover.

## Change verification

The user manager reports both MeshCore unit names as `not-found`, with no
MeshCore unit listed as enabled. The named processes were absent after stop.
All three archived SQLite copies passed integrity and foreign-key checks. The
Rolling Thunder system service remained active. The backup manifest and exact
archive paths are retained in the owner's private operational record, not in
this public repository.

## Rollback and retention

The cutover preserved source data and archived the removed unit definitions. If an
owner-authorized rollback is required, restore the archived unit files and prior
enabled state under the owning user manager only if the previous MeshCore
executable, configuration, credential, database, and receiver path are still
compatible and available.
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

Cutover acceptance: **PASS** for the authorized service-removal scope. Both
units are absent from the correct user manager, their definitions are archived,
all three databases have verified consistent backups, no database rows or
credentials were deleted, and the Rolling Thunder system service remained
active. OHGO was not modified. Restoration remains conditional on a compatible
receiver and runtime.

No Rolling Thunder deployment or restart, database mutation of source stores,
physical USB manipulation, CAT/PTT activity, or RF transmission occurred.
