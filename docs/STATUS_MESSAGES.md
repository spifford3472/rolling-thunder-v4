# Status Message Arbitration

## Purpose

Rolling Thunder uses one runtime-owned status-message service for transient
operator messages in the global bottom status area. The service prevents
individual features from directly overwriting the ticker and provides
deterministic priority and expiration behavior for current and future operator
alerts.

The same bottom area also contains a persistent one-row graphical health strip.
The graphical cells and transient ticker have separate responsibilities: health
cells remain visible while higher-priority operator messages temporarily replace
only the ticker text.

## Vehicle Status Strip

The bottom bar is 76 pixels high. Its left side contains four equal 76-pixel
cells in this fixed order:

1. HF radio
2. Internet
3. Forge
4. microphone

Each cell renders a programmatic 68-pixel canvas icon. The icons do not depend on
Unicode or emoji fonts. Healthy/available state is green, failed/unavailable
state is red, and a bounded starting/indeterminate state is neutral gray.
Additional cells should extend the shared `StatusItemId`/`STATUS_ITEM_ORDER`
presentation model rather than creating unrelated labels.

The Tk dashboard performs no health I/O. It reads the latest immutable
`StatusMonitorSnapshot` and the already-authoritative radio state, builds one
pure `StatusStripSnapshot`, and renders that snapshot. Network and device probes
run through the background polling scheduler.

### HF radio definition

The HF cell consumes `runtime.latest_radio_state.connection_state`, which is
already maintained by the existing radio polling service. `CONNECTED` is green;
disconnected or error states are red. The status strip does not create another
CAT poller or radio-health authority.

### Internet definition

The Internet probe answers whether `anvilmobile` can establish a real external
TCP connection through the vehicle router. It uses the numeric address
`8.8.8.8` on TCP port 53, so the probe itself does not depend on DNS resolution.
The connect timeout is 2 seconds and the normal polling interval is 15 seconds.
The socket is closed immediately after the bounded check.

After Internet has become healthy, one failed check retains the previous green
state. Two consecutive failed checks are required to turn the cell red. A
successful check recovers to green immediately. This suppresses distracting
single-sample flicker without concealing a sustained outage.

### Forge definition

Forge health is independent of public Internet health. The probe reuses the
existing configured Forge base URL and the existing `GET /api/v1/health`
endpoint. It uses `forge.request_timeout_s`; no additional Forge API is required.

- `service_status: healthy` -> green
- `service_status: starting` -> neutral
- `degraded`, `unavailable`, timeout, connection failure, non-2xx response, or
  invalid health payload -> red

The Internet and Forge cells are never artificially tied together, so private
Forge reachability can remain healthy even when public Internet is unavailable.

### Microphone definition

The microphone cell uses the configured `speech.audio_device`. For a configured
ALSA selector such as `plughw:CARD=Array,DEV=0`, the background probe reads
`/proc/asound/cards` and `/proc/asound/pcm`, resolves the configured card, and
verifies that the requested PCM device is enumerated with a capture capability.
It does not open the microphone, run a recording, or repeatedly spawn
`arecord`.

For this status cell, **available** therefore means that the configured ALSA
capture endpoint is currently enumerated and exposes capture. It does not prove
that a long continuous recording will succeed through every possible USB cable;
full installation validation still requires the recording test documented in
`docs/setup/audio.md`.

### Polling and lifecycle

Internet, Forge, and microphone checks run together every 15 seconds on the
background scheduler. All network operations have bounded timeouts, probe
exceptions are converted to unavailable state instead of escaping into the UI,
and the monitor cancellation handle is stopped during dashboard shutdown.
Starting the monitor schedules work but performs no network/device probe on the
Tk caller.

To add another persistent status icon later:

1. add a stable `StatusItemId` and append it to `STATUS_ITEM_ORDER`;
2. add a bounded background probe only when new I/O is required;
3. add the immutable result to the monitor/presentation snapshot;
4. add one programmatic icon drawing function; and
5. keep Tk rendering free of probe logic and blocking I/O.

## Operator Behavior

The right side of the bottom bar normally shows routine non-icon status such as
voice, GPS, and synchronization state. Radio, Internet, Forge, and microphone
health are represented by the persistent graphical cells instead of duplicated
routine words.

When a higher-priority message is active, it temporarily replaces the routine
line. The icon cells remain visible and the routine line returns automatically
when the higher-priority message expires or is cleared.

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

The separate status monitor also exposes only immutable results to Tkinter; its
bounded network/filesystem probes run outside Tk.

Status publishing and health monitoring cannot create a second radio-control
path. The existing typed `ReceiveTuningService` remains the only receive-tuning
authority. No status message or health cell can provide PTT, MOX, keying, tuner,
power, or unattended transmit authority.

## Extension Points

Future APRS, MeshCore, weather, DX, radio, and connectivity alerts should
publish transient alerts through the status-message service using feature-owned
replacement keys. They must not add direct ticker overrides or perform blocking
work in Tkinter callbacks.

Persistent glanceable health belongs in the status-strip model described above,
not in transient-message arbitration. Priorities should represent operator
urgency rather than subsystem importance. Temporary alerts should use bounded
monotonic durations. Long-lived degraded state may remain non-expiring until its
owning publisher replaces or clears it.

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

The graphical vehicle-status-bar changes require a new target-Pi acceptance pass
before merge. Physical PASS by itself does not authorize merge.

The unresolved FT-891 CAT/front-panel band-context behavior is tracked in issue
#149 and is not represented as a verified automatic band change by status text.
