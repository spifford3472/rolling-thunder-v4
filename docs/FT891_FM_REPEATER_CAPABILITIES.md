# FT-891 six-meter FM repeater CAT capability

Checkpoint #168 establishes a typed, receive/configuration-only FT-891 capability for the later repeater execution workflow. It deliberately does **not** change the repeater panel, Active/All behavior, encoder actions, or the two-press workflow owned by #169.

## Safety boundary

This capability uses only the FT-891 Enhanced CAT interface already owned by `Ft891Radio`.

It does not add or expose PTT, MOX, keying, tuner, RF power, voice, digital transmit, or unattended-transmit authority. The FT-891 Standard COM port remains outside this capability.

Unsupported requests are rejected during preflight before any repeater-specific CAT mutation. A failure after a supported transaction has begun is reported as a radio/verification failure; success is never fabricated.

## Official CAT operations

The software codecs are based on the official Yaesu FT-891 CAT Operation Reference (Yaesu document 1707-B, Japanese edition; command definitions are language-independent).

| Purpose | CAT operation | Verified reference behavior |
| --- | --- | --- |
| Operating context | `IF;` | `IF` field P7 reports `0` VFO, `1` memory, `2` memory tune, `5` PMS |
| VFO-A frequency | `FA#########;`, `FA;` | Existing project capability; exact frequency read-back |
| FM mode | `MD04;`, `MD0;` | Existing project capability; exact mode read-back |
| Repeater shift | `OS0x;`, `OS0;` | `x=0` simplex, `1` plus, `2` minus; documented for FM |
| 50 MHz offset | `EX0905xxxx;`, `EX0905;` | 0-4000 kHz, 10 kHz steps |
| CTCSS tone | `CN00nnn;`, `CN00;` | One CTCSS tone index, `000`-`049` |
| CTCSS behavior | `CT0x;`, `CT0;` | `x=0` off, `1` encode/decode, `2` encode |

The implementation keeps these opcodes inside `ft891_cat.py` and exposes typed values to the radio adapter. UI/controllers do not receive raw CAT strings.

## Typed capability contract

`FmRepeaterConfigurationRequest` describes only the operator-requested radio state:

- selected repeater RX frequency
- shift direction (`minus`, `simplex`, `plus`)
- absolute offset in hertz
- optional RX CTCSS tone
- optional TX CTCSS tone

`Ft891Radio.configure_fm_repeater()` returns `FmRepeaterConfigurationOutcome` with either:

- `configured`, including the resulting `RadioState`, or
- `unsupported_manual_handoff`, including a typed unsupported reason and an operator-facing handoff message.

The capability does not decide how #169 displays, filters, stages, or acknowledges an unsupported repeater.

## CTCSS representation boundary

The official CAT interface exposes one CTCSS tone selection (`CN00nnn`) plus a shared CTCSS mode (`CT0x`). It does not expose independent RX-tone and TX-tone registers.

The typed preflight therefore uses this exact policy:

| Requested tones | FT-891 representation | Result |
| --- | --- | --- |
| RX none / TX none | CTCSS off | supported |
| RX none / TX tone A | tone A + encode-only | supported |
| RX tone A / TX tone A | tone A + encode/decode | supported |
| RX tone A / TX none | cannot preserve receive-only CTCSS without also encoding | unsupported/manual handoff |
| RX tone A / TX tone B | independent tones not representable | unsupported/manual handoff |

A supplied tone must match one of the 50 Yaesu CTCSS values exactly. The code does not round or substitute a nearby tone.

## Offset representation boundary

Menu `0905 RPT SHIFT 50MHz` represents 0 through 4000 kHz in 10 kHz increments. Requests outside 0-4,000,000 Hz or not divisible by 10,000 Hz are rejected during preflight.

The request model additionally requires simplex to use zero offset and plus/minus to use a non-zero offset.

## Ordered safe sequence

For a representable request, the adapter performs one serialized transaction under the existing radio operation lock:

