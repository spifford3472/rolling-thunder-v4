# Real Yaesu FT-891 Integration

## Scope

This document covers Milestone 10 Phase B, first slice: read-only integration of
the installed Yaesu FT-891. The approved live commands in this slice request the
current VFO-A frequency and operating mode only.

Receive-only frequency, mode, band, and confirmed POTA tuning remain a later
validation step. This slice adds no PTT, MOX, CW keying, voice keying, automatic
transmission, or unattended transmit authority.

## Verified USB Interfaces

Live observation on `anvilmobile` identified the FT-891 USB bridge as a Silicon
Labs CP2105 dual UART with serial number `011F42E9`.

The two interfaces have different safety roles:

| Interface | Stable path suffix | Observed tty | Purpose |
| --- | --- | --- | --- |
| Enhanced Com Port | `if00-port0` | `/dev/ttyUSB1` | CAT frequency and mode |
| Standard Com Port | `if01-port0` | `/dev/ttyUSB2` | PTT, CW keying, and digital TX control |

Rolling Thunder must use only the Enhanced Com Port:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-if00-port0
```

The Standard Com Port must not be configured as `hardware.radio_device` and was
not opened during read-only validation.

## Verified Serial Settings

The installed radio responded successfully with:

- 38,400 baud
- 8 data bits
- no parity
- 2 stop bits
- semicolon-terminated CAT commands and replies

The read-only live probe sent only:

```text
FA;
MD0;
```

The radio replied with a current state of 7.273020 MHz, LSB. Rolling Thunder
reported `transmitting=False`, closed the transport, and released the device.

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

Use a stable `/dev/serial/by-id` path rather than `/dev/ttyUSB1`, because tty
numbers can change after USB reconnects. The configured user must have access to
the serial device; user `geoff` is a member of `dialout` on the verified Pi.

## Runtime Behavior

Radio polling owns initial connection and recovery. It operates outside the
Tkinter thread through the existing scheduler boundary.

At startup:

- the application attempts to connect to the configured Enhanced CAT port
- successful connection publishes current frequency and mode
- failed connection publishes visible radio error state
- local application services and GPS polling continue running
- polling remains scheduled and retries the radio connection

After a read failure or physical disconnect:

- the FT-891 adapter closes the failed CAT transport
- the last known frequency and mode remain available with error state
- software transmit state remains false
- polling continues and retries the stable by-id path
- reconnection refreshes current hardware frequency and mode without restarting
  the application

## Safety Boundary

The typed `Radio` boundary exposes no PTT operation. This integration does not add
or issue raw commands for:

- PTT or MOX
- CW keying
- voice keying
- digital-mode TX control
- unattended transmit

The read-only hardware test must not call `set_frequency`, `set_mode`,
`change_band`, or the POTA tune executor. Receive-only tuning will be validated
separately through the existing explicit operator-confirmation path.

## Automated Coverage

Automated tests use fakes and manual schedulers. They cover:

- verified default CAT baud and timeout settings
- invalid CAT configuration
- real-radio plus mock-GPS composition
- configured device, baud, and timeout factory arguments
- unavailable radio at application startup
- visible error state while local services continue
- disconnect error with last-known state
- continued polling after failure
- automatic reconnect and refreshed frequency/mode
- non-overlapping hardware callbacks

Automated tests never open a physical serial device.

## Live Validation Sequence

Before approval and merge:

1. Confirm the configured path resolves to the Enhanced Com Port.
2. Confirm the Standard Com Port remains unopened.
3. Start Rolling Thunder with real radio and mock or real GPS as selected.
4. Confirm the dashboard displays the FT-891 frequency and mode.
5. Change frequency and mode manually on the radio and confirm display updates.
6. Unplug only the FT-891 USB connection.
7. Confirm the dashboard remains running and radio state becomes unavailable or
   error while local logging and GPS remain available.
8. Reconnect the same USB cable.
9. Confirm radio state automatically returns without restarting the application.
10. Confirm no frequency-set, mode-set, band-change, PTT, MOX, or keying command
    was issued during this read-only validation.
