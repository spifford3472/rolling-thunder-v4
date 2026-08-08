# GPS-assisted Raspberry Pi clock synchronization

Checkpoint #159 uses the trusted GPS UTC observation from Checkpoint #158 as a bounded fallback and verification source for the `anvilmobile` Raspberry Pi system clock.

## Safety and privilege boundary

Rolling Thunder must continue running as the normal `geoff` user. The dashboard process must never run as root merely to set system time.

The application policy is separated from operating-system authorization:

- `ClockSynchronizationService` decides when a trusted GPS UTC value may be compared with or applied to the Pi clock.
- `SystemClockSetter` is a narrow typed port for the privileged operating-system operation.
- The final concrete `anvilmobile` adapter and authorization mechanism must be selected only after inspecting the installed NTP/timedated/polkit configuration.
- Failure to verify or set the clock is degraded clock-sync state only; it must not prevent startup or affect GPS, map, logging, controls, radio, or other runtime services.

## Approved cadence

All cadence decisions use a monotonic clock and therefore do not change when the Pi wall clock is corrected.

1. After application startup, GPS UTC must remain continuously trusted for approximately 60 seconds before the first synchronization opportunity opens.
2. During an open opportunity, a failed attempt or unavailable/untrusted GPS UTC may be retried no more frequently than once every 60 seconds.
3. The retry opportunity is bounded to 10 minutes from its first attempt.
4. A successful verification or synchronization closes the opportunity and defers another opportunity for at least 12 hours.
5. If the 10-minute retry window expires without success, the opportunity closes and another opportunity is not opened until the same 12-hour cadence permits it.
6. A later opportunity still requires trusted GPS UTC; if trust was lost and recently recovered, the continuous-trust gate must be satisfied before action.

## Trust requirement

The synchronization service consumes only `GPSUTCObservation.trusted == True`. It does not independently weaken the GPS trust model.

A clock write is therefore impossible from GPS UTC that is stale, invalid, non-advancing, missing a valid fix, disconnected, or otherwise untrusted.

## Verification tolerance

The policy defaults to a two-second absolute tolerance.

If the current Pi UTC differs from trusted GPS UTC by no more than the tolerance, the opportunity is recorded as `VERIFIED` and no operating-system write is requested.

If the difference exceeds the tolerance, the service requests `SystemClockSetter.set_utc()` and records `SYNCHRONIZED` only when that call succeeds.

## Mandatory `anvilmobile` inspection before deployment

Before a concrete clock-setting adapter is selected or enabled on the vehicle Pi, capture all of the following from the installed system:

```bash
printf '===== DATE / CLOCK =====\n'
date --iso-8601=seconds
date -u --iso-8601=seconds

printf '\n===== TIMEDATECTL =====\n'
timedatectl status || true

printf '\n===== TIMESYNCD =====\n'
systemctl is-enabled systemd-timesyncd.service 2>&1 || true
systemctl is-active systemd-timesyncd.service 2>&1 || true
systemctl status systemd-timesyncd.service --no-pager -n 20 2>&1 || true

printf '\n===== OTHER TIME DAEMONS =====\n'
systemctl is-active chrony.service chronyd.service ntp.service ntpd.service 2>&1 || true
systemctl is-enabled chrony.service chronyd.service ntp.service ntpd.service 2>&1 || true

printf '\n===== TIMEDATED DBUS =====\n'
busctl introspect org.freedesktop.timedate1 /org/freedesktop/timedate1 org.freedesktop.timedate1 2>&1 || true

printf '\n===== POLKIT =====\n'
pkaction --action-id org.freedesktop.timedate1.set-time --verbose 2>&1 || true
pkaction --action-id org.freedesktop.timedate1.set-ntp --verbose 2>&1 || true

printf '\n===== USER / GROUPS =====\n'
id

printf '\n===== SUDO CLOCK COMMAND CHECK =====\n'
sudo -n -l 2>&1 || true
```

The inspection is read-only except for `sudo -n -l`, which only lists non-interactive sudo authorization and does not perform a privileged operation.

## Deployment decision

The concrete adapter is intentionally **not finalized yet**. The preferred mechanism will be whichever narrow path best cooperates with the actual installed time service while granting only the minimum additional authority required.

Candidates include systemd-timedated over D-Bus/polkit or a narrowly authorized root-owned helper. Rolling Thunder will not disable normal NTP or broadly grant root execution merely to implement GPS fallback time.
