# Issue #410 — installed deployment wrapper review (2026-11-13)

## Evidence and scope

The operator supplied the contents of the root-owned `/usr/local/sbin/rolling-thunder-deploy` on anvilmobile. This is an **operator-provided snapshot**, not a hash-verified file capture. It was reviewed against the live `/etc/systemd/system/rolling-thunder.service` and repository `deploy/rolling-thunder-autostart`. At the time of this initial review, no deployment, restart, or radio action had been performed. A later, separately authorized parked deployment and stop/start test are recorded below.

## Confirmed behavior

The wrapper invokes **system-level** `systemctl stop/start/is-active rolling-thunder.service` (no `--user`). This reconciles the original false discrepancy in #410. It accepts only a lowercase exact 40-character commit, verifies clean checkout and remote branch containment, and checks out detached exact SHA. It stops the service, creates a SQLite online backup, refreshes the editable venv install, initializes/validates schema, starts the service, sleeps three seconds, checks `systemctl is-active`, and verifies the checkout SHA. The rollback routine preserves the current database, checks its schema against the backup, then attempts previous-code checkout and reinstall.

## Risks and testable corrections

1. **No transaction/deployment lock.** No `flock` or equivalent protects concurrent wrapper invocations. Independently, `deploy/rolling-thunder-autostart` uses two non-atomic `pgrep` checks. Require a single serialized deploy operation and a fail-closed dashboard singleton ownership mechanism.
2. **Health is only systemd activity after three seconds.** `systemctl is-active` does not prove UI responsiveness, device readiness, PTT safe state, or absence of a second process. The unit's minimum uptime wait is 180 seconds only when system uptime is under 180 seconds; an early boot deploy could report active while the launcher is still waiting. Test explicit MainPID/cgroup and application readiness, with a bounded wait that respects startup delay.
3. **No explicit bash strict mode or trap.** Most commands are checked manually, but not every command is checked. Failures in `chmod`, `chown`, intermediate readback, or `systemctl start` after backup failure can continue or exit without assured recovery. Validate every critical step and use bounded cleanup/rollback traps.
4. **Backup directory precondition not checked.** The supplied script constructs `/var/backups/rolling-thunder-deploy/rolling-thunder-<timestamp>-<sha>.db` but does not create or verify the directory. Inspect deployed directory existence, free space, permissions, backup retention, and integrity/foreign-key checks before any parked change.
5. **Rollback schema compatibility is intentionally strict.** It compares full `sqlite_master`, `schema_metadata`, and `user_version` between current DB and predeploy backup. After a legitimate migration, rollback may refuse previous code and leave service stopped, preserving new data. This is safer than destructive restore but must be documented as an explicit recovery gate and tested with migrations.
6. **Rollback may report success without readiness.** It calls `systemctl restart` and checks its exit code, but does not check sustained service state, exact restored SHA after restart, or actual dashboard readiness. Test and report degraded rollback explicitly.
7. **Stop/cleanup partially tested.** The system unit uses SIGTERM and a 20-second stop timeout. A subsequent parked, FT-891-powered-off stop/start completed in 1412.5 ms with zero reported shutdown errors, including FT8 transmit cleanup (1154.0 ms) and GPS polling (236.9 ms). This does not establish active CAT/PTT release behavior, forced-timeout safety, or intermittent contention resolution; further parked hardware acceptance remains required.
8. **Backups are created after stopping the dashboard.** This is a deliberate consistency tradeoff; backup duration extends service downtime. Do not change ordering without testing database consistency and WAL behavior.

## Subsequent parked deployment and restart evidence (2026-11-13)

- Desktop Commander connected as `geoff` and used a newly installed, narrowly scoped `/etc/sudoers.d/rolling-thunder-desktop-deploy` rule to invoke the **unchanged** root-owned exact-SHA deployment wrapper. Operator installation passed `visudo -c`. A malformed `NOT_A_SHA` invocation was rejected without cached sudo credentials; the intended exact-SHA command was permitted. This did not authorize arbitrary root commands.
- Deployment from `179c005f0f7f61df1004641db75897f42b3dd8ad` to merged `ba58b0b2a3b9b10b73dcdcb1ee046528f79b6d62` completed successfully at approximately 20:06:59 EST. The wrapper reported schema version 22, `integrity_check=ok`, `foreign_key_check=ok`, and system service `active`.
- Backup: `/var/backups/rolling-thunder-deploy/rolling-thunder-20261114T010636Z-179c005f0f7f61df1004641db75897f42b3dd8ad.db`. Backup creation and integrity check passed; restore was **not** exercised.
- A separately authorized parked stop/start at approximately 20:07 EST completed with `RT_RUNTIME_SHUTDOWN phase=end duration_ms=1412.5 errors=0`. FT8 transmit cleanup took 1154.0 ms; GPS polling cleanup took 236.9 ms. After restart, `rolling-thunder.service` was active with MainPID `60400`, `NRestarts=0`, and exactly one observed dashboard process; production checkout matched the target SHA.
- No `RT_PTT_RELEASE` event was observed in this FT-891-off test. Active CAT PTT release timing, dashboard UI responsiveness, restart under early boot, concurrent deployment exclusion, and schema-changing rollback are **not** verified by this acceptance.
- The permission and production deployment evidence, validation, rollback instructions and history are committed in private `spifford3472/ki5vnb-qth-infrastructure`, `docs/operations/rolling-thunder-desktop-deploy-access-2026-11-13.md` (merged PRs #29 and #30).

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

- 2026-11-13: Added observed exact-SHA deployment, backup/schema checks, narrowly scoped Desktop Commander privilege, parked 1.413-second stop/start and remaining unverified safety/readiness gates. No additional deployment or restart for this documentation update.
