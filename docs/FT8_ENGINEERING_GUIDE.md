# Rolling Thunder FT8 Engineering / Design Guide

Status: CP9.1 engineering-guide source. This document is intended to become the basis for a printable design/engineering guide after final production acceptance.

## Design Intent

The native FT8 subsystem is built around three separate concerns:

1. **CQ eligibility/activity** — which stations are allowed to appear in the operator browser.
2. **Attempt history/presentation** — how an already-eligible CQ row is decorated based on current-day prior attempts.
3. **QSO execution/telemetry** — the bounded state machine, radio authority, logging, and machine-analysis records.

Keeping these separate prevents decoded non-CQ traffic or historical attempt data from manufacturing a station that never called CQ.

## CQ Eligibility State

`FT8CQActivityManager` is authoritative for browser membership.

A callsign enters the activity map only from a normalized CQ decode. If a non-CQ decode is received for a callsign that is not already present, it is ignored for browser-membership purposes.

For an existing CQ candidate:
- `last_cq` records the most recent CQ period;
- `last_any_decode` records the most recent decode of any type;
- `cq_count` counts distinct CQ periods;
- non-CQ traffic can mark the station active;
- six periods without any traffic expire the row;
- insertion order is preserved, so new CQs append at the bottom.

## CQ Presentation State

Base presentation for an eligible CQ is:

1. fresh CQ (CQ count 1-2) -> yellow;
2. repeated CQ (CQ count 3+) -> white;
3. recent non-CQ activity from an existing CQ candidate -> gray.

Persistent same-day attempt history has higher presentation precedence:

1. failed/error/retry-exhausted/preparation-failed -> red + `!`;
2. operator aborted -> blue + `■`;
3. otherwise active non-CQ -> gray;
4. otherwise repeated CQ -> white;
5. otherwise fresh CQ -> yellow.

The selected row retains this callsign color and adds an independent high-contrast selection border/background.

POTA is independent metadata: an explicit POTA CQ token adds the tree indicator and does not change eligibility or attempt outcome.

## Attempt History

Attempt history is keyed by:
- normalized callsign;
- band;
- UTC date.

It is derived from the durable FT8 performance outbox rather than a second ad-hoc persistence database.

On application startup, the attempt-history service rebuilds the current UTC day's state from stored performance payloads. New terminal performance records update the in-memory history after durable local storage.

Outcome mapping:
- `COMPLETED` clears failed/aborted presentation history because the normal worked-today subsystem suppresses the successful callsign/band;
- `ABORTED` -> blue;
- `RETRY_EXHAUSTED`, `ERROR`, and `PREPARATION_FAILED` -> red.

Attempt history never inserts a callsign into CQ activity.

At the UTC date boundary, prior-day visual history expires.

## Successful Worked-Today Suppression

`FT8WorkedTodayService` derives successful callsign/band suppression from normal completed FT8 contacts.

A completed callsign/band is hidden for the remainder of the UTC date. Different bands remain independent. This survives application restart because completed contacts are durable.

## Terminal Result Reset

The QSO coordinator and QSO-start controller have separate responsibilities.

When a terminal QSO result is acknowledged and ownership returns to the CQ browser:
- terminal coordinator ownership is released;
- QSO-start presentation state resets to IDLE;
- stale activity/error/attempt-seed data is cleared;
- the next station receives a fresh attempt ID and preparation sequence.

This prevents a prior FAILED banner from contaminating a later station attempt.

## Machine-Analysis Telemetry

Successful, failed, aborted, retry-exhausted, and preparation-failed attempts are stored separately from the normal contact log.

The telemetry model includes structured UTC timing, callsign, band/frequency, local/remote Maidenhead grids, distance, signal reports/SNR, target power, available radio meter values (power/SWR/ALC), outcome, state, and terminal reason.

Successful QSO:
- normal contact exactly once;
- telemetry exactly once.

Non-successful attempt:
- no normal contact;
- telemetry exactly once.

The outbox is idempotent by stable attempt UUID and synchronizes to Forge for future AI/statistical analysis.

## Safety Boundaries

- UI widgets do not own CAT/PTT/audio authority.
- One explicit selected CQ authorizes one bounded QSO.
- No auto-next station.
- Radio preparation fails closed.
- CAT loss fails closed.
- Receive-only configuration creates no physical transmit authority.
- Local Maidenhead grid is frozen for the duration of one authorized QSO.
- Persistent continuous receive architecture remains independent of transmit execution.
