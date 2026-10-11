# VOACAP / FT8 Phase B — durable attempt ledger and correlation

Status: implemented in source, disabled for network/provider delivery by default.
No production migration, service activation, provider request, deployment, or RF
test is part of this change.

Phase C1 subsequently adds a separate UUID-keyed synthetic/test exclusion and
conservative provenance diagnostics without changing this phase's raw event or
replay contract. See `voacap-ft8-phase-c.md`.

## Ownership and data flow

The Pi remains authoritative for FT8 observations. After the existing
`FT8PerformanceAttempt` is durable, `FT8AttemptLedgerRepository` snapshots that
terminal attempt together with the matching rows owned by
`FT8TransmitPeriodRepository`. This happens for completed, no-answer,
busy-target exhaustion, operator abort, interruption, execution fault, and
preparation fault. A failed analytics capture is logged and cannot change the
terminal result, contact, RF state, or Wavelog behavior.

```text
existing terminal result
  -> existing durable performance attempt
  -> existing durable per-emission evidence
  -> local immutable FT8AttemptEvent (always local when FT8 is enabled)
  -> optional disabled store-forward scheduler
  -> authenticated Forge attempt inbox (no provider work in request)
  -> optional disabled leased VOACAP worker
  -> immutable input/run/link history
  -> authenticated read-only per-attempt diagnostics
```

Successful contacts retain the stable contact/attempt UUID only when normal
contact durability actually succeeded. Non-success attempts never create a
`Contact` and never enter contact sync or Wavelog.

## Attempt event contract

`FT8AttemptEvent` schema 1 preserves source creation/start/end UTC; frozen local
grid and paired coordinates; decoded remote grid and its original four- or
six-character precision; explicit terminal classification and source reason;
directional reports in `ft8_decoder_db`; and each emitted period with its verified
CAT configured power and waveform offset from the existing transmit-period owner.
Unknown values remain null. Raw FT-891 meter values are not configured watts.

## Local store-forward contract

The attempt ledger is append-only by UUID and canonical payload SHA-256. Exact
replay is accepted; changed replay conflicts. Delivery uses identified bounded
leases, bounded batches, exponential retry, maximum attempts, and dead-letter
state. Source evidence remains after delivery/dead-letter. SQLite uses WAL,
foreign keys, a busy timeout, and due indexes. No network or retry sleep occurs on
the terminal/UI thread.

`ft8.attempt_delivery.enabled` defaults false. Enabling it requires an absolute
private/TLS endpoint and protected `ROLLING_THUNDER_FT8_ATTEMPT_TOKEN`.

## Forge ingestion and worker

The existing disabled propagation-QSO listener additionally routes
`POST /api/v1/ft8-attempts` and authenticated
`GET /api/v1/ft8-attempts/{attempt_uuid}`. Authentication and the enabled gate
precede bounded body reads. The idempotency header must equal the event UUID.
Acknowledgement means durable inbox acceptance, not provider success.

The separate inbox preserves payload hashes, worker identities, leases, retries,
dead letters, and mixed-release coexistence. The worker records canonical model
inputs, append-only runs, and attempt links.

## Scientific semantics

Every model input hash includes schema, direction, event UTC hour, grid precision
and center assumption, frequency/band, mode, period identity, power/provenance,
nullable antenna/noise/solar/model settings, and service contract version. Each
transmitted period with verified power gets a local-to-remote input. Unknown remote
power makes reverse direction explicitly skipped, not 0 W.

Phase B links are `retrospective`: real calculation availability is retained and
never presented as knowledge available before station choice. Diagnostics state
that modeled-day circuit reliability is not next-QSO probability, VOACAP dB-Hz is
not FT8 decoder dB, missing is not zero, and retrospective is not pre-choice.
Legacy contact VOACAP rows and performance placeholders remain unchanged.

## Migration and rollback

Before any separately approved installation:

1. Record the exact release SHA and stop only the candidate service through the
   approved workflow.
2. Take SQLite-consistent backups of the Pi database and both Forge propagation
   databases, including WAL state via SQLite backup or a checkpointed stopped copy.
3. Restore to non-production paths and open each repository once.
4. Compare every legacy table's pre/post row count; run `PRAGMA integrity_check`,
   `PRAGMA foreign_key_check`, and verify the new stores use WAL.
5. Test legacy/new exact replay, conflicting replay, lease expiry, retry and restart.
6. Install only the exact reviewed SHA with all new gates false. Ingestion and
   provider egress require separate approvals.

Operational rollback is stop/disable plus selecting the recorded prior exact SHA.
Additive tables may remain unread by old code. If data rollback is required,
restore the pre-migration backups; never delete tables from a live database or use
a Git checkout as a durable-state backup.

## Operator acceptance (no RF required)

1. Confirm prior FT8 receive/QSO/contact/Wavelog behavior is unchanged.
2. With fakes, create success, no-answer, busy, abort, interruption and fault.
3. Verify one local row per UUID, no fake non-success contact, and frozen UTC/grid/
   coordinates across movement and UTC rollover.
4. Change configured power between emissions and verify each period; unreadable is
   null.
5. Disconnect Forge, queue/restart/reconnect, and verify bounded eventual replay.
6. Verify changed UUID replay conflicts and final expired lease dead-letters.
7. Only with separate provider approval, verify direction, full hashes, missing
   reverse power, dB-Hz labeling and retrospective/training-ineligible diagnostics.
8. Run integrity/foreign-key checks and a representative 90-day-volume load.

Live RF, production migration, restart, deployment, or provider smoke testing
requires separate explicit authorization.
