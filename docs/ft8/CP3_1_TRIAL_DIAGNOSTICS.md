# CP3.1 FT8 trial: repeatable baseline and limitations

Source: Forge read-only SQLite database, trial started October 11, 2026 UTC, 00:45-02:00. Run `python3 scripts/ft8_cp31_trial_report.py /var/lib/rolling-thunder/forge-contact-sync.db` from the repository root. The script opens with SQLite `mode=ro` and modifies no archive rows.

Observed: 16 attempts (20m: 4; 40m: 12), 109 transmit periods, all join by attempt/QSO UUID; completed: 5, retry exhausted: 10, aborted: 1. These observations reproduce the operator's archived cohort. All displayed power sequences are CAT configured settings, **not RF wattage**. The report includes individual sequences, verified power readbacks, reported SNR, distance when present, and terminal outcome.

### Investigations that remain open

- **WW3QB (20m):** reported received signal -17 dB; twelve emissions, CAT 20,25,30,35,40,45,45,45,45,45,45,45 W; terminal `retry_exhausted`.
- **WW5G (40m):** reported received signal -19 dB; identical twelve-emission CAT power sequence; terminal `retry_exhausted`.
- These are **partial exchange evidence**, not equivalent to zero replies, nor completed QSOs. The attempt summary records an RX report but not precisely which remote reply or acknowledgment was decoded between transmissions. A plateau in CAT settings cannot establish reply timing, minimal working wattage, receiver reachability, or the exact reason the FT8 handshake failed.
- Next instrumentation should append immutable TX message classes, RX decode classes, state transitions, repeat reasons and per-emission policy decisions to the local event/outbox chain; do not modify the existing immutable transmit-period digest or use a backfill that invents historical events.
- Reconstruct historical power, chronology, band, distance and terminal results from existing rows. Record first-actual-reply event and its preceding TX power **only for future attempts** where decoder events can be associated unambiguously.

### Scope and release gate

This commit provides read-only cohort diagnostics. It changes no live services, power policy, CAT, PTT, RF capability, database schema or deployment artifacts. Future PSK-informed recommendations must remain shadow-only until separately approved. Preserve 20 W starting policy, 5 W bounded steps, ceilings, and CAT verification.
