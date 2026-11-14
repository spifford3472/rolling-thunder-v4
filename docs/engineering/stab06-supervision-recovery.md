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
  rollback refusal, stale cgroup/process and failed readiness.
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
