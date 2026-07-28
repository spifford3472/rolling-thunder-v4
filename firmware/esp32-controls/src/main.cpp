#include <Arduino.h>
#include <esp_system.h>

namespace {

constexpr unsigned long kSerialBaudRate = 115200;
constexpr uint8_t kTestButtonPin = 23;
constexpr unsigned long kDebounceMilliseconds = 40;

bool stable_button_pressed = false;
bool last_raw_button_pressed = false;
unsigned long last_change_milliseconds = 0;

uint32_t boot_session_id = 0;
uint32_t event_sequence = 0;

void emit_button_event() {
    ++event_sequence;

    char event_id[32];
    snprintf(
        event_id,
        sizeof(event_id),
        "%08lx-%08lx",
        static_cast<unsigned long>(boot_session_id),
        static_cast<unsigned long>(event_sequence)
    );

    const double monotonic_seconds =
        static_cast<double>(millis()) / 1000.0;

    Serial.print("RTCTRL/1 EVENT test-button ");
    Serial.print(event_id);
    Serial.print(' ');
    Serial.println(monotonic_seconds, 3);
}

}  // namespace

void setup() {
    Serial.begin(kSerialBaudRate);
    pinMode(kTestButtonPin, INPUT_PULLUP);

    boot_session_id = esp_random();

    delay(250);
}

void loop() {
    const unsigned long now = millis();
    const bool raw_button_pressed =
        digitalRead(kTestButtonPin) == LOW;

    if (raw_button_pressed != last_raw_button_pressed) {
        last_raw_button_pressed = raw_button_pressed;
        last_change_milliseconds = now;
    }

    if (
        now - last_change_milliseconds >= kDebounceMilliseconds
        && stable_button_pressed != raw_button_pressed
    ) {
        stable_button_pressed = raw_button_pressed;

        if (stable_button_pressed) {
            emit_button_event();
        }
    }

    delay(1);
}
