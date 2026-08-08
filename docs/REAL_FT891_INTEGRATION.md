# Real Yaesu FT-891 Integration

## Scope

This document covers the installed Yaesu FT-891 integration and the safe
receive-only control path used by Rolling Thunder.

The implementation establishes and validates:

- stable USB device identity
- read-only CAT connection and background polling
- current VFO-A frequency and receive mode
- disconnect detection and automatic recovery
- independent band, frequency, and mode operations
- hard band-before-frequency ordering for cross-band receive changes
- exact read-back verification
- shared POTA/DX two-press receive tuning through `ReceiveTuningService`
- timed ATAS-120 operator warning after a verified band change

This work adds no PTT, MOX, CW keying, voice keying, tuner control, power control,
automatic transmission, or unattended transmit authority.

## Verified USB Interfaces

Live observation on `anvilmobile` identified the FT-891 USB bridge as a Silicon
Labs CP2105 dual UART with serial number `011F42E9`.

The two interfaces have different safety roles:

| Interface | Stable path suffix | Observed tty | Purpose |
| --- | --- | --- | --- |
| Enhanced Com Port | `if00-port0` | `/dev/ttyUSB1` | CAT state and approved receive control |
| Standard Com Port | `if01-port0` | `/dev/ttyUSB2` | PTT, CW keying, and digital TX control |

Rolling Thunder must use only the Enhanced Com Port:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

The Standard Com Port must not be configured as `hardware.radio_device` and must
remain unopened.

## Verified Serial Settings

The installed radio responded successfully with:

- 38,400 baud
- 8 data bits
- no parity
- 2 stop bits
- semicolon-terminated CAT commands and replies

The verified read commands include:

```text
FA;
MD0;
```

Read-only hardware tests confirmed current frequency and mode,
disconnect/reconnect recovery, and `transmitting=False`.

## Band, Frequency, and Mode Separation

Band selection, frequency setting, and mode setting remain independent typed
operations:

```text
select_band(band)
set_frequency(frequency)
set_mode(mode)
```

Band selection does not choose the final target frequency or receive mode.

The FT-891 CAT commands are:

```text
BSxx;          select band
FA#########;   set VFO-A frequency
MD0x;          set main receive mode
```

Supported CAT band-selection commands are:

| Band | Command |
| --- | --- |
| 160 m | `BS00;` |
| 80 m | `BS01;` |
| 40 m | `BS03;` |
| 30 m | `BS04;` |
| 20 m | `BS05;` |
| 17 m | `BS06;` |
| 15 m | `BS07;` |
| 12 m | `BS08;` |
| 10 m | `BS09;` |
| 6 m | `BS10;` |

The FT-891 CAT table has no dedicated 60-meter `BS` value. Software selection of
60 meters therefore fails closed.

## Required Receive-Tuning Order

`ReceiveTuningService` owns the approved receive-only sequence:

```text
Determine target band from requested frequency
Read current radio state

If target band differs:
    send BSxx;
    read FA; and MD0;
    verify returned frequency belongs to target band

send FA#########;
read FA;
verify exact requested frequency

send MD0x; when requested mode differs
read MD0;
verify requested mode
```

A direct cross-band `set_frequency()` call raises `BandChangeRequiredError`
before an `FA` command is transmitted.

A failed band verification prevents frequency and mode changes. A failed
frequency verification prevents the mode change.

Same-band tuning skips the `BS` command but still verifies frequency and mode.

`ReceiveTuningService` also refuses ordered receive tuning while the current
radio state reports `transmitting=True`.

## Shared POTA/DX Two-Press Path

Checkpoint 8 routes POTA and DX through the same operator-command and tuning
path:

```text
encoder / keyboard activation
    -> SharedSpotActivePanelCommandController
    -> SharedSpotTuneController
    -> ReceiveTuningService
    -> Ft891Radio
```

The operator contract is exactly two presses:

```text
first press
    -> stage exact selected identity/callsign/frequency/mode
    -> no CAT
    -> no radio change

second press on the same still-valid target
    -> submit exact staged action
    -> background receive tuning
    -> ReceiveTuningService
```

There is no third confirmation/execution press in the shared checkpoint-8 path.

Before staging or tuning, the active-panel command controller requires the latest
radio state to be connected, to have known frequency and mode, and not to report
transmitting. Otherwise staging is invalidated and the action fails closed.

Rotation, selection change, POTA/DX context change, band/mode filter change,
identity disappearance, action-critical callsign/frequency/mode mutation,
Back/Cancel, or radio invalidation clears staging.

No neighboring row can inherit a staged action.

## Background Tuning Boundary

The second press does not perform blocking CAT work in Tkinter.

`SharedSpotTuneController` owns background submission of the exact
`StagedSpotAction`. It publishes immutable tuning state for UI presentation:

- idle
- tuning
- succeeded
- failed

A busy background tuning boundary rejects a second concurrent submission rather
than creating overlapping receive-tune operations.

## Configuration

A real radio can be tested while GPS remains mocked:

```yaml
hardware:
  mock: true
  radio_mode: real
  gps_mode: mock
  radio_device: /dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
  radio_baud_rate: 38400
  radio_timeout_s: 1.0
  gps_device: null
```

Use the stable `/dev/serial/by-id` path rather than `/dev/ttyUSB1`, because tty
numbers can change after USB reconnects.

The configured user must have serial-device access. User `geoff` is a member of
`dialout` on the verified Pi.

## Runtime Behavior

Radio polling owns initial connection and recovery outside Tkinter.

