# Desktop Commander access and shutdown diagnosis (2026-11-13)

## Scope and current state

AnvilMobile runs Rolling Thunder as `rolling-thunder.service`. Production was deployed at exact SHA `179c005f0f7f61df1004641db75897f42b3dd8ad`; a parked, FT-891-off controlled stop/start succeeded. This document records operator-side access configuration and read-only investigation findings, not a code or production release change. Desktop Commander is the chosen remote access for Rolling Thunder; do not introduce SpiffBridge for this project.

## Desktop Commander configuration and privilege boundaries

- The `geoff` Desktop Commander device is a user systemd unit at `/home/geoff/.config/systemd/user/desktop-commander-remote.service` with `ExecStart` invoking the local desktop-commander agent in `remote` mode.
- Previously `NoNewPrivileges=yes` prevented sudo privilege escalation. Changed to `NoNewPrivileges=no`, then ran `systemctl --user daemon-reload` and restarted that user unit. Original unit backup: `/home/geoff/.config/systemd/user/desktop-commander-remote.service.pre-privilege-fix-20261113`.
- The Desktop Commander `blockedCommands` list was changed to remove only `sudo`; disk formatting, partitioning, firewall, account management, poweroff/reboot, and other preexisting blocked commands were retained. This setting is held in Desktop Commander configuration, not in the Rolling Thunder Git repository.
- `sudo -n -l` now succeeds from the `geoff` Desktop Commander session. Existing sudoers authorizes `(root) NOPASSWD: /usr/local/sbin/rolling-thunder-pi-service-control start` and `stop`; the root-owned helper only invokes `/usr/bin/systemctl start|stop rolling-thunder.service`. `sudo -n ... status` required a password, confirming that unlisted arguments are not passwordless. Note that the user also has conventional password-protected sudo privileges; `NoNewPrivileges=no` relaxes process hardening and must be treated as a security tradeoff, not a sandbox.
- A separate Desktop Commander device on AnvilMobile uses `rt-remote`, not `geoff`; do not conflate its permissions with the `geoff` device. No network/firewall configuration was changed.

## Validation and recovery

- Controlled stop: `sudo -n /usr/local/sbin/rolling-thunder-pi-service-control stop` exited 0 after approximately 3.71 seconds. `systemctl show` reported inactive, MainPID=0, Result=success.
- Controlled start: `sudo -n /usr/local/sbin/rolling-thunder-pi-service-control start` exited 0. `systemctl show` reported active/running, MainPID=56143, NRestarts=0, Result=success, exact SHA `179c005f0f7f61df1004641db75897f42b3dd8ad`. Only one dashboard process was observed.
- To roll back Desktop Commander permissions, restore the backed-up user unit, run `systemctl --user daemon-reload`, restart `desktop-commander-remote.service`, and restore `sudo` to its previous `blockedCommands` array. Restarting the agent disconnects its remote session temporarily. Do not change Linux sudoers as part of this rollback; none were modified.
- For Rolling Thunder recovery, use the existing exact-SHA deployment wrapper with its database backup and rollback safeguards; avoid killing the dashboard abruptly when orderly shutdown diagnostics are needed.

## Shutdown evidence and follow-up

At 19:22:53–19:22:57 EST, the outer `RT_SHUTDOWN` cleanup completed in 2808.2 ms with zero errors. `RT_RUNTIME_SHUTDOWN` totaled 2805.1 ms: FT8 transmit close 1817.1 ms, GPS polling stop 707.0 ms, FT8 receive stop 178.9 ms, location publishing 71.7 ms; remaining steps were small. No systemd timeout occurred in this test. This does **not** reproduce or explain the earlier intermittent 20-second timeout.

Read-only code review: `ApplicationRuntime.stop()` invokes `ft8_hardware_transmit.close()`, which calls `_ptt.close()`; investigate the concrete PTT adapter's CAT release/serial I/O and whether each wait has a deadline. `GPSPollingService.stop()` cancels a `ThreadScheduledPoll`, whose `cancel()` sets an event and joins for `interval_s + 1.0`; the bounded join can return while a callback is still executing. `FT8ReceiveService.stop()` also uses bounded thread joins (up to three seconds each). Review the concrete GPS refresh callback, serial read timeouts, and shutdown ordering before proposing changes. Keep PTT fail-safe behavior intact. Add targeted deterministic regression tests for stalled callbacks and blocked PTT release before any code change. Do not alter production until a separately reviewed PR passes Ruff, MyPy, pytest, and parked hardware acceptance.
