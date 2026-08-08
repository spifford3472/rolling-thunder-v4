# GPS-assisted Raspberry Pi clock synchronization

Checkpoint #159 uses the trusted GPS UTC observation from Checkpoint #158 as a bounded fallback and verification source for the `anvilmobile` Raspberry Pi system clock.

## Safety and privilege boundary

Rolling Thunder continues running as the normal `geoff` user. The dashboard process must never run as root merely to set system time.

The application policy is separated from operating-system authorization:

- `ClockSynchronizationService` decides when a trusted GPS UTC value may be compared with or applied to the Pi clock.
- `SystemClockSetter` is a narrow typed port for the privileged operating-system operation.
- `ChronyHelperClockSetter` invokes only `/usr/local/sbin/rolling-thunder-chrony-settime` through `sudo -n`.
- the helper accepts exactly one decimal UTC epoch and rejects timestamps outside 2020-2100.
- the helper temporarily enables chrony's manual-input mode, submits one UTC sample, and disables manual input on exit.
- failure to verify or set the clock is degraded clock-sync state only; it must not prevent startup or affect GPS, map, logging, controls, radio, or other runtime services.

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

## Installed `anvilmobile` time-service inspection

Inspection on 2026-08-08 established:

- local zone: `America/New_York`
- system clock reported synchronized
- NTP service reported active
- `systemd-timesyncd` is not installed
- `chrony.service` is enabled and active; `chronyd.service` is its active alias
- `org.freedesktop.timedate1` is present and reports NTP enabled/synchronized
- timedated set-time and set-NTP actions require administrator authentication through polkit
- `geoff` is in the normal `sudo` group but has no existing non-interactive passwordless sudo authorization
- there is no RTC reported by timedated

This makes chrony the installed normal time authority. GPS fallback should cooperate with chrony rather than disabling NTP or replacing chronyd as the clock controller.

## Accepted deployment path

The deployment uses a narrow root-owned helper instead of granting the application direct root or general chrony control.

Repository templates:

- `deploy/rolling-thunder-chrony-settime`
- `deploy/rolling-thunder-clock-sync.sudoers`

Install them with:

```bash
sudo install -o root -g root -m 0755 \
  deploy/rolling-thunder-chrony-settime \
  /usr/local/sbin/rolling-thunder-chrony-settime

sudo install -o root -g root -m 0440 \
  deploy/rolling-thunder-clock-sync.sudoers \
  /etc/sudoers.d/rolling-thunder-clock-sync

sudo visudo -cf /etc/sudoers.d/rolling-thunder-clock-sync
```

The sudoers rule authorizes `geoff` to run only the fixed helper as root without an interactive password. The helper itself must remain root-owned and non-writable by `geoff`.

The helper does not disable chrony or timedated. It performs this bounded sequence:

1. validate one decimal epoch argument and the 2020-2100 safety range;
2. enable chrony manual input with `chronyc manual on`;
3. submit one UTC sample with `chronyc settime`;
4. disable manual input on exit, including failure/termination cleanup.

## Helper acceptance before runtime wiring

Before Rolling Thunder is allowed to invoke the helper automatically, validate the installed files and a near-no-op clock sample:

```bash
command -v chronyc
ls -l \
  /usr/local/sbin/rolling-thunder-chrony-settime \
  /etc/sudoers.d/rolling-thunder-clock-sync
sudo -n -l

EPOCH="$(date -u +%s)"
sudo -n /usr/local/sbin/rolling-thunder-chrony-settime "$EPOCH"

chronyc tracking
timedatectl status
```

Do not deliberately skew the vehicle Pi clock for this acceptance test. The deterministic test suite covers the out-of-tolerance write path; installed acceptance verifies that the real helper can submit a valid sample without breaking chrony/NTP operation.

## Runtime wiring gate

The helper is installed and accepted before `ApplicationRuntime` automatically composes the GPS clock-sync service. This prevents a new privileged path from being activated before its root ownership, sudoers syntax, non-interactive authorization, and chrony behavior have been proven on `anvilmobile`.
