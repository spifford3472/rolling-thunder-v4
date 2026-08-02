#include <Arduino.h>
#include <esp_system.h>

#include <array>
#include <cstdint>

namespace {

constexpr unsigned long kSerialBaudRate = 115200;
constexpr unsigned long kButtonDebounceMilliseconds = 40;
constexpr unsigned long kLongPressMilliseconds = 800;

// Rotary encoder.
constexpr uint8_t kEncoderClockPin = 32;
constexpr uint8_t kEncoderDataPin = 33;
constexpr uint8_t kEncoderSwitchPin = 25;

// Dedicated buttons.
constexpr uint8_t kVoiceButtonPin = 23;
constexpr uint8_t kCommitButtonPin = 22;
constexpr uint8_t kDiscardButtonPin = 21;

// Contextual buttons.
constexpr uint8_t kPanelButtonPin = 19;
constexpr uint8_t kContextButton1Pin = 18;
constexpr uint8_t kContextButton2Pin = 27;
constexpr uint8_t kContextButton3Pin = 26;

// Most mechanical encoders produce four valid quadrature transitions
// for one physical detent.
constexpr int8_t kEncoderTransitionsPerDetent = 4;

enum class ButtonBehavior : uint8_t {
    ImmediatePress,
    ShortLongOnRelease,
};

struct ButtonState {
    uint8_t pin;
    ButtonBehavior behavior;
    const char* short_event_id;
    const char* long_event_id;
    bool stable_pressed;
    bool last_raw_pressed;
    unsigned long last_change_milliseconds;
    unsigned long pressed_at_milliseconds;
};

std::array<ButtonState, 8> buttons{{
    {
        kVoiceButtonPin,
        ButtonBehavior::ImmediatePress,
        "voice-button",
        nullptr,
        false,
        false,
        0,
        0,
    },
    {
        kCommitButtonPin,
        ButtonBehavior::ImmediatePress,
        "commit-button",
        nullptr,
        false,
        false,
        0,
        0,
    },
    {
        kDiscardButtonPin,
        ButtonBehavior::ImmediatePress,
        "discard-button",
        nullptr,
        false,
        false,
        0,
        0,
    },
    {
        kPanelButtonPin,
        ButtonBehavior::ShortLongOnRelease,
        "panel-button-short",
        "panel-button-long",
        false,
        false,
        0,
        0,
    },
    {
        kContextButton1Pin,
        ButtonBehavior::ShortLongOnRelease,
        "context-button-1-short",
        "context-button-1-long",
        false,
        false,
        0,
        0,
    },
    {
        kContextButton2Pin,
        ButtonBehavior::ShortLongOnRelease,
        "context-button-2-short",
        "context-button-2-long",
        false,
        false,
        0,
        0,
    },
    {
        kContextButton3Pin,
        ButtonBehavior::ShortLongOnRelease,
        "context-button-3-short",
        "context-button-3-long",
        false,
        false,
        0,
        0,
    },
    {
        kEncoderSwitchPin,
        ButtonBehavior::ShortLongOnRelease,
        "encoder-switch-short",
        "encoder-switch-long",
        false,
        false,
        0,
        0,
    },
}};

uint32_t boot_session_id = 0;
uint32_t event_sequence = 0;

uint8_t previous_encoder_state = 0;
int8_t encoder_transition_accumulator = 0;

void emit_input_event(const char* input_id) {
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

    Serial.print("RTCTRL/1 EVENT ");
    Serial.print(input_id);
    Serial.print(' ');
    Serial.print(event_id);
    Serial.print(' ');
    Serial.println(monotonic_seconds, 3);
}

uint8_t read_encoder_state() {
    const uint8_t clock_state =
        digitalRead(kEncoderClockPin) == HIGH ? 1U : 0U;
    const uint8_t data_state =
        digitalRead(kEncoderDataPin) == HIGH ? 1U : 0U;

    return static_cast<uint8_t>((clock_state << 1U) | data_state);
}

void handle_button_pressed(
    ButtonState& button,
    unsigned long now
) {
    button.pressed_at_milliseconds = now;

    if (button.behavior == ButtonBehavior::ImmediatePress) {
        emit_input_event(button.short_event_id);
    }
}

void handle_button_released(
    const ButtonState& button,
    unsigned long now
) {
    if (button.behavior != ButtonBehavior::ShortLongOnRelease) {
        return;
    }

    const unsigned long held_milliseconds =
        now - button.pressed_at_milliseconds;

    if (
        held_milliseconds >= kLongPressMilliseconds
        && button.long_event_id != nullptr
    ) {
        emit_input_event(button.long_event_id);
        return;
    }

    emit_input_event(button.short_event_id);
}

void poll_buttons(unsigned long now) {
    for (ButtonState& button : buttons) {
        const bool raw_pressed = digitalRead(button.pin) == LOW;

        if (raw_pressed != button.last_raw_pressed) {
            button.last_raw_pressed = raw_pressed;
            button.last_change_milliseconds = now;
        }

        const bool debounce_complete =
            now - button.last_change_milliseconds
            >= kButtonDebounceMilliseconds;

        if (
            !debounce_complete
            || button.stable_pressed == raw_pressed
        ) {
            continue;
        }

        button.stable_pressed = raw_pressed;

        if (button.stable_pressed) {
            handle_button_pressed(button, now);
        } else {
            handle_button_released(button, now);
        }
    }
}

void poll_encoder() {
    // Valid quadrature transitions contribute +1 or -1. Invalid
    // transitions, including most contact bounce, contribute zero.
    static constexpr std::array<int8_t, 16> transition_table{{
         0, -1,  1,  0,
         1,  0,  0, -1,
        -1,  0,  0,  1,
         0,  1, -1,  0,
    }};

    const uint8_t current_state = read_encoder_state();

    if (current_state == previous_encoder_state) {
        return;
    }

    const uint8_t transition_index = static_cast<uint8_t>(
        (previous_encoder_state << 2U) | current_state
    );

    encoder_transition_accumulator = static_cast<int8_t>(
        encoder_transition_accumulator
        + transition_table[transition_index]
    );

    previous_encoder_state = current_state;

    if (
        encoder_transition_accumulator
        >= kEncoderTransitionsPerDetent
    ) {
        encoder_transition_accumulator = 0;
        emit_input_event("encoder-clockwise");
    } else if (
        encoder_transition_accumulator
        <= -kEncoderTransitionsPerDetent
    ) {
        encoder_transition_accumulator = 0;
        emit_input_event("encoder-counterclockwise");
    }
}

void initialize_buttons() {
    const unsigned long now = millis();

    for (ButtonState& button : buttons) {
        pinMode(button.pin, INPUT_PULLUP);

        const bool pressed = digitalRead(button.pin) == LOW;
        button.stable_pressed = pressed;
        button.last_raw_pressed = pressed;
        button.last_change_milliseconds = now;
        button.pressed_at_milliseconds = now;
    }
}

}  // namespace

void setup() {
    Serial.begin(kSerialBaudRate);

    pinMode(kEncoderClockPin, INPUT_PULLUP);
    pinMode(kEncoderDataPin, INPUT_PULLUP);

    boot_session_id = esp_random();

    // Allow the serial connection and input pull-ups to settle before
    // capturing initial states.
    delay(250);

    previous_encoder_state = read_encoder_state();
    initialize_buttons();
}

void loop() {
    const unsigned long now = millis();

    poll_buttons(now);
    poll_encoder();

    delay(1);
}