1. require a connected radio and refuse operation if the known state is transmitting;
2. establish the existing six-meter context through the accepted memory `010` handoff (`MC010` verification then `MA`);
3. read `IF` and require authoritative VFO operating context before exact tuning;
4. set the selected repeater RX frequency on VFO-A and verify `FA` read-back;
5. set FM and verify `MD0` read-back;
6. set shift direction and verify `OS0` read-back;
7. set the 50 MHz offset and verify `EX0905` read-back;
8. when a tone is required, set it and verify `CN00` read-back;
9. set the required CTCSS behavior and verify `CT0` read-back.

A mismatch at any verification point stops subsequent steps and raises `RadioVerificationError`.

The operation lock is an `RLock` so this transaction can safely reuse the adapter's already-locked band/frequency/mode methods while still preventing polling or another radio operation from interleaving with the repeater transaction.

## Six-meter context truthfulness

The project already treats the installed FT-891 memory-to-VFO band handoff as best-effort context rather than authoritative operator-visible band state. Checkpoint #168 does not change that boundary.

After the memory `010` handoff, `IF` must prove VFO operating context before exact VFO-A configuration proceeds. When the transaction began outside the known six-meter state, the successful outcome sets `manual_band_confirmation_required=True`; this preserves the accepted operator-confirmation handoff rather than claiming more CAT authority than has been proven.

## Automated proof

Fake-transport tests cover:

- exact `IF`, `OS`, `EX0905`, `CN`, and `CT` serialization/parsing;
- the full deterministic command sequence for encode-only, encode/decode, and CTCSS-off requests;
- preflight rejection with zero CAT mutation for unsupported band, tone, offset range, and offset step;
- explicit rejection of RX-only and differing RX/TX CTCSS requirements;
- stop-on-failed-read-back behavior at VFO context, shift, offset, and tone verification points;
- concurrency protection so radio polling cannot interleave with the atomic repeater transaction;
- regression coverage for the existing radio operations.

## Real-radio bench acceptance

**Accepted on the installed FT-891 on 2026-08-11 EDT using branch commit `1b682462a0f051e4e1ad1b0a6708218b938ec93a`.**

The bench test used only the Enhanced CAT interface at the project's accepted 38400-baud 8N2 settings. Rolling Thunder was stopped cleanly before the test so no second process competed for the CAT device. The Standard COM interface remained unopened before, during, and after the test.

Observed acceptance results:

1. Connected successfully through the Enhanced CAT port; initial state read back as 14.237010 MHz USB.
2. The accepted memory `010` handoff copied the 6 m context to VFO-A and read back 50.100000 MHz USB.
3. `IF;` reported `vfo` after the memory-to-VFO handoff.
4. FM mode set and read back successfully.
5. `OS00`, `OS01`, and `OS02` each read back correctly as simplex, plus, and minus respectively.
6. `EX0905` set to the representative 1.000 MHz offset and read back exactly as 1,000,000 Hz.
7. `CN00` selected 131.8 Hz and read it back exactly.
8. `CT00`, `CT01`, and `CT02` each read back correctly as off, encode/decode, and encode-only.
9. One full typed supported repeater request configured 53.050000 MHz FM, minus shift, 1.000 MHz offset, and 131.8 Hz TX CTCSS. The typed result was `configured` and the resulting state read back 53.050000 MHz FM.
10. No PTT, MOX, keying, tuner, RF-power, voice, digital-transmit, or unattended-transmit operation was invoked by the acceptance script.
11. The Standard COM port remained unopened after the test.
12. The temporary worktree was removed and the original Rolling Thunder UI process restarted successfully after acceptance.

This completes the mandatory physical-radio acceptance required by checkpoint #168 for the newly claimed FT-891 repeater configuration operations.

## Handoff to #169

Checkpoint #169 may consume the typed `FmRepeaterConfigurableRadio` capability and its outcome. It must preserve the unsupported/manual-handoff result and the `manual_band_confirmation_required` flag. Decisions about panel presentation, Active/All filtering, staging, confirmation, and physical-control execution remain #169 work.
