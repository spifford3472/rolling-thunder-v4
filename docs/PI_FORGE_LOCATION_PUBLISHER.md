# Pi to Forge GPS Location Publisher

## Purpose

Checkpoint #161 adds the Raspberry Pi side of the retained mobile-location path introduced in checkpoint #160. `anvilmobile` publishes its latest useful GPS fix to the existing private Forge endpoint:

```text
PUT http://192.168.9.170:8766/api/v1/mobile-location
```

The publisher is part of the existing dashboard runtime. It does not create another daemon, listener, database, weather provider, radio-control path, or Tkinter callback that performs network I/O.

## Source of truth

The publisher consumes only the immutable state already produced by `GPSPollingService`; it never reads the serial GPS device itself.

A candidate publication requires all of the following:

- GPS connection state is `connected`
- position fix is 2D or 3D, not `no_fix`
- latitude and longitude are present
- the typed RMC UTC observation is valid, fix-valid, advancing, and fresh
- the RMC UTC observation has a monotonic receipt timestamp
- current monotonic sample age is no more than 5 seconds
- GPS UTC is not later than the Pi UTC clock
- GPS UTC is no more than 30 seconds older than the Pi UTC clock
- speed, when present, is no more than the Forge bound of 100 m/s

The request uses:

- `latitude` / `longitude` from typed `GPSPosition`
- optional `speed_m_s` / `heading_degrees` from typed `GPSPosition`
- `fix_at` from the trusted typed RMC UTC observation
- `received_at` from the Pi's aware UTC clock immediately before publication

This deliberately reuses the typed GPS/UTC trust model from checkpoints #158 and #159 rather than reparsing NMEA or reconstructing time in the publisher.

## Background execution

The scheduler callback performs no HTTP work. It only queues a single-worker executor job when publication is due.

Publication owns a separate one-worker executor from Forge shared-spot polling, so a slow location request cannot block `/api/v1/spots` refreshes.

A pending or executing location request suppresses additional queued requests. The HTTP timeout comes from the existing `forge.request_timeout_s` configuration.

Default cadence is:

- first opportunity immediately after the publisher starts
- 600 seconds after a successful publication
- 600 seconds after Forge reports the candidate as stale (`HTTP 409`), because Forge already has that fix or a newer one
- 60 seconds after network/HTTP publication failure
- 30 seconds while no usable fresh GPS fix is available

The scheduler itself wakes every 30 seconds. Cadence decisions use monotonic time so wall-clock corrections cannot trigger bursts or extend a retry unexpectedly.

## Duplicate and retry behavior

After a successful publication, the accepted `fix_at` is marked consumed and will not be sent again merely because a UI or scheduler callback observed the same immutable GPS state.

A Forge stale rejection also consumes that fix and prevents repeated `409` requests for the same timestamp.

A transient network failure does **not** consume the fix. The same fix may be retried only if it is still valid and fresh when the retry actually runs; otherwise the current GPS state is evaluated and stale data is skipped.

## Failure isolation

Expected Forge connection/response failures are converted into immutable publisher state and never escape into GPS polling, map, controls, shared spots, radio polling, or local logging.

Unexpected worker exceptions are logged and the scheduler remains eligible for a later bounded retry.

Stopping the dashboard cancels future callbacks and waits for the single bounded in-flight worker before GPS polling is stopped.

## Configuration and mock safety

No new YAML credential or endpoint is introduced. The publisher reuses the existing validated Forge configuration:

```yaml
forge:
  enabled: true
  api_url: http://192.168.9.170:8766
  request_timeout_s: 5.0
```

The production publisher is composed only when:

1. Forge is enabled, and
2. the selected GPS hardware mode is `real`.

Mock GPS mode can still use Forge shared-spot reads but does not compose the location publisher. This prevents development/mock coordinates from being written to production Forge accidentally.

If Forge is disabled or not configured, the location publisher is absent and performs no work.

## Private-network security boundary

Checkpoint #161 does not change the security decision from checkpoint #160. The supported path remains the private routed network:

```text
anvilmobile / CarLAN
    -> WireGuard
    -> RadioLAN
    -> Forge 192.168.9.170:8766
```

The endpoint has no application bearer token or TLS in this checkpoint. Wider or untrusted-network exposure remains unsupported.

## Radio safety boundary

Location publication has no CAT, frequency/mode, PTT/MOX, keying, tuner, power, or transmit authority. Network failure or a rejected location cannot initiate a radio operation.

## Acceptance

Before checkpoint #161 is Ready for review:

1. Ruff, strict MyPy, and the full pytest suite must pass on the exact PR head.
2. `anvilmobile` must run the exact accepted branch head with its real GPS.
3. A fresh trusted fix must be published over the private network to production Forge.
4. Forge must retain a newer mobile-location revision containing the observed Pi coordinates and typed GPS UTC `fix_at`.
5. No overlapping request or foreground/UI network work may be observed.
6. A temporary Forge/network failure must not disturb GPS polling or the rest of the dashboard runtime.
7. Existing Forge `/api/v1/health` and `/api/v1/spots` must remain healthy.

## Scope

Checkpoint #161 publishes mobile GPS only. It does not fetch weather, add radar, change maps, add repeater data, or alter CAT behavior.
