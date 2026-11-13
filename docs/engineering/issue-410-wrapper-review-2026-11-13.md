# Issue #410 — installed deployment wrapper review (2026-11-13)

## Evidence and scope

The operator supplied the contents of the root-owned `/usr/local/sbin/rolling-thunder-deploy` on anvilmobile. This is an **operator-provided snapshot**, not a hash-verified file capture. It was reviewed against the live `/etc/systemd/system/rolling-thunder.service` and repository `deploy/rolling-thunder-autostart`. No deployment, restart, or radio action was performed.

## Confirmed behavior

The wrapper invokes **system-level** `systemctl stop/start/is-active rolling-thunder.service` (no `--user`). This reconciles the original false discrepancy in #410. It accepts only a lowercase exact 40-character commit, verifies clean checkout and remote branch containment, and checks out detached exact SHA. It stops the service, creates a SQLite online backup, refreshes the editable venv install, initializes/validates schema, starts the service, sleeps three seconds, checks `systemctl is-active`, and verifies the checkout SHA. The rollback routine preserves the current database, checks its schema against the backup, then attempts previous-code checkout and reinstall.

## Risks and testable corrections

1. **No transaction/deployment lock.** No `flock` or equivalent protects concurrent wrapper invocations. Independently, `deploy/rolling-thunder-autostart` uses two non-atomic `pgrep` checks. Require a single serialized deploy operation and a fail-closed dashboard singleton ownership mechanism.
2. **Health is only systemd activity after three seconds.** `systemctl is-active` does not prove UI responsiveness, device readiness, PTT safe state, or absence of a second process. The unit's minimum uptime wait is 180 seconds only when system uptime is under 180 seconds; an early boot deploy could report active while the launcher is still waiting. Test explicit MainPID/cgroup and application readiness, with a bounded wait that respects startup delay.
3. **No explicit bash strict mode or trap.** Most commands are checked manually, but not every command is checked. Failures in `chmod`, `chown`, intermediate readback, or `systemctl start` after backup failure can continue or exit without assured recovery. Validate every critical step and use bounded cleanup/rollback traps.
4. **Backup directory precondition not checked.** The supplied script constructs `/var/backups/rolling-thunder-deploy/rolling-thunder-<timestamp>-<sha>.db` but does not create or verify the directory. Inspect deployed directory existence, free space, permissions, backup retention, and integrity/foreign-key checks before any parked change.
5. **Rollback schema compatibility is intentionally strict.** It compares full `sqlite_master`, `schema_metadata`, and `user_version` between current DB and predeploy backup. After a legitimate migration, rollback may refuse previous code and leave service stopped, preserving new data. This is safer than destructive restore but must be documented as an explicit recovery gate and tested with migrations.
6. **Rollback may report success without readiness.** It calls `systemctl restart` and checks its exit code, but does not check sustained service state, exact restored SHA after restart, or actual dashboard readiness. Test and report degraded rollback explicitly.
7. **Stop/cleanup not proven.** The system unit uses SIGTERM and 20-second stop timeout, but whether FT8 PTT, CAT, audio, serial and GPS release safely on timeout is not demonstrated. Parked hardware acceptance is required.
8. **Backups are created after stopping the dashboard.** This is a deliberate consistency tradeoff; backup duration extends service downtime. Do not change ordering without testing database consistency and WAL behavior.

## Acceptance matrix (offline first)

- Missing/malformed SHA, dirty checkout, missing DB, remote fetch failure: refuse without service stop.
- Concurrent deploy: second invocation refuses before changing checkout/service.
- Service active but dashboard missing, wrong cgroup, or multiple processes: refuse success.
- Early boot: readiness wait honors 180-second minimum uptime.
- Backup missing directory, write failure, integrity failure: no checkout; restore original service when safe and report failure.
- Failed checkout, editable install, migration, start or readiness: safe code rollback only if schema-compatible; preserve all newer durable data; report exact running SHA and service state.
- Schema-changing migration: no silent old-code restart; retain DB and explicit manual recovery instructions.
- SIGTERM and forced-timeout scenarios: RF/PTT off and resources released before any restart, verified parked with operator.
- Successful deployment: exact target SHA, one supervised dashboard, sustained UI readiness, service state and backup path recorded.

## Operational guidance

Do not replace or execute the root-owned wrapper during an active drive. Implement hardening as a separate reviewed branch with mocked shell/systemd/database tests and operator-approved parked deployment. Any actual host-wrapper/unit change requires the private QTH infrastructure change record (paths, integrations, jobs, validation, rollback, history) committed before completion.

## Change history

- 2026-11-13: Operator-provided wrapper contents reconciled with systemd manager and source launcher; no production changes.
