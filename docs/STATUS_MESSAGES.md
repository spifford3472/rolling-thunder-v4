# Status Message Arbitration

## Purpose

Rolling Thunder uses one runtime-owned status-message service for the global
bottom status bar. The service prevents individual features from directly
overwriting the ticker and provides deterministic priority and expiration
behavior for current and future operator alerts.

## Operator Behavior

The bottom bar normally shows the routine radio, GPS, network, Home Station
Platform, synchronization, and connectivity summary.

When a higher-priority message is active, it temporarily replaces the routine
line. The routine line remains retained and returns automatically when the
higher-priority message expires or is cleared.

A successful shared receive tune whose starting band differs from the target
band publishes the manual operator handoff:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

The band/ATAS reminder:

- appears in amber
- lasts exactly 10 seconds
- is published only for a successful cross-band receive tune
- is not published for a same-band tune
- names the target band
- does not claim that CAT authoritatively changed the FT-891 operator-visible band state
- does not claim that the ATAS-120 is tuned
- replaces an earlier reminder through the same stable replacement key
- expires automatically; the Back control does not dismiss it

The reminder is an explicit operator handoff. The operator manually sets or
confirms the FT-891 band and tunes the ATAS-120 before transmitting. Rolling
Thunder does not operate or verify the antenna tuner.

## Arbitration Rules

Each publisher uses a stable replacement key and supplies:

- message text
- a presentation token
- an integer priority
- an optional duration

The service uses a monotonic clock for expiration. The highest-priority
unexpired message is selected. When priorities are equal, the newest message
wins. Updating one replacement key does not disturb messages owned by other
publishers.

Lower-priority unexpired messages remain retained and resume automatically after
a higher-priority message expires or is cleared.

Checkpoint-8 shared receive-tune status durations are:

- tuning status: active until replaced by the result
- success status: 5 seconds
- failure status: 8 seconds
- cross-band manual band/ATAS reminder: 10 seconds at higher priority than the
  normal success result

## Architecture and Safety

`StatusMessageService` is thread-safe and exposes immutable message and snapshot
objects. Tkinter reads snapshots and maps presentation tokens to colors. The
service performs no:

- Tkinter widget work
- network requests
- filesystem access
- SQLite access
- CAT commands
- hardware access

Status publishing cannot create a second radio-control path. The existing typed
`ReceiveTuningService` remains the only receive-tuning authority. No status
message can provide PTT, MOX, keying, tuner, power, or unattended transmit
authority.

## Extension Points

Future APRS, MeshCore, weather, DX, radio, and connectivity alerts should
publish through this service using feature-owned replacement keys. They must not
add direct ticker overrides or perform blocking work in Tkinter callbacks.

Priorities should represent operator urgency rather than subsystem importance.
Temporary alerts should use bounded monotonic durations. Long-lived degraded
state may remain non-expiring until its owning publisher replaces or clears it.

## Target-Pi Acceptance

Checkpoint-8 target-Pi acceptance on `anvilmobile` verified that:

1. The normal routine ticker remains available.
2. A successful cross-band POTA/DX receive tune shows the amber
   `SET BAND TO <BAND> METERS — TUNE ATAS-120` reminder.
3. The reminder is timed and does not require Back acknowledgement.
4. The routine ticker resumes automatically after expiration.
5. Same-band tuning does not show the reminder.
6. Back retains its normal staging/selection cancellation behavior.
7. Logging, GPS, radio polling, physical controls, POTA/DX, and the live map
   remain responsive.
8. The Standard TX-capable FT-891 USB interface remains closed.
9. No PTT, MOX, keying, tuner, power, or transmit action occurs.

The unresolved FT-891 CAT/front-panel band-context behavior is tracked in issue
#149 and is not represented as a verified automatic band change by status text.