At startup:

- the application connects to the configured Enhanced CAT port
- successful connection publishes current frequency and mode
- failed connection publishes visible radio error state
- local services and GPS continue running
- polling remains scheduled and retries the stable device path

After a CAT failure or physical disconnect:

- the adapter closes the failed transport
- the last known frequency and mode remain available with error state
- software transmit state remains false
- polling continues
- reconnection refreshes current hardware state without restarting the app

Shared receive-tuning operations use the ordered application service only after
explicit operator confirmation. Blocking CAT work must not run directly from a
Tkinter widget callback.

## ATAS-120 Retune Warning

Band selection and receive frequency changes do not imply that the ATAS-120 is
tuned or safe to transmit.

After a successful shared receive tune reports a verified band change, the
shared tune status controller publishes this amber status message:

```text
BAND CHANGED TO <BAND> METERS — RETUNE ATAS-120
```

Current checkpoint-8 behavior is:

- same-band receive tuning publishes no ATAS warning
- verified cross-band receive tuning publishes the verified target band
- the ATAS message uses higher status priority than the normal tune result
- the ATAS message expires automatically after 10 seconds
- success status is shown for 5 seconds
- failure status is shown for 8 seconds

Back is not the ATAS acknowledgement mechanism in checkpoint 8. Within the
shared POTA/DX panel, Back cancels staging first and clears selection on a later
Back action. The ATAS reminder is a timed `StatusMessageService` message.

The warning is presentation only. Rolling Thunder cannot tune or verify the
ATAS-120 and must never claim that the antenna is safe to transmit.

## Safety Boundary

The typed radio and receive-tuning boundaries expose no command for:

- PTT or MOX
- CW keying
- voice keying
- digital-mode TX control
- tuner control
- radio power control
- unattended transmit
- voice-originated receive tuning

The Standard Com Port must remain unopened.

The shared spot controller, physical-control parser/mapper, Forge client, Forge
service, and Tkinter do not issue raw CAT commands.

`ReceiveTuningService` is the sole approved receive-tuning authority.

## Automated Coverage

Automated tests use fakes, mock radios, fake CAT transports, fake tuning
boundaries, and deterministic schedulers. Coverage includes:

- exact `BSxx;` command encoding
- unsupported 60-meter selection
- shared frequency-to-band resolution
- same-band frequency changes
- prohibited direct cross-band frequency changes
- band, frequency, and mode read-back verification
- failures stopping subsequent operations
- ordered receive-tuning call sequence
- same-band tuning skipping band selection
- receive-tuning rejection while transmitting
- first shared activation staging only
- second shared activation submitting the exact staged action
- POTA and DX sharing the same execution boundary
- stale/action-mutated staging rejection
- radio-state invalidation
- background tune success and failure state
- exact timed ATAS-120 warning after verified band changes
- no ATAS warning for same-band tuning
- absence of PTT, MOX, keying, tuner, and power commands

Automated tests never open a physical serial device.

## Controlled Live Checkpoint-8 Validation

Perform live validation only while parked, with no PTT action and no
transmission.

### Preparation

1. Confirm the radio uses the Enhanced CAT stable device path.
2. Confirm the Standard Com Port is not open.
3. Confirm CAT speed is 38,400 baud.
4. Confirm Rolling Thunder reports the radio connected with known frequency and
   mode.
5. Note the starting frequency and mode.
6. Do not transmit; receive tuning does not tune the ATAS-120.

### First-Press Safety Test

For both a POTA target and a DX target:

1. Select the target with the installed controls.
2. Note the current FT-891 frequency and mode.
3. Press the encoder once.
4. Confirm the UI reports the target staged / press again to tune.
5. Confirm FT-891 frequency and mode have not changed.
6. Rotate to another row and confirm staging clears.

### Same-Band POTA Test

1. Select a POTA target on the current band.
2. First press stages only; verify no radio change.
3. Second press submits the tune.
4. Confirm no `BS` band selection is required.
5. Confirm final frequency read-back matches exactly.
6. Confirm requested receive mode read-back matches.
7. Confirm no ATAS warning is displayed.
8. Confirm no transmit action occurs.

### Cross-Band POTA Test

1. Select a POTA target on another supported band.
2. First press stages only; verify no radio change.
3. Second press submits the tune.
4. Confirm band selection occurs before target frequency.
5. Confirm band, frequency, and mode read-backs succeed.
6. Confirm the amber ATAS message names the verified target band.
7. Confirm it expires after the timed status duration.
8. Confirm no PTT/MOX/keying/tuner/power action occurs.

### Same-Band DX Test

Repeat the same-band procedure using a DX target and verify the exact same
operator-command, background-tune, and `ReceiveTuningService` path.

### Cross-Band DX Test

Repeat the cross-band procedure using a DX target and verify band-before-
frequency ordering, exact read-back, timed ATAS warning, and no transmit action.

### Invalidation Tests

With a staged target, separately verify that staging clears on:

- encoder movement
- provider/context change
- band-filter change
- mode-filter change
- Back/Cancel

Where practical with test state rather than unsafe live manipulation, also verify
that disconnected/invalid radio state prevents submission.

### Offline Continuity

During a controlled Forge interruption:

1. confirm retained/cached POTA/DX data remains presentable when a valid prior
   snapshot exists
2. confirm local contact logging still works
3. confirm Forge failure does not create any alternate radio-control path

Record the observed starting state, selected target, first-press state, final
read-back state, ATAS status behavior, and any recovery behavior before issue
#148 is approved for merge.
