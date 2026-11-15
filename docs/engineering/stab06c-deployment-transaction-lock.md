# STAB-06C — deployment transaction lock (candidate, not installed)

Status: **offline implementation and tests only**, dated 2026-11-14 UTC.

## Scope and source of truth

`deploy/rolling-thunder-deploy-lock` is a small, testable guard for a *single
complete deployment command*. It opens an exclusive, nonblocking `flock` on file
descriptor 9 and `exec`s the command so the lock is inherited for the entire
transaction. A simultaneous invocation returns 75 before executing its command.
Command failure is propagated. Symlink and missing-parent checks refuse ordinary
unsafe lock paths.

This helper **is not part of production deployment yet**. The installed
`/usr/local/sbin/rolling-thunder-deploy` is root-owned and absent from the Git
repository. The prior 2026-11-13 operator-supplied snapshot is documentary
evidence, not a verified complete script suitable for replacement.

## Safety and integration gates

- The privileged integration must acquire **one transaction lock before fetch,
  checkout, backups, service stop, migration or any other mutable operation**.
  The lock must remain held through post-start verification and rollback.
- Use a fixed lock path under an existing root-owned, non-world-writable
  directory, with secure ownership/mode verified before installation; a
  pre-check for symlinks alone does not prevent TOCTOU races in untrusted
  directories. The helper is not a substitute for privileged path validation.
- All authorized deployment entry points must use the same transaction guard;
  never create a second deployment service or bypass existing exact-SHA controls.
- Do **not** wrap only the service-stop step or a child that exits before the
  full transaction has committed or rolled back.
- `systemctl is-active` is *not* application readiness. A separately reviewed
  bounded readiness probe must check exact SHA, one expected service-owned PID,
  correct cgroup and a genuine dashboard-responsive signal. If no safe signal
  exists, fail closed rather than mark release successful.
- Preserve SQLite contents, backups, schema compatibility and QSO history;
  blocked or failed rollback must remain an explicit failed state.
- Forced-stop or crash recovery must report unknown physical CAT/PTT state;
  software TX0 success is not independent radio receive-state verification.

## Acceptance and rollback

`tests/test_deployment_transaction_lock.py` covers lock inheritance through
`exec`, rejection of an overlapping transaction before its mutation marker,
lock release on completion, symlink/missing-parent refusal, and exit-code
propagation. No service, database or RF operations are exercised.

Parked installation requires separate owner approval, review of installed
wrapper and protected service configuration, isolated failure-injection for
backup/migration/start/rollback, and a committed QTH infrastructure change
record describing installed paths, validation and rollback. Revert the source
commit to remove this candidate; there is no production installation to undo.

## Change history

- 2026-11-14: Added uninstalled, hardware-free deployment transaction guard and
  lock-lifetime regressions. No installed wrapper, supervisor or permissions changed.
