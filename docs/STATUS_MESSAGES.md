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

A receive tune that verifies an actual band change publishes:

```text
BAND CHANGED TO <BAND> METERS — RETUNE ATAS-120
```

The ATAS-120 reminder:

- appears in amber
- lasts exactly 10 seconds
- is published only after a verified band change
- is not published for a same-band tune
- replaces an earlier ATAS reminder when another verified band change occurs
- expires automatically; the Back control does not dismiss it

The reminder is informational only. Rolling Thunder does not operate the
antenna tuner.

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

Before merging a change to status behavior, verify on `anvilmobile` that:

1. The normal routine ticker remains visible.
2. A verified cross-band receive tune shows the amber ATAS reminder.
3. The reminder remains visible for approximately 10 seconds.
4. The routine ticker resumes automatically.
5. Same-band tuning does not show the reminder.
6. Back retains its normal cancellation and navigation behavior.
7. Logging, GPS, radio polling, physical controls, POTA, and the live map remain
   responsive.
