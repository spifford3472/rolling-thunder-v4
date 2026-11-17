# STAB-06 — supervision and recovery verification

Status: **source / offline verification only**. No host changes or service
restarts are authorized by this document.

## Implemented supervision

The Pi dashboard is owned by **system-level**
`/etc/systemd/system/rolling-thunder.service`, not a user service.
The installed source launcher is `deploy/rolling-thunder-autostart` and
inherits an exclusive nonblocking `flock` through `exec`. A secondary
`pgrep` rejects an unmanaged dashboard, before and after the uptime wait.
The expected unit uses `Restart=on-failure`, `RestartSec=10`,
`TimeoutStopSec=20`, `KillSignal=SIGTERM`.

Source-level tests include:
- unexpired startup wait and satisfied minimum uptime;
- unmanaged process refuses false-success startup;
- exclusive lock refuses a second launcher;
- symlinked lock path fails closed;
- **STAB-06** long-lived fake UI holding the lock after `exec`, rejection of a
  concurrent second launcher, and successful launch after the first UI exits.

These tests use an isolated fake executable, fake pgrep and temp paths. They
**do not** prove installed unit, MainPID/cgroup, UI readiness, exact-SHA
runtime identity or deployed wrapper behavior.

## Outstanding host/recovery gates

- Read-only snapshot of installed unit and every drop-in; obtain authorized
  inspection of the previously unreadable protected FT8 drop-in. Compare
  installed launcher hash/config to current source and verify the only
  matching dashboard PID belongs to the **system** service cgroup.
- Read-only wrapper inspection and bounded recovery dry-run model before
  any actual parked release. The 2026-11-13 operator-supplied wrapper
  review reports no atomic deployment lock and a 3-second
  `systemctl is-active` check that does not prove UI readiness.
- Test concurrent exact-SHA deployments, crash restart, early-boot
  startup, malformed SHA, backup failure, schema-changing rollback,
  rollback refusal, stale cgroup/process, failed target readiness, and failed
  previous-code restore/install/readiness. The offline candidate now refuses
  to restart after failed old-code restoration and requires the same bounded
  dashboard-readiness check after rollback; it remains uninstalled.
  Do not install a second supervisor or modify production wrapper under
  the guise of a unit test.
- Resolve STAB-04/05 safety stop gates before assuming force-kill/restart
  makes radio release safe. Recovery must report **unknown RF/PTT state**
  if release was not independently established.
- A stopped/started service, exact checkout identity, verified health/UI,
  journaled shutdown markers, one MainPID/cgroup and independently
  validated backup/rollback are required in separately authorized parked
  acceptance.

## Source discrepancy

`issue-410-supervision-reconciliation.md` is historical and describes an
old two-pgrep-only launcher. Current source uses inherited `flock`.
`issue-410-wrapper-review-2026-11-13.md` notes the later evidence.
Reconcile this in DOC-02; preserve the original dated observation.

## Change history / rollback

2026-11-14: Added hardware-free inherited-flock lifetime regression and
current-versus-historical supervision evidence. No systemd, root-wrapper,
permissions, network, or infrastructure changes. Revert this tests/docs
commit to roll back.

## STAB-07 current-source status update (2026-11-14)

The operator-authorized private snapshot of the installed root wrapper is now
available with SHA256 `476ecdbdbcc70bcb1025ac1ce97bae1982b98d8842d5e333ea43632378512daf`;
its **installed original** still requires a separate privileged hash comparison.
STAB-06C–F provides offline candidate locking, journaling and inspected
reconciliation but nothing is installed. The STAB-07 integration rehearsal is
not a merge, deployment, or parked safety acceptance. See
`stab07-integration-and-parked-release-plan.md`.

## 2026-11-16 owner-run read-only production evidence

The owner ran a read-only inspection through interactive root authorization.
The installed wrapper's SHA-256 matched its operator-captured copy. The base
service unit and all four active drop-ins were hashed, and only systemd
directive names were reported; protected values were not disclosed. This
confirms the installed wrapper is still the captured version described above,
not the newer uninstalled candidate. No configuration, service, or database
state changed. Hash identity does not independently validate configuration
values, readiness, deployment safety, or physical PTT state.
