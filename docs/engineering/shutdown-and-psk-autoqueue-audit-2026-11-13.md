# Shutdown/duplicate protection and Forge PSK autoqueue read-only audit — 2026-11-13

## AnvilMobile: observed state

`/etc/systemd/system/rolling-thunder.service` is a system-level `Type=simple` unit invoking `deploy/rolling-thunder-autostart`. The live unit has `KillMode=control-group`, `KillSignal=SIGTERM`, `TimeoutStopSec=20`, `Restart=on-failure`, and `MainPID=1499`. The only dashboard process returned by `pgrep` was PID 1499. An additional `50-ft8-evidence.conf` drop-in exists; the remote account could not read `60-ft8-period.conf`. No stop or restart was performed.

The launcher checks `pgrep -u ... -f '[p]ython.*rolling_thunder.ui_main|[r]olling-thunder-ui'` before and after the uptime wait and exits **zero** if a dashboard already exists. This guard is non-atomic and cannot prove systemd ownership. A separately started dashboard could cause the launcher to exit successfully without bringing that dashboard into the unit's control group. The current observed instance is supervised; this is a latent failure mode, not evidence of an active duplicate.

The systemd SIGTERM/control-group policy provides process cleanup but **does not demonstrate** FT8 PTT/MOX deassertion, CAT close, audio and serial release, or recovery from an unresponsive UI. No parked shutdown acceptance was performed.

### Required offline and parked checks

- Fake-process regression: existing unmanaged dashboard must not produce a false healthy managed instance.
- Simultaneous launcher invocations: prove a single atomic ownership lock; assert no duplicate process and deterministic loser behavior.
- Check dashboard MainPID and cgroup membership, not only `is-active`.
- Mocked SIGTERM/timeout cases: demonstrate cleanup ordering and reporting without real RF.
- Separately approved parked validation: no transmit, monitor FT8 PTT/CAT/audio/GPS state, graceful stop and bounded timeout; capture exact SHA, service state, hardware-safe state and rollback. Never run this while driving.

## Forge: PSK autoqueue failure

`rolling-thunder-forge-psk-autoqueue.timer` schedules a one-shot service approximately once per minute. The unit at `/etc/systemd/system/rolling-thunder-forge-psk-autoqueue.service` runs as `rolling-thunder-pskreporter` (uid/gid 981), with **no supplementary groups**, `ProtectSystem=strict`, and `ReadWritePaths=/var/lib/rolling-thunder-forge-pskreporter`. Its Python entrypoint `rolling_thunder.forge_psk_autoqueue` reads:
- `/var/lib/rolling-thunder/forge-contact-sync.db`
- `/var/lib/rolling-thunder/forge-contact-sync-contact-snapshots.db`
- `/var/lib/rolling-thunder-forge-pskreporter/orchestration.sqlite3`

The service was observed failed with `ExecMainStatus=1`. `/var/lib/rolling-thunder` has mode `0750`, owner/group `rollingthunder:rollingthunder` and an ACL indicator (`+`); the PSK service account is not in `rollingthunder`. A plain permission check by the restricted diagnostic account cannot traverse the directory. **An ACL may grant access to the service account**, so these observations establish a plausible permissions failure but not its root cause. The journal was inaccessible to the diagnostic account; no traceback was captured. The service's `ConditionPathExists` checks do not establish that its user can read the databases.

Source `src/rolling_thunder/forge_psk_autoqueue.py` attaches all three SQLite databases read-only, joins synchronized contacts with successful FT8 performance attempts and snapshots, and writes only to the PSK orchestration queue when `--enqueue` is supplied. A failed one-shot therefore may prevent new FT8 events entering the PSK queue; no evidence currently establishes lost QSO records or a failure of primary contact sync.

### Next evidence (read-only, approved access)

1. Obtain the latest `journalctl -u rolling-thunder-forge-psk-autoqueue.service -n 50 --no-pager` via an authorized privileged diagnostic route, with secrets redacted.
2. Inspect `getfacl -p /var/lib/rolling-thunder` and both source database files, and confirm effective access as the service account **without opening databases for writes**.
3. Verify schema/table availability and source release identity through read-only SQLite and exact-SHA checks, only after authorization.
4. Reproduce with copied SQLite databases and a disposable queue database under an unprivileged test identity; distinguish permission errors from schema mismatch, bad event validation, or source/queue version drift.
5. Propose the smallest reviewed change (specific ACL, dedicated read-only group, or feeder adapter fix). Do not broaden general remote permissions or run the queue job in production to diagnose.

## Change/rollback record

2026-11-13: Read-only service, process, source, and directory checks only. No systemd, ACL, database, deployment wrapper, USB, or radio changes. A future Forge permission/unit change requires separate owner approval, narrow regression tests, verified backup/rollback, and the mandatory private QTH infrastructure repository change history before completion.
