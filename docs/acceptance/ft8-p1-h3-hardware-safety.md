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
