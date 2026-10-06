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

## Completed-result observability

The current policy status and the result of the most recently completed synchronization opportunity are separate concepts.

After a successful verification, the current status normally advances from `VERIFIED` to `WAITING_FOR_CADENCE` on the next poll because another attempt is not permitted for 12 hours. A one-poll `VERIFIED` state is too transient for a UI, diagnostic sampler, or acceptance script to observe reliably.

`ClockSyncState.last_result` therefore retains an immutable `ClockSyncResult` for the lifetime of the running service. It records the most recent completed opportunity as `VERIFIED`, `SYNCHRONIZED`, or `WINDOW_EXPIRED`, including the GPS UTC, measured offset, whether a clock write occurred, and any completion error. The current status can continue to describe cadence or shutdown while `last_result` remains available as durable in-memory evidence of what actually happened.

Starting a new `ClockSynchronizationService` lifecycle clears the previous in-memory result. No checkpoint-159 result is persisted across process restarts.

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

FT8 receive diagnostics follow the same authority order. They use a read-only
chrony tracking probe as the primary readiness signal and the already-published
trusted GPS UTC observation as fallback/independent verification. This adds no
clock-write path and does not alter the helper, sudoers, systemd, chrony, or NTP
configuration. A greater-than-one-second disagreement is reported as degraded
rather than selecting a source silently.

The installed privilege boundary is:

- root-owned `/usr/local/sbin/rolling-thunder-chrony-settime`, mode 0755
- root-owned `/etc/sudoers.d/rolling-thunder-clock-sync`, mode 0440
- passwordless sudo only for the fixed helper path
- the helper accepts exactly one decimal UTC epoch and bounds it to 2020-2100
- the helper temporarily enables chrony manual input, submits one manual time sample, disables manual input, returns configured sources online, and requests a short NTP burst so normal source selection can resume promptly when network time is available

Rolling Thunder itself does not receive shell, service-management, package-management, or arbitrary root authority.

## Runtime composition and enablement

`ApplicationRuntime` owns the clock-synchronization lifecycle alongside GPS polling.

The production path is intentionally disabled unless the process environment contains exactly:

```text
ROLLING_THUNDER_GPS_CLOCK_SYNC=1
```

This keeps deployment opt-in while the feature is accepted on the installed vehicle Pi. The runtime refuses to enable clock synchronization when the configured GPS adapter is in mock mode.

When enabled:

1. real GPS polling starts first
2. `ClockSynchronizationService` starts on its own `ThreadingPollScheduler`
3. the service consumes only the immutable latest GPS state already published by GPS polling
4. no helper call can occur until trusted GPS UTC has remained continuously available for approximately 60 seconds
5. normal in-tolerance operation performs verification only and makes no privileged call
6. an out-of-tolerance system clock reaches only the typed `ChronyHelperClockSetter`
7. shutdown stops clock synchronization before GPS polling is stopped

The scheduler is thread-backed, so helper invocation never runs in Tkinter callbacks or on the UI thread.

## Installed acceptance history

### Initial helper attempt

On 2026-08-08 at head `5523d4313798f2cb8d9ffd8e6af61df2861b3ba0`:

- helper and sudoers ownership/modes were correct
- `visudo -cf` passed
- malformed input was rejected
- a near-current manual time sample was accepted by chronyd
- immediately after that sample, chrony reported Stratum 0 / `Not synchronised`, while `timedatectl` reported `System clock synchronized: no`

That result **failed** the helper-health acceptance gate. Runtime wiring remained blocked.

Normal service was restored using `chronyc online`, `chronyc burst 2/4`, and `chronyc waitsync`. Recovery completed with an external `^*` source, Stratum 3, `Leap status: Normal`, `System clock synchronized: yes`, NTP active, and `chrony.service` active.

### Corrected helper acceptance

The helper was revised so cleanup also issues chrony `online` and `burst 2/4` after manual input.

Installed acceptance on 2026-08-08 at exact head `4cb321ae2ad4a61811e247735c62297293058866` passed:

- repository and installed helper SHA-256 hashes matched
- starting chrony state was healthy with an external `^*` source, Stratum 3, and `Leap status: Normal`
- malformed input was rejected
- a near-current UTC sample was accepted with helper return code 0
- the helper explicitly requested NTP source recovery
- the first `waitsync` observation briefly showed no selected source, as expected immediately after manual input
- the second observation reselected the external NTP source
- final state returned to external `^*` source selection, Stratum 3, `Leap status: Normal`, `System clock synchronized: yes`, NTP active, and `chrony.service` active

This passes the privileged-helper health gate and permits final runtime wiring and installed runtime acceptance.

### First runtime acceptance observation

Installed runtime acceptance on 2026-08-08 at head `b82f07a0d9c08a1c524fb085253bc4af54c4c3f5` established:

- focused clock-sync tests passed 26/26 on `anvilmobile`
- chrony was healthy before the runtime test: Stratum 3, `Leap status: Normal`, system clock synchronized, and NTP active
- the acceptance runtime composed successfully with real GPS and mock radio
- trusted GPS UTC became available normally
- no clock write was observed
- after the roughly 60-second trust gate, the sampled current status changed from `WARMING_UP` to `WAITING_FOR_CADENCE`
- chrony remained healthy after the run: Stratum 3, `Leap status: Normal`, system clock synchronized, NTP active, and `chrony.service` active

The acceptance script reported failure because it sampled every five seconds and required the transient current status to equal `VERIFIED`. Code inspection showed that `VERIFIED` was immediately followed by `WAITING_FOR_CADENCE` on the next one-second policy poll. Reaching cadence within a few seconds of warm-up cannot be caused by the ten-minute retry-window expiry; it indicates a completed verification or synchronization. Because no clock write occurred and the Pi was in tolerance, the completed action was verification.

This exposed an **observability defect**, not a clock-setting or cadence failure: the completed verification was not retained after the next policy poll. The service was revised to retain `ClockSyncState.last_result`, and final installed acceptance must observe that durable completed result instead of relying on a transient current status.

## Recovery procedure

If a future manual-helper test leaves chrony temporarily without a selected source, recover normal sampling without changing configuration:

```bash
sudo chronyc online
sudo chronyc burst 2/4
chronyc waitsync 30 0.5 0 1 || true
chronyc tracking
chronyc sources -v
timedatectl status
systemctl is-active chrony.service
```

## Final installed runtime acceptance

Before enabling the production runtime flag, confirm the branch passes CI on the final runtime-observability head.

Then run the isolated real-GPS/mock-radio acceptance and confirm:

1. runtime composition succeeds
2. GPS reaches trusted UTC normally
3. no helper invocation occurs during the first approximately 60 seconds
4. because the Pi is already NTP-synchronized within the two-second tolerance, `last_result.status` becomes `VERIFIED`
5. `last_result.clock_written` remains false
6. the current status may be `WAITING_FOR_CADENCE` after verification; that is expected
7. chrony remains on an external source with `Leap status: Normal`
8. `timedatectl` continues to report system clock synchronized and NTP active
9. stopping the runtime preserves the completed result for final observation and stops the clock-sync scheduler cleanly

Do not deliberately skew the installed Pi clock merely to force the write path; deterministic tests cover the out-of-tolerance setter path.
