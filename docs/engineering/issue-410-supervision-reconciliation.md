# Issue #410: dashboard service supervision reconciliation (read-only)

Date: 2026-11-13. Status: **status discrepancy explained; wrapper stop/start and duplicate safety not fully verified**. No production changes, restarts, or deployment were performed.

## Direct production observations

On `anvilmobile`, `ps -eo pid,ppid,user,stat,lstart,args` showed exactly one matching dashboard process, PID 1499, PPID 1, started 2026-11-13 03:38:33 EST. `/proc/1499/cgroup` reported `0::/system.slice/rolling-thunder.service`.

`systemctl show rolling-thunder.service -p LoadState -p FragmentPath -p ActiveState -p MainPID` returned:
- `LoadState=loaded`
- `FragmentPath=/etc/systemd/system/rolling-thunder.service`
- `ActiveState=active`
- `MainPID=1499`

The same query with `systemctl --user` returned `LoadState=not-found`, `ActiveState=inactive`, `MainPID=0`, and an empty fragment path. **These queries address different systemd managers.** The original Nov 11 user-manager check did not disprove the system-manager service reported by the deployment wrapper.

The system unit runs as `User=geoff`, starts `/usr/bin/bash /home/geoff/projects/rolling-thunder-v4/deploy/rolling-thunder-autostart`, and sets `Restart=on-failure`, `RestartSec=10`, `TimeoutStopSec=20`, and `KillSignal=SIGTERM`. It is enabled under `graphical.target.wants`. It sets a minimum system uptime of 180 seconds and X11 display environment. Active drop-ins include R1A timing and FT8 environment files. A protected `60-ft8-period.conf` drop-in was not readable by the restricted remote account and its contents were **not** inferred.

## Current-source supersession notice (2026-11-14)

The launcher interpretation below is a **dated 2026-11-13 snapshot** and is
not the current implementation. Current repository
`deploy/rolling-thunder-autostart` acquires a nonblocking inherited `flock`
before the uptime wait and rejects unmanaged processes with `pgrep` as a
secondary guard. See `system-architecture.md`,
`stab01-doc01-evidence-2026-11-13.md`, and STAB-06 tests for current
source-level evidence. This correction does not independently attest that
the installed launcher matches source or that the protected systemd drop-ins
were inspected. Keep the original incident text as historical evidence.

## Source-level lifecycle and duplicate risk

The repository's `deploy/rolling-thunder-autostart` checks for an existing process matching `[p]ython.*rolling_thunder\\.ui_main|[r]olling-thunder-ui` before and after the 180-second uptime wait. If found, it logs and exits successfully; otherwise it validates config/venv and uses `exec` to replace itself with `rolling-thunder-ui`. This provides a *best-effort* duplicate check, **not an atomic singleton lock**. Concurrent launches could both pass `pgrep`; a pre-existing unmanaged dashboard could make the service exit successfully, leaving systemd without ownership of that dashboard. In this observed instance, cgroup membership and MainPID prove ownership.

The deployed root-owned `/usr/local/sbin/rolling-thunder-deploy` exists but is not readable through the restricted remote session. Its exact stop/start commands, health criteria, rollback, and concurrency protections **remain unverified**. The repository's deployment workflow describes expected behavior, not proof of the installed wrapper's implementation. Do not infer that wrapper execution is safe from service state alone.

A SIGTERM and 20-second stop timeout are configured, but actual orderly cleanup of FT8 PTT, CAT, audio, serial, and GPS was not tested. Avoid stop/restart while radio operations are active.

## Minimal separately reviewable follow-ups

1. **Read-only privileged wrapper inspection:** authorized operator reviews the deployed wrapper content and installed drop-ins; compare against expected exact-SHA deployment behavior and verify that health checks use system-manager `systemctl`, not user-manager commands.
2. **Tests for service semantics:** mock system-level active/inactive/missing states, stale process, and service MainPID; prevent false positives from `pgrep` alone; ensure exact expected SHA is running.
3. **Atomic duplicate protection:** design one supervised instance with a single lock/owner, and fail clearly if another dashboard is active. Review as a separate code/host change, not part of documentation reconciliation.
4. **Parked lifecycle acceptance:** after separate approval, verify graceful SIGTERM and bounded PTT/audio/serial cleanup, unexpected crash restart, and rollback to a recorded exact SHA; no live RF test without explicit authorization.
5. **QTH infrastructure record:** before any actual host service/wrapper/sudoers change, commit configuration paths, integrations, jobs, validation, rollback and history to `spifford3472/ki5vnb-qth-infrastructure`.

## Read-only verification

```bash
systemctl show rolling-thunder.service -p LoadState -p FragmentPath -p ActiveState -p MainPID
systemctl --user show rolling-thunder.service -p LoadState -p FragmentPath -p ActiveState -p MainPID
systemctl cat rolling-thunder.service
ps -eo pid,ppid,user,stat,lstart,args | grep '[r]olling-thunder-ui'
cat /proc/$(systemctl show -p MainPID --value rolling-thunder.service)/cgroup
```

Do not use `systemctl restart`, `kill`, or deploy commands as diagnostic probes.

## Change history

- 2026-11-13: Read-only production systemd/cgroup reconciliation; identified service-manager mismatch and unverified wrapper/cleanup gates. No production modification.
