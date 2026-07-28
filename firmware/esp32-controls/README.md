# Rolling Thunder ESP32 Controls

Minimal ESP32 firmware for reporting physical button events to the Rolling
Thunder Raspberry Pi client.

## Confirmed hardware

- ESP32-D0WD-V3 development board
- ESP-32S module
- CP2102 USB-to-UART bridge
- 40 MHz crystal
- PlatformIO board target: `esp32dev`
- Linux serial device during bench testing: `/dev/ttyUSB0`

## Test-button wiring

Disconnect USB power before changing wiring.

    GPIO 23 ---- normally-open pushbutton ---- GND

GPIO 23 uses the ESP32 internal pull-up resistor. Do not connect the input to
5 V.

## Protocol

A debounced button press emits one ASCII line at 115200 baud:

    RTCTRL/1 EVENT test-button <boot-session>-<sequence> <seconds-since-boot>

Example:

    RTCTRL/1 EVENT test-button 8f2ad392-00000001 52.195

The ESP32 reports opaque input identifiers only. Application actions such as
voice capture, commit, discard, context selection, tuning, or transmit control
remain defined and enforced on the Raspberry Pi.

## Build

    pio run --project-dir firmware/esp32-controls

## Upload

    pio run --project-dir firmware/esp32-controls --target upload --upload-port /dev/ttyUSB0

The confirmed reliable upload speed for this board is 115200 baud.

## Monitor

    pio device monitor --port /dev/ttyUSB0 --baud 115200

## Bench results

The initial GPIO 23 test confirmed:

- one event per deliberate press
- no repeated events while held
- stable boot-session event identifiers
- sequential event numbering
- valid RTCTRL/1 messages accepted by the host parser
