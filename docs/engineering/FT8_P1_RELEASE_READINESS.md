# FT8-P1 release readiness — PR #255 (draft)

Status: **NOT APPROVED FOR PRODUCTION**. This checklist is a review plan, not permission to deploy or transmit RF.

## Verified in isolated development

- Per-QSO period evidence: pre-PTT uncertain intent, atomic completion, local outbox retry and immutable Forge replay identity.
- Per-period CAT configured-power readback and transmit-side waveform audio base frequency; neither is calibrated RF power/center-frequency measurement.
- Production-wired final pre-PTT policy rejects unknown CAT power, unrecognized band, and power exceeding limits (10 m 30 W, 12 m/15 m 40 W). Other-band legacy maximum can be 70 W; the advisory baseline 20 W does not enforce a universal starting power.
- Authenticated Forge `/ft8-period` with dedicated bearer credential; missing credentials fail closed.
- Existing production PSK-N2 is independent and must not be reconfigured or restarted solely to test FT8-P1.
- New SQLite columns are nullable; historical records remain without invented audio offset. Confirm migrations on *copies* of actual Pi and Forge production databases before change approval.

## Open blockers — no production enablement until separately reviewed

1. Physical PTT release/watchdog under audio hang, radio disconnect, abrupt Pi death, and failed CAT release. Hardware acceptance must be stationary, supervised, with dummy load and explicit operator approval; do **not** run these tests remotely or during driving.
2. Front-panel power settings: CAT readback detects limits but cannot reliably distinguish every operator override within allowed range. Do not enable automatic power adjustment.
3. The FT8 exit path sets 100 W for voice operation; operator must explicitly approve the intended behavior and ensure it cannot operate while PTT remains keyed.
4. PSK Reporter correlation primitive is offline only. Verify true USB dial + base-tone provenance, receiver frequency semantics, timing, ambiguity, and calibration before live joins or ML training.
5. Verify credentials through restricted service environment/systemd credential handling, process identity, logs and firewall/WireGuard isolation without printing actual secret values.
6. Review rollback behavior for additive schema columns, immutable Forge evidence, and deferred uploads; never roll back a live SQLite database over newer evidence.

## Proposed staged validation — approval required

- **Before Forge:** Capture exact SHA, branch/PR checks, service health and backup inventory. Snapshot Forge database and configuration, test schema migration on its isolated copy, and verify credentials without disclosing them. Record current release SHA and service statuses.
- **Forge first:** Install the exact approved SHA through existing deploy helper only after operator approval. Validate contact-sync and `/ft8-period` with synthetic API requests (no PTT), authentication rejection, identical retry, changed replay conflict and persistence. Verify existing contact/Wavelog and PSK-N2 health. If failure, restore previous binaries/config while retaining newer durable evidence; do not blindly restore older DB.
- **Then anvilmobile:** Backup Pi SQLite and runtime configuration; test migration on a copy; deploy only exact approved SHA. Use supervised no-RF tests for UI, receive, restart/retry and logs. Keep transmitting disabled until separate supervised hardware authorization and release review.
- **Rollback:** Revert code/config to recorded SHAs, keep databases and outboxes backed up, and stop new FT8 emission delivery if protocol compatibility is uncertain. Document successful final smoke checks and acknowledgements; preserve uncertain intents.

## Acceptance sign-off fields

- Independent reviewer / review date: **pending**
- CI + full Python/Ruff/mypy/pre-commit + migration/retry tests: **verify at final SHA**
- Forge credential and network isolation check: **pending**
- On-hardware supervised safe-release demonstration: **pending approval**
- 100 W voice restore behavior: **pending operator decision**
- Operator merge approval: **not granted**
- Operator Forge deployment approval: **not granted**
- Operator anvilmobile deployment approval: **not granted**
