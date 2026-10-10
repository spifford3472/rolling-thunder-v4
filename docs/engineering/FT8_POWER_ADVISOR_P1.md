# FT8-P1 — safety ceilings and recommendation-only advisor

Initial slice adds a configuration-backed per-band power ceiling and a read-only empirical recommendation engine. Adaptive CAT power changes are NOT implemented or enabled; no PSK Reporter network calls are added.

- Baseline 20 W; configured automatic ceilings 10m 30 W, 12m 40 W and 15m 40 W.
- Live CQ selection and inbound response attempt seeds are clamped to band-specific policy before radio preparation.
- Strong observations from three distinct receivers on the same UTC day, at verified matching TX power, permit an advisory 5 W reduction. Weak or missing evidence never automatically increases power.
- Existing per-attempt telemetry records target/start/end/max configured power, but **not independently verified per-15-second transmission power**. That detailed transmission log and reception-time attribution is the next dependency before trustworthy model training.
- The radio CAT interface does not reliably identify physical-control overrides; automated adjustment remains disallowed until manual override behavior is explicitly verified.
- Other-band default ceiling remains 70 W as a legacy compatibility setting, configurable in policy. The first-session 20 W rule applies to the advisor, not the existing distance-based initial-power algorithm on bands outside the specified new ceilings.
- RF exposure limits depend on antenna/vehicle configuration. Do not interpret an advisor output as an RF compliance assessment.

No production deployments or raw XML cleanup in this checkpoint.

## P1.3 local durability checkpoint

For physical FT8 QSO transmissions the executor now reads configured CAT power before keying, records exact UTC keyed intervals, and appends each completed period to `ft8_transmit_period` in the Pi's existing SQLite storage database. Each QSO may contain multiple distinct emission rows. A readback failure is stored as unknown rather than guessed from an RF meter; the value is a *CAT configured setting*, not a calibrated wattage measurement. This is written after PTT release, is local only, and the existing per-QSO bounded in-memory records remain available.

**Still missing:** Crash-proof recording of an emission whose process dies before unkey, explicit operator physical-control override detection, reliable attachment of PSK Reporter observations to a specific emitted period, transfer of individual period records to Forge, and receiver-path calibration. These are rollout blockers for any adaptive power control. No live radio/Forge deployment is authorized by this checkpoint.

## P1.3 second slice — Forge persistence and correlation primitives

The independent `ForgeFT8PeriodRepository` stores individually sequenced emission records, returning an idempotent replay acknowledgement and rejecting changed replays. This is a storage contract and is **not yet connected** to the Forge HTTP endpoint or the Pi sync schedule. The read-only time/frequency attribution function requires an explicitly dial-aligned reception frequency, a unique bounded time match and verified CAT power. Real PSK Reporter records commonly report RF signal frequency rather than dial frequency, so frequency normalization and uncertainty analysis are required before production association. No quantitative reception percentages or automatic power changes are authorized by these primitives.

## P1.3 third slice — opt-in Pi-to-Forge emission delivery (development only)

The FT8 period repository now tracks per-emission acknowledgements independently of source records. An unacknowledged emission remains eligible for retry after connectivity loss or process restart. The existing FT8 performance sync scheduler invokes a bounded period upload pass. Each record uses a stable (QSO UUID, emission sequence) identity and receives an explicit accepted/already_exists response before marking local delivery complete.

The contact-sync application exposes POST /ft8-period and stores immutable observations in the separate Forge emission repository. It validates a bounded strict JSON envelope and idempotency key; mismatched or changed replays are rejected. **The route inherits the existing private-network Forge contact service's access assumptions; it does not implement new bearer-token authentication.** Do not expose this route on a public listener. Upgrade and smoke-test Forge first, then anvilmobile, as older Forge releases do not recognize /ft8-period.

Known rollout gates: review endpoint authentication and access controls; extend network integration tests; ensure persistent pre-key intention / crash-aborted emission state; test physical override and final RF safety boundary; validate PSK frequency attribution (provider RF frequency is not FT8 dial frequency); acceptance test on anvilmobile without transmitting. Adaptive CAT power remains disabled.

## P1.5 — upload credential hardening

The FT8 emission upload route now **fails closed** unless `ROLLING_THUNDER_FT8_PERIOD_TOKEN` is explicitly supplied to the Forge contact-sync process. It rejects missing or incorrect bearer credentials using timing-safe comparison. The Pi client also refuses to send until the token is present in its own environment. **The same dedicated high-entropy token must be provisioned separately to both isolated processes through their protected runtime secrets**, not checked into Git. Ordinary contact and terminal-attempt routes retain their current behavior. This is an application credential in addition to network isolation, not a replacement for WireGuard/firewall controls. No production configuration has been changed.

Safety gates still open: verify environment-variable injection via restricted systemd secrets without exposing tokens to logs; handle abrupt process crash with a durable pre-key intent/outcome; normalize reported PSK RF frequency with known audio offset before receiver correlation; review physical operator override and full transmit-boundary checks. Keep the PR in draft and auto power disabled.
