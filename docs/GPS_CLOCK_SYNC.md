# GPS-assisted Raspberry Pi clock synchronization

Checkpoint #159 uses the trusted GPS UTC observation from Checkpoint #158 as a bounded fallback and verification source for the `anvilmobile` Raspberry Pi system clock.

## Safety and privilege boundary

Rolling Thunder must continue running as the normal `geoff` user. The dashboard process must never run as root merely to set system time.

The application policy is separated from operating-system authorization:

- `ClockSynchronizationService` decides when a trusted GPS UTC value may be compared with or applied to the Pi clock.
- `SystemClockSetter` is a narrow typed port for the privileged operating-system operation.
- `ChronyHelperClockSetter` may invoke only `/usr/local/sbin/rolling-thunder-chrony-settime` through non-interactive sudo.
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

## `anvilmobile` deployment decision

Inspection on 2026-08-08 established:

- timezone `America/New_York`
- NTP active and initially synchronized
- `systemd-timesyncd` absent
- `chrony.service` enabled and active; `chronyd.service` is an active alias
- systemd-timedated D-Bus present
- set-time and set-NTP polkit actions require administrator authentication
- `geoff` has normal password-protected sudo but no general passwordless sudo
- no RTC is reported

The deployment therefore preserves chrony as the normal network time authority. GPS is only a bounded verification/fallback source.

The installed privilege boundary is:

- root-owned `/usr/local/sbin/rolling-thunder-chrony-settime`, mode 0755
- root-owned `/etc/sudoers.d/rolling-thunder-clock-sync`, mode 0440
- passwordless sudo only for the fixed helper path
- the helper accepts exactly one decimal UTC epoch and bounds it to 2020-2100
- the helper temporarily enables chrony manual input, submits one manual time sample, disables manual input, returns configured sources online, and requests a short NTP burst so normal source selection can resume promptly when network time is available

Rolling Thunder itself does not receive shell, service-management, package-management, or arbitrary root authority.

## Installed acceptance history

On 2026-08-08 at head `5523d4313798f2cb8d9ffd8e6af61df2861b3ba0`:

- helper and sudoers ownership/modes were correct
- `visudo -cf` passed
- malformed input was rejected
- a near-current manual time sample was accepted by chronyd
- immediately after that sample, chrony reported Stratum 0 / `Not synchronised`, while `timedatectl` reported `System clock synchronized: no`

That result failed the helper-health acceptance gate. Runtime wiring remained blocked.

The helper was revised so its cleanup also issues chrony `online` and `burst 2/4` requests after manual input. The revised helper must pass installed acceptance showing normal NTP source selection returns promptly before runtime wiring is allowed.

## Installed acceptance procedure

1. Confirm the Pi is already synchronized before testing.
2. Validate malformed input rejection.
3. Submit only a near-current UTC sample; do not deliberately skew the Pi clock.
4. Confirm the helper exits successfully.
5. Confirm chrony returns to a selected external source and `Leap status: Normal`.
6. Confirm `timedatectl` reports NTP active and system clock synchronized.
7. Confirm `chrony.service` remains active.

Only after those gates pass may the clock synchronization service be wired into `ApplicationRuntime`.
