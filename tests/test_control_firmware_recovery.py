"""Compile real firmware logic against GPIO/serial stubs; no device upload."""

import shutil
import subprocess
from pathlib import Path

import pytest

from rolling_thunder.control_protocol_v2 import Event, Pong, Ready, parse_v2_line

ARDUINO = r"""
#pragma once
#include <cstdint>
#include <string>
#include <cstring>
#include <cstddef>
inline uint64_t fake_us = 0;
inline int pins[40] = {};
constexpr int HIGH = 1, LOW = 0, INPUT_PULLUP = 2;
inline void pinMode(int, int) {}
inline int digitalRead(int pin) { return pins[pin]; }
inline unsigned long millis() { return static_cast<uint32_t>(fake_us / 1000); }
inline void delay(unsigned long ms) { fake_us += ms * 1000; }
struct FakeSerial {
    std::string incoming, output;
    void setTxBufferSize(size_t) {}
    void begin(unsigned long) {}
    int available() { return static_cast<int>(incoming.size()); }
    int availableForWrite() { return 256; }
    int read() { auto c = incoming.front(); incoming.erase(0, 1); return static_cast<unsigned char>(c); }
    size_t write(const uint8_t* p, size_t n) { output.append(reinterpret_cast<const char*>(p), n); return n; }
};
inline FakeSerial Serial;
"""

PROGRAM = r"""
#define RTCTRL_RECOVERY_V2
#include "main.cpp"
#include <cassert>
#include <iostream>
#include <string>
std::string take() { std::string out = Serial.output; Serial.output.clear(); return out; }
std::string send(const std::string& s) { Serial.incoming += s; loop(); return take(); }
std::string step(uint64_t ms) { fake_us += ms * 1000; loop(); return take(); }
int main(int argc, char**) {
    for (int& pin : pins) pin = HIGH;
    if (argc > 1) watchdog_fail = true;
    pins[23] = LOW; // Held voice key at boot must never become an action.
    setup();
    const std::string n(32, 'a'), n2(32, 'c'), n3(32, 'd');
    if (argc > 1) {
        assert(!recovery_watchdog_ready);
        assert(send("RTCTRL/2 HELLO " + n + "\n").empty());
        return 0;
    }
    assert(recovery_watchdog_ready);
    std::string frames = send("RTCTRL/2 HELLO " + n + "\n");
    assert(frames.find("READY") != std::string::npos);
    assert(send("RTCTRL/2 HELLO " + n + "\n").empty());
    assert(step(50).empty());
    pins[23] = HIGH;
    assert(step(1).empty());
    assert(step(41).empty());
    pins[23] = LOW;
    assert(step(1).empty());
    std::string event = step(41);
    assert(event.find("voice-button") != std::string::npos);
    frames += event;
    frames += send("RTCTRL/2 PING " + n + " 1\n");
    assert(send("RTCTRL/2 PING " + n + " 01\n").empty());
    assert(send("RTCTRL/2 PING " + n + " 18446744073709551616\n").empty());
    pins[18] = LOW; // Short/long key held across session replacement.
    encoder_transition_accumulator = 2;
    std::string ready = send("RTCTRL/2 HELLO " + n2 + "\n");
    assert(ready.find("READY") != std::string::npos);
    assert(encoder_transition_accumulator == 0);
    frames += ready;
    pins[18] = HIGH;
    assert(step(1).empty());
    assert(step(41).empty()); // Release of old held key is discarded.
    pins[18] = LOW;
    assert(step(1).empty());
    assert(step(41).empty());
    pins[18] = HIGH;
    assert(step(1).empty());
    event = step(41);
    assert(event.find("context-button-1-short") != std::string::npos);
    frames += event;
    assert(step(800).empty());
    char output[256];
    assert(!recovery_session->event("voice-button", recovery_now(), output, sizeof(output)));
    std::string malformed = "RTCTRL/2 HELLO " + n3;
    malformed.push_back(0);
    malformed += "junk\n";
    assert(send(malformed).empty());
    assert(send(std::string(300, 'x') + "RTCTRL/2 HELLO " + n3 + "\n").empty());
    while (!Serial.incoming.empty()) loop();
    assert(take().empty());
    fake_us = (uint64_t{1} << 32) * 1000 + 2000000;
    ready = send("RTCTRL/2 HELLO " + n3 + "\n");
    assert(ready.find("4294969296") != std::string::npos);
    frames += ready;
    assert(watchdog_resets > 0);
    std::cout << frames;
}
"""


@pytest.fixture(scope="module")
def firmware_program(tmp_path_factory) -> Path:
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("Native firmware regression requires g++")
    folder = tmp_path_factory.mktemp("control-firmware")
    headers = {
        "Arduino.h": ARDUINO,
        "esp_system.h": "#pragma once\n#include <cstdint>\ninline uint32_t esp_random() { static uint32_t n = 1; return n++; }\n",
        "esp_timer.h": "#pragma once\ninline int64_t esp_timer_get_time() { return static_cast<int64_t>(fake_us); }\n",
        "esp_idf_version.h": "#pragma once\n#define ESP_IDF_VERSION_MAJOR 4\n",
        "esp_task_wdt.h": "#pragma once\nusing esp_err_t = int;\nconstexpr int ESP_OK = 0;\ninline bool watchdog_fail = false;\ninline int watchdog_resets = 0;\ninline int esp_task_wdt_init(unsigned, bool) { return watchdog_fail ? -1 : 0; }\ninline int esp_task_wdt_add(void*) { return 0; }\ninline int esp_task_wdt_reset() { ++watchdog_resets; return 0; }\n",
    }
    for name, content in headers.items():
        (folder / name).write_text(content)
    program = folder / "test.cpp"
    program.write_text(PROGRAM)
    executable = folder / "firmware-test"
    firmware = Path(__file__).resolve().parents[1] / "firmware/esp32-controls/src"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(folder),
            "-I",
            str(firmware),
            str(program),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return executable


def test_real_firmware_held_keys_sessions_and_wire_contract(firmware_program: Path) -> None:
    result = subprocess.run([str(firmware_program)], check=True, capture_output=True, timeout=5)
    frames = [parse_v2_line(line + b"\n") for line in result.stdout.splitlines()]
    assert sum(isinstance(f, Ready) for f in frames) == 3
    assert sum(isinstance(f, Event) for f in frames) == 2
    assert sum(isinstance(f, Pong) for f in frames) == 1
    assert isinstance(frames[-1], Ready) and frames[-1].uptime_ms > 2**32


def test_watchdog_registration_failure_emits_no_session_or_actions(firmware_program: Path) -> None:
    result = subprocess.run(
        [str(firmware_program), "watchdog-failure"], check=True, capture_output=True, timeout=5
    )
    assert result.stdout == b""
