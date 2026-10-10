# FT8 first RF dummy-load acceptance — HOLD until hardware gate passes

Production FT8 transmit remains DISABLED. This protocol is planning and inspection only;
never toggle `ft8.transmit.enabled` or key PTT as part of the preflight.

## Required physical gate (stationary, operator supervised)

- Car parked, radio accessible, operator observing FT-891 TX/RX indicator, and a
  reachable radio POWER control to terminate unexpected TX. No driving.
- Confirm FT-891 RF output physically routed to an appropriately rated 50-ohm
  dummy load (MFJ-260C), not antenna. Check connectors, ventilation and SWR.
- Set and verify 5 W RF power on radio and via CAT; verify applicable per-band
  software ceiling; any unreadable CAT setting blocks keying.
- Set and verify FT-891 independent TX timeout if the model/mode supports it;
  never assume the software CAT watchdog is independent.
- Confirm both the FT8 transmit audio output and radio PTT device; test audio
  routing without PTT before enabling any transmit configuration.
- Take a timestamped backup of YAML and all production SQLite databases, record
  exact source SHA, verify stable radio/service operation and test frequency.
- Ensure physical radio power cutoff is immediately reachable, and define abort:
  power down the radio if transmission fails to stop; do NOT rely on UI/USB.

## Fail closed and no-key checks

- Existing receive-only service and FT8 decoder healthy.
- Safety-alarm physical acknowledgement and 1-3-1 tested with simulation.
- No-QSO policy checks (unknown power, over-cap, wrong frequency/mode) must
  refuse PTT. Use mocks/no-RF to verify denial paths, never probe by RF.
- Before any first RF emission, obtain separate authorization for an explicitly
  defined short bounded test, not automated CQ or QSO traffic.

## Controlled RF test proposal (not authorization)

1. Record dummy-load connection, 5 W radio/CAT setting, fixed frequency,
   radio status before PTT, and a hard abort plan.
2. Only after explicit key-down authorization, conduct one brief bounded
   transmission with continuous observation of physical FT-891 TX indicator.
3. Confirm return to RX by direct observation, CAT log, and power meter;
   stop immediately if any indication is uncertain. Do not deliberately jam CAT.
4. Restore FT8 transmit-disabled setting, restart only as authorized, verify
   disabled config, inspect TX intent/period records and evidence backups.

## Known software limitations at review

- H4 alarm is visual; requires running Pi/screen. A successful CAT TX0 write is
  not physical RX proof.
- Timer/watchdog shares the CAT operation lock/transport with normal release.
- Executor `cancel_test()`, `cancel_qso()` and `close()` call PTT cancel/close;
  separately review their failure handling before RF acceptance.
- Software unlock requires operator attestation; there is no independent RF
  feedback or autonomous hard-kill demonstrated.
