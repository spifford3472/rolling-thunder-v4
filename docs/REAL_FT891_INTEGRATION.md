# Real Yaesu FT-891 Integration

## Scope

This document covers Milestone 10 Phase B integration of the installed Yaesu
FT-891.

The first Phase B slice established and validated:

- stable USB device identity
- read-only CAT connection
- current VFO-A frequency and receive mode
- background polling
- disconnect detection
- automatic recovery

The ordered receive-only control slice is implemented, hardware-validated, and
merged. Band, frequency, and mode remain separate operations with a hard
band-before-frequency rule.

The current Phase B slice adds the required sticky ATAS-120 operator warning
after a verified band change. It adds presentation and acknowledgement state
only. It does not attempt to tune or verify the antenna.

This work adds no PTT, MOX, CW keying, voice keying, tuner control, power
control, automatic transmission, or unattended transmit authority.

## Verified USB Interfaces

Live observation on `anvilmobile` identified the FT-891 USB bridge as a Silicon
Labs CP2105 dual UART with serial number `011F42E9`.

The two interfaces have different safety roles:

| Interface | Stable path suffix | Observed tty | Purpose |
| --- | --- | --- | --- |
| Enhanced Com Port | `if00-port0` | `/dev/ttyUSB1` | CAT state and receive control |
| Standard Com Port | `if01-port0` | `/dev/ttyUSB2` | PTT, CW keying, and digital TX control |

Rolling Thunder must use only the Enhanced Com Port:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

The Standard Com Port must not be configured as `hardware.radio_device` and
must remain unopened.

## Verified Serial Settings

The installed radio responded successfully with:

- 38,400 baud
- 8 data bits
- no parity
- 2 stop bits
- semicolon-terminated CAT commands and replies

The verified read commands are:

```text
FA;
MD0;
```

The read-only hardware tests confirmed current frequency and mode,
disconnect/reconnect recovery, and `transmitting=False`.

## Band, Frequency, and Mode Separation

Band selection, frequency setting, and mode setting are independent operations:

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

The supported CAT band-selection commands are:

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

The FT-891 CAT table has no dedicated 60-meter `BS` value. Software selection
of 60 meters therefore fails closed.

## Required Receive-Tuning Order

The shared `ReceiveTuningService` owns the required sequence:

```text
Determine target band from requested frequency
Read current frequency and determine current band

If the target band differs:
    send BSxx;
    read FA; and MD0;
    verify the returned frequency belongs to the target band

send FA#########;
read FA;
verify the exact requested frequency

send MD0x; when the requested mode differs
read MD0;
verify the requested mode
```

A direct cross-band `set_frequency()` call raises
`BandChangeRequiredError` before an `FA` command is transmitted.

A failed band verification prevents frequency and mode changes. A failed
frequency verification prevents the mode change.

Same-band tuning skips the `BS` command but still verifies frequency and mode.

Confirmed POTA tuning uses this same ordered service. POTA code has no direct
frequency, mode, band, PTT, or transmit-command path.

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

Radio polling owns initial connection and recovery outside the Tkinter thread.

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

Receive-tuning operations use the ordered application service through the
existing explicit operator-confirmation path. Blocking CAT work must not run
directly from a Tkinter widget callback.

## ATAS-120 Retune Warning

Band selection and receive frequency changes do not imply that the ATAS-120 is
tuned or safe to transmit.

After a receive-tuning result reports a verified band change, Rolling Thunder
publishes this sticky operator warning in the always-visible full-screen bottom
ticker. Amber warning text temporarily replaces routine ticker status until the
operator acknowledges it:

```text
BAND CHANGED TO <BAND> METERS — RETUNE ATAS-120
```

The warning behavior is intentionally narrow and explicit:

- same-band frequency or mode changes publish no warning
- a verified cross-band result publishes the verified target band
- the warning survives POTA selection, filter, and execution-result cleanup
- a later same-band tune does not clear an existing warning
- a later verified band change replaces the warning with the new band
- the existing Back or X interaction explicitly acknowledges and clears it from any dashboard context
- Back acknowledges the warning before cancelling an intent or clearing a row

The warning is presentation and acknowledgement state only. Rolling Thunder
still cannot tune or verify the ATAS-120 and must never claim that the antenna
is safe to transmit.

## Safety Boundary

The typed radio and receive-tuning boundaries expose no command for:

- PTT or MOX
- CW keying
- voice keying
- digital-mode TX control
- tuner control
- radio power control
- unattended transmit

The Standard Com Port must remain unopened. The radio state remains
`transmitting=False` throughout this scope.

## Automated Coverage

Automated tests use fakes, mock radios, fake CAT transports, and manual
schedulers. Coverage includes:

- exact `BSxx;` command encoding
- unsupported 60-meter selection
- shared frequency-to-band resolution
- same-band frequency changes
- prohibited direct cross-band frequency changes
- band, frequency, and mode read-back verification
- failures stopping subsequent operations
- ordered receive-tuning call sequence
- same-band tuning skipping band selection
- confirmed POTA tuning through the ordered service
- exact ATAS-120 warning text after verified band changes
- no warning for same-band tuning
- sticky warning persistence across result and selection cleanup
- later same-band tuning preserving an existing warning
- later band changes replacing the warning band
- explicit acknowledgement and Back-command priority
- startup failure and recovery
- absence of PTT, MOX, keying, tuner, and power commands

Automated tests never open a physical serial device.

## Controlled Live Validation

Perform live validation only while parked, with no PTT action and no
transmission.

### Preparation

1. Confirm the radio uses the Enhanced CAT device path.
2. Confirm the Standard Com Port is not open.
3. Confirm CAT speed is 38,400 baud.
4. Start on a known amateur band and note the current frequency and mode.
5. Do not transmit; receive tuning does not tune the ATAS-120.

### Same-Band Test

1. Request a receive frequency on the current band.
2. Confirm no `BS` band-selection command is required.
3. Confirm the radio moves to the requested frequency.
4. Confirm frequency read-back matches exactly.
5. Change receive mode if needed.
6. Confirm mode read-back matches.
7. Confirm no ATAS-120 warning is displayed.
8. Confirm `transmitting=False`.

### Cross-Band Test

1. Request a receive frequency on a different supported band.
2. Confirm band selection occurs before the target frequency.
3. Confirm the selected band is read back and verified.
4. Confirm the target frequency is then set and verified.
5. Confirm the requested receive mode is then set and verified.
6. Confirm the visible warning names the verified target band.
7. Change selection or context and confirm the warning remains retained.
8. Use Back or X and confirm the warning clears before other POTA state.
9. Confirm no PTT, MOX, keying, tuner, or power command occurs.
10. Do not transmit; the ATAS-120 has not been declared tuned.

### Confirmed POTA Test

1. Select one POTA spot.
2. Create the normal pending tune intent.
3. Explicitly confirm the intent.
4. Execute the tune once.
5. Confirm it follows the same band-first sequence.
6. Confirm duplicate execution remains rejected.
7. Confirm no voice or unattended action can trigger tuning.
8. Confirm same-band and cross-band warning behavior matches this document.

Record the observed starting state, requested state, final read-back state,
warning text and acknowledgement behavior, CAT device path, and any error or
recovery behavior before approving the pull request.
