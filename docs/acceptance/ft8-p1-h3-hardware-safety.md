# FT8-P1-H3: CAT failure review and hardware acceptance plan

Status: **software tests only; live FT8 TX disabled**. This document is not authorization to key a radio.

## Hardware-free evidence

- CAT TX0 timeout leaves PTT state uncertain/retryable; disconnect must not silently close CAT and claim a normal shutdown.
- After TX0 failure, an additional TX1 is not issued until release has succeeded.
- TX1 write failure followed by failed compensating TX0 retains uncertain PTT state (H2).
- Normal release retains watchdog coverage until successful TX0 (H1).
- CAT serial port configures read and write timeouts; the watchdog uses the same CAT operation lock/transport, and is **not independent**.

## Remaining hazards and limitations

1. The CAT TX0 *write* completing is **not proof of physical receive**; the transport does not query PTT feedback in this path.
2. A jammed synchronous CAT call or lock may block both normal release and the timer thread's release.
3. A Pi crash, USB disconnect, radio CAT failure or lost power to the controller can leave radio state unknown. No separate hardware PTT kill has been demonstrated.
4. On an uncertain state, disable further transmission and require direct operator intervention and confirmed receive. Do not treat a UI status flag or an SQLite journal as RF proof.

## Preconditions for separate stationary dummy-load authorization

- Operator present with clear view of FT-891 TX/RX indication and a physical means to stop TX; vehicle parked; no road use.
- Appropriately rated 50-ohm dummy load on radio RF output; inspect coax, connectors, ventilation and SWR.
- Dedicated release/recovery procedure agreed in advance. Disconnect PTT/control or turn off radio manually if transmission persists.
- Verify test-specific config, exact merged code, backup, healthy database and no production contact logging pollution.
- Limit power and key-down duration conservatively; verify menu power and actual CAT readback on each tested band before any PTT.
- Confirm transmit refuses over-ceiling power, invalid band and unknown CAT power **without PTT**.
- Separately observe normal completion, playback interruption, abort, and recovery; no deliberately stuck PTT or controller power-loss simulation while transmitting without independent hardware cutoff.
- Inspect immutable intent/period records and Forge delivery behavior, with no duplicate records after retry.
- Record measured observations, deviations and evidence. Restore receive-only configuration and verify service and RX behavior afterward.

## Gate

Do not enable production FT8 transmit merely because simulated tests or CI pass. Hardware acceptance and any RF test require explicit operator approval and fail-safe assessment.

## H4 uncertain-transmit operator alarm (software prototype)

A failed CAT PTT release raises a prominent yellow dashboard warning with the
instruction **POWER DOWN RADIO MANUALLY**, accompanied by a repeating klaxon on
the configured ALSA default output. **The operator's voice-cancel/discard control
is the sole acknowledgment path.** USB disappearance does NOT acknowledge or
clear the warning. Verify that the voice-cancel physical input is actually mapped
to `discard` on the deployed installation before deploying H4.

The visual warning and klaxon end after voice-cancel acknowledgment, but FT8 TX
remains inhibited in the alarm state for the rest of that runtime. Only a future,
separately reviewed recovery procedure may restore authority. The `default`
ALSA sink is not guaranteed to be HDMI on every Pi: confirm HDMI audio routing
under stationary no-RF simulation before accepting this feature. Failure of the
UI, speakers, Pi power, or the audio subsystem can prevent the warning entirely;
these are notification aids, not a hard RF cutoff.

## H4 FT8-only deliberate unlock sequence

After manually powering down any radio believed to be stuck in TX, the operator
acknowledges the yellow alarm using physical voice cancel (mapped to DISCARD).
On the FT8 page a green panel, 26pt bold white type, instructs: "Press command
buttons in this order Command 1, Command 3, Command 1 to unlock". The
physical command actions must be delivered exactly in order; wrong order resets
the sequence. While locked, they must not invoke normal FT8 panel functions.
Completion clears the in-memory lock only after this explicit operator action.
A button sequence cannot prove RF is absent, and it never bypasses FT8 power,
frequency, radio connection, timing or other transmit gates. Never execute
the sequence before independently checking that the radio is in receive and
recovering the radio if needed. Repeated failures require stopping the radio.
