# Production configuration audit — 2026-11-13

This is a **read-only partial inventory**, not a certification of all services or installed versions. Source of truth: live `systemctl` and process inspection on `anvilmobile` and Forge. Do not copy this inventory into a deployment script or treat it as permission to restart services.

## anvilmobile

- `rolling-thunder.service`: system-manager service, `/etc/systemd/system/rolling-thunder.service`, active; dashboard PID 1499 at 15:xx EST, `NRestarts=0`, `/system.slice/rolling-thunder.service`. Its unit runs `deploy/rolling-thunder-autostart` as geoff with 180-second boot wait, `Restart=on-failure`, 10-second restart delay and 20-second SIGTERM stop timeout.
- `rt-usb-observer.service`: **user-manager** service, `/home/geoff/.config/systemd/user/rt-usb-observer.service`; temporary independent read-only diagnostic script at `/home/geoff/.local/bin/rt-usb-observer.py`; JSONL at `/home/geoff/.local/state/rolling-thunder-diagnostics/usb-events.jsonl`. Not managed by the exact-SHA dashboard deployment.
- `r02-pi-snapshot.service`, `r02-pi-deliver.service`: present, inactive oneshot jobs at inspection; inspect associated timers before asserting health.
- `rt-gps-uncertainty-20261105.service`: historical one-time GPS uncertainty capture, inactive.
- `chrony.service`: active.
- `/usr/local/sbin/rolling-thunder-deploy`: root-owned mode 0750, inaccessible to the restricted remote account; **implementation not inspected**. See `issue-410-supervision-reconciliation.md`.

## Forge

Observed active system services:
- `rolling-thunder-forge-callsign-info.service`
- `rolling-thunder-forge-contact-sync.service`
- `rolling-thunder-forge-propagation-qso-worker.service`
- `rolling-thunder-forge-propagation.service`
- `rolling-thunder-forge-psk-evidence-forward.service`
- `rolling-thunder-forge-psk-evidence.service`
- `rolling-thunder-forge-pskreporter.service`
- `rolling-thunder-forge-spots.service`

Observed inactive oneshot jobs:
- `rolling-thunder-forge-ft8-readiness.service`
- `rolling-thunder-forge-noaa-refresh.service`
- `rolling-thunder-forge-voacap-baseline.service`
- `rolling-thunder-r02-forge-backup.service`
- `r02-forge-forward.service`

**Actionable discrepancy requiring separate investigation:** `rolling-thunder-forge-psk-autoqueue.service` was `failed` with `Result=exit-code`, `ExecMainStatus=1`. Its minute-scale `rolling-thunder-forge-psk-autoqueue.timer` was scheduled and running. The oneshot unit is at `/etc/systemd/system/rolling-thunder-forge-psk-autoqueue.service`; it runs `python -m rolling_thunder.forge_psk_autoqueue` under `rolling-thunder-pskreporter` with `--enqueue`, reading two contact-sync databases and writing the PSK orchestration database. The restricted journal query returned no entries; **failure cause unknown**. No service restart, timer change, database write, or queue processing was performed. This may affect the FT8-to-PSK queue; do not assert impact until logs and queue state are examined.

Observed timers include:
- `rolling-thunder-forge-psk-autoqueue.timer`
- `rolling-thunder-forge-ft8-readiness.timer`
- `rolling-thunder-forge-noaa-refresh.timer`
- `rolling-thunder-forge-voacap-baseline.timer`
- `rolling-thunder-r02-forge-backup.timer`
- `r02-forge-forward.timer`

An inactive oneshot service between timer firings is not evidence of an outage.

## Documentation reconciliation priorities

1. Verify exact installed wrapper contents using approved privileged read-only access; compare service manager, stop/start, rollback, and health semantics.
2. Compare the current engineering service inventory and operator guide with these observed service/timer names and actual source/configuration.
3. Examine PSK autoqueue failure and document verified impact and safe recovery separately.
4. Add the temporary USB observer to the repository with offline tests and an approved, separately deployed install/rollback path.
5. Update `source-file-index.md`, service ownership/consumer contracts, and operator guide only where the audited behavior requires it.
6. For any **future** actual QTH host/infrastructure modification, commit the corresponding change record to `spifford3472/ki5vnb-qth-infrastructure` before declaring completion.

## Read-only validation

```bash
systemctl list-units --type=service --all --no-pager | grep -Ei 'rolling|r02'
systemctl list-timers --all --no-pager | grep -Ei 'rolling|r02'
systemctl show rolling-thunder.service -p MainPID -p ActiveState -p NRestarts -p FragmentPath
systemctl show rolling-thunder-forge-psk-autoqueue.service -p ActiveState -p Result -p ExecMainStatus -p FragmentPath
systemctl cat rolling-thunder-forge-psk-autoqueue.service
```

## Rollback and history

2026-11-13: Inventory documentation only; no system configuration, integrations, jobs, service states, or data changed. Rollback of this document is a Git revert. Any future diagnostic installer must provide its own explicit rollback and preserve evidence.
