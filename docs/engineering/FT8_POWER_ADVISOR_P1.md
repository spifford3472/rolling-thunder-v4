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
