# Rolling Thunder ESP32 Controls

The ESP32 reports physical control input events to the Rolling Thunder
Raspberry Pi client over one-way USB serial.

The Raspberry Pi does not send commands, acknowledgments, LED state, or other
information back to the ESP32.

## Confirmed hardware

- ESP32-D0WD-V3 development board
- ESP-32S module
- CP2102 USB-to-UART bridge
- 40 MHz crystal
- PlatformIO board target: `esp32dev`
- USB serial speed: 115200 baud
- Confirmed Linux device during bench testing: `/dev/ttyUSB0`

## Pin map

| Physical control | ESP32 GPIO |
|---|---:|
| Encoder CLK | 32 |
| Encoder DT | 33 |
| Encoder switch | 25 |
| Voice | 23 |
| Commit | 22 |
| Discard | 21 |
| Panel | 19 |
| Context 1 | 18 |
| Context 2 | 27 |
| Context 3 | 26 |

## Wiring

Rotary encoder:

    Encoder GND -> ESP32 GND
    Encoder +   -> ESP32 3V3
    Encoder SW  -> GPIO 25
    Encoder DT  -> GPIO 33
    Encoder CLK -> GPIO 32

Use 3.3 V for the encoder module. Do not connect its `+` terminal to 5 V.

Each separate pushbutton is wired between its assigned GPIO and the common
ground rail:

    GPIO ---- normally-open button ---- GND

All button grounds and the encoder ground may share one ESP32 GND connection.

## Button behavior

Voice, Commit, and Discard are permanent direct controls. They emit one event
immediately after a debounced press. Holding them does not create repeat
events or secondary actions.

Panel, Context 1, Context 2, Context 3, and the encoder switch support short
and long presses:

- short press: released before 800 milliseconds
- long press: held for at least 800 milliseconds
- the event is emitted on release
- a long press never also emits the short-press event
- holding a control does not generate repeat events

Encoder rotation emits one direction event for each decoded detent.

## Event catalog

Permanent buttons:

| Physical action | Input event identifier |
|---|---|
| Press Voice | `voice-button` |
| Press Commit | `commit-button` |
| Press Discard | `discard-button` |

Panel and context buttons:

| Physical action | Input event identifier |
|---|---|
| Short Panel press | `panel-button-short` |
| Long Panel press | `panel-button-long` |
| Short Context 1 press | `context-button-1-short` |
| Long Context 1 press | `context-button-1-long` |
| Short Context 2 press | `context-button-2-short` |
| Long Context 2 press | `context-button-2-long` |
| Short Context 3 press | `context-button-3-short` |
| Long Context 3 press | `context-button-3-long` |

Rotary encoder:

| Physical action | Input event identifier |
|---|---|
| Rotate clockwise one detent | `encoder-clockwise` |
| Rotate counterclockwise one detent | `encoder-counterclockwise` |
| Short encoder-switch press | `encoder-switch-short` |
| Long encoder-switch press | `encoder-switch-long` |

The identifiers describe only physical inputs. Their application meaning is
selected by the Raspberry Pi according to the active panel.

The ESP32 contains no POTA, DX, repeater, logging, radio-tuning, transmit,
PTT, MOX, or menu-navigation policy.

## Serial protocol

Each event is emitted as one ASCII line:

    RTCTRL/1 EVENT <input-id> <event-id> <seconds-since-boot>

Example:

    RTCTRL/1 EVENT panel-button-short 8f2ad392-00000001 52.195

The event ID combines a random boot-session identifier with an incrementing
sequence number.

The timestamp is the ESP32 uptime in seconds. The Raspberry Pi uses its own
monotonic clock for repeat suppression so an ESP32 reboot does not disable
controls.

## Build

    pio run --project-dir firmware/esp32-controls

## Upload

    pio run --project-dir firmware/esp32-controls --target upload --upload-port /dev/ttyUSB0

The confirmed reliable upload speed for this board is 115200 baud.

## Monitor

    pio device monitor --port /dev/ttyUSB0 --baud 115200

## Direction correction

If clockwise rotation reports `encoder-counterclockwise`, exchange the encoder
CLK and DT connections. No application-level mapping change is required.

## Opt-in recovery firmware candidate

The default `esp32dev` target still uses the one-way RTCTRL/1 protocol above. A separate `esp32dev-recovery` target implements health-only host challenges, session-bound input, held-button suppression and task watchdog registration. It requires the new host worker, which is not composed/activated. Build only with `pio run --project-dir firmware/esp32-controls -e esp32dev-recovery`; do not upload until parked board identity, firmware rollback and DTR/RTS behavior are reviewed. See [the recovery engineering guide](../../docs/engineering/controller-recovery-v2.md) for the exact protocol, tests and commissioning gates. Neither target has been flashed by this development work.
