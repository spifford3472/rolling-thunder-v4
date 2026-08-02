# Real GPS Integration

## Scope

This document covers Milestone 10 Phase A: integrating a physical read-only GPS
receiver while the FT-891 remains mocked. Mapping and physical-radio control are
separate later changes.

## Verified Receiver

Live testing on `anvilmobile` identified this stable serial path:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_a67ea6d582f4ef11804abf1b6d9880ab-if00-port0
```

The path resolves to `/dev/ttyUSB3` in the tested installation. Configuration
must use the stable `/dev/serial/by-id` link rather than the transient tty number.

Observed serial settings and stream characteristics:

- 9600 baud, 8 data bits, no parity, 1 stop bit
- checksummed ASCII NMEA output
- approximately one `GNGGA` position sentence per second
- interleaved `GNRMC`, `GNZDA`, `GPGSA`, `GLGSA`, `GPGSV`, `GLGSV`, `GPGST`,
  and `GPGRS` sentences
- a valid differential GGA fix with fix quality 2
- opening the live stream can begin in the middle of a sentence

## Configuration

The legacy `hardware.mock` value remains the fallback for configurations that do
not define per-device modes. Physical GPS testing with a safely mocked radio uses:

```yaml
hardware:
  mock: true
  radio_mode: mock
  gps_mode: real
  radio_device: null
  gps_device: /dev/serial/by-id/usb-Silicon_Labs_CP2102N_USB_to_UART_Bridge_Controller_a67ea6d582f4ef11804abf1b6d9880ab-if00-port0
  gps_baud_rate: 9600
  gps_timeout_s: 2.0
```

The configured user must have read/write access to the serial device. On the
verified Pi, user `geoff` is already a member of `dialout`.

## Runtime Behavior

The serial adapter is read-only. It never sends receiver configuration commands.

Each refresh performs a bounded scan for the next supported `GPGGA` or `GNGGA`
sentence. Complete NMEA candidates receive strict checksum validation. Valid
non-GGA sentences are skipped. A truncated or non-ASCII opening fragment is
skipped because opening an active stream can begin mid-sentence.

A missing, timed-out, malformed, or disconnected GPS produces explicit GPS error
state. GPS polling continues and attempts reconnection. Physical read failures
close the failed serial handle so the stable by-id path can be reopened after the
receiver is reattached.

GPS failure does not prevent the application runtime, mock radio, local contact
logging, or other local services from starting.

## Automated Coverage

Automated tests use fake serial ports and manual schedulers. They cover:

- valid GGA and no-fix parsing
- southern and western coordinates
- mixed live NMEA streams
- truncated and non-ASCII opening fragments
- bad checksums
- missing GGA within the bounded scan
- read timeout
- physical disconnect and reopen
- degraded startup and background retry
- mock radio with real GPS configuration
- runtime startup while GPS is unavailable

Automated tests do not open physical hardware.

## Live Validation

Before merge, validate on `anvilmobile` with the FT-891 still mocked:

1. Confirm the stable GPS by-id link exists.
2. Start the application with the mixed configuration shown above.
3. Confirm GPS reaches READY and the displayed coordinates/grid are plausible.
4. Unplug only the CP2102N GPS receiver.
5. Confirm the dashboard remains running, logging remains available, and GPS
   changes to an unavailable/error presentation.
6. Reconnect the same receiver.
7. Confirm GPS returns to READY without restarting the application.
8. Confirm no FT-891 CAT device was opened or commanded during the test.

The pull request remains draft until this hardware behavior is observed and
approved by the repository owner.
