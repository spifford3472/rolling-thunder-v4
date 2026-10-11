# VOACAP / FT8 Phase C4 — bounded pre-choice baseline sampling

Status: **implemented offline, disabled and uncomposed**. C4 adds a reusable Forge
domain/repository/service boundary for deterministic historical and pre-choice
sampling. It adds no daemon, provider HTTP adapter, timer, production configuration,
Pi code, UI, ranking, ML advisor, power control, CAT/PTT path, migration invocation,
or deployment asset. The three typed activation gates default false. Tests inject a
fake provider and never contact VOACAP or NOAA.

## Gate 0 audit (2026-10-11)

| Area | Read-only evidence | Gap / C4 disposition |
| --- | --- | --- |
| Branch | `feature/voacap-ft8-phase-c4-20261011` began at verified `origin/main` `24762a12580e5827db8b616539be37981cbcdb54`. | Correct development base; no production action. |
| Installed QSO worker | Installed release `7e68d53ee92ed2d774092cf2e2eca009507af504` is the C2 merge. Journal records show the worker active with ingestion true and VOACAP false after 09:11 local. | C3 is merged in source but not installed. C4 does not deploy or alter this worker. |
| C2/C3 | C2 owns read-only retrospective coverage and immutable correlation fixes. C3 owns only copied-database, fake-only AA4NP replay. | Neither provides a scheduled baseline. C4 remains a separate store and service boundary. |
| Provider | `voacap-service` source SHA `63d15f305020a352a23a6169a324cc4dde9c659c`; Uvicorn is configured on `0.0.0.0:8787`. | All-interface binding is a flagged exposure. C4 does not repair or reconfigure the separate repository/service. |
| October 11 smoke | Journal proves `GET /version` returned 200 at 14:26:54 local and the immediately following `POST /api/v1/summary` returned 500. No exception detail or response body was logged. | **Cause unconfirmed.** Source permits at least NOAA SSN retrieval failure and wrapper/subprocess failure. Do not select one without evidence; no retry was made. Live acceptance remains **BLOCKED**. |
| Scientific identity | AA4NP UUID `938620bb-b4ff-40b2-9493-081b56bb038c`, immutable payload SHA `9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab`, 2026-10-11 11 UTC, EM79xm → EL98 grid4, 7074000-Hz dial, 1906-Hz audio offset, twelve periods 20/25/30/35 then 40 W ×8, remote report −15 and local report +12 in `ft8_decoder_db`. | Existing manually audited `field_observed` provenance is required and unchanged. Decoder dB, modeled dB-Hz, configured/model watts, actual RF watts, modeled reliability and QSO success remain distinct. |
| Exclusions | UUIDs `9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339` and `1d99bba6-0f38-4069-a706-77f9a90d4a8c` are documented synthetic/test evidence. | C4 tests freeze both identities. Unknown provenance is not field observed and no C4 baseline row is training-eligible. |

## C4 contract

`BaselinePlan` is immutable by UUID and canonical SHA-256. A new inventory,
assumption, model or service version is a child plan with an explicit parent; old
plans and results are never rewritten. It freezes an actual origin grid6, origin
uncertainty, a curated/versioned list of target grid4/grid6 cells with region IDs and
uncertainty, exactly bands 40/30/20/17/15/12/10 m, UTC hours 00/06/12/18, and one
20-W model reference. Unsupported rows terminate as explicit skips.

Every slot retains `forecast_for_utc`, `scheduled_at_utc`, `generated_at_utc`, and a
truthful timing class: `pre_choice`, `late`, `backfill`, or `missed`. The environment
snapshot includes SSN value, source/version, observation time and capture time.
Missing SSN or source identity fails validation; no NOAA lookup is available here.

The canonical monthly request includes the frozen circuit, calendar month, one band,
20-W reference, FT8 mode, SSN identity and plan model/service versions. It excludes
hour because the v1 provider response contains all hourly cells. Its SHA-256 keys one
immutable response, response SHA-256 and generation time. Thus 00/06/12/18 slots for
the same target/band/month reuse one provider response while each slot validates its
own band/hour cell. This is response reuse, not a claim that four QSOs share an
outcome.

SQLite migration is additive/forward-only. Foreign keys protect plan lineage and
slots; arbitrary legacy tables remain untouched. Slot identity is unique and a
terminal slot cannot be completed again. `BEGIN IMMEDIATE`, identified leases,
expiry recovery, capped attempts, deterministic jittered exponential retry, daily
and per-cycle provider budgets, response/storage caps, and restart backlog-to-missed
handling bound work. The application service has a nonblocking single-worker lock;
the plan contract fixes concurrency at one. Provider attempts and outcomes are
durably ledgered, including failures.

`BaselineConfig()` leaves process, scheduler and provider gates false. No runtime
composition currently constructs this service, so repository release alone cannot
schedule or send a request.

## Diagnostics and retention

`BaselineRepository.diagnostics` opens SQLite read-only with `query_only=ON` and
emits deterministic schema-1 JSON. Coverage is grouped by plan/version, UTC day,
band, hour and region plus status/timing; retention reports oldest/newest forecast;
budget reports provider-call and activity counts. It contains no callsigns, attempt
payloads or exact coordinates. `training_eligible` is always false. C4 does not prune
data; a future retention operation needs an approved policy, backup/restore test and
separate implementation.

## Bounded future real-provider smoke runbook — BLOCKED

This is a review artifact, not current authorization. Do not run it until the owner
separately approves provider egress and the provider exposure/root-cause questions.

1. Record exact Rolling Thunder and provider SHAs, provider bind/firewall scope,
   service/model version, operator, UTC window and rollback point.
2. Keep scheduler disabled. Use a new disposable database, one approved origin,
   one target, one supported band, one UTC cell, fixed 20 W and a manually supplied
   SSN whose source/version/observation/capture timestamps are recorded. This avoids
   NOAA egress.
3. Set concurrency one, maximum calls one, timeout at most 10 seconds and response
   cap at most 1 MB. Capture sanitized HTTP status, duration, canonical request and
   response SHA-256; do not log credentials or raw protected data.
4. On 429, 500, timeout, malformed/oversized response, missing SSN/version, or a
   missing requested band/hour cell, stop. Do not retry during the smoke window.
5. Verify the single result is immutable, a repeated slot makes zero provider calls,
   SQLite integrity/foreign keys pass, and diagnostics label timing/status correctly.
6. Restore every gate false and retain the disposable evidence. Do not enable the
   scheduler, migrate production, restart services, change provider configuration,
   deploy, touch the Pi, or transmit RF under this runbook.

Live real-provider acceptance: **BLOCKED / not performed**.

## C5 read-only shadow advisory handoff

C5 now implements an offline Forge-only contract accepting a frozen choice
timestamp, explicit provenance and prospective forecast evidence available at or
before that choice. Its versioned response returns separate modeled-circuit/ranking
suitability fields, coverage/age/status, model/service identities, uncertainty and
hardcoded `shadow_only=true`, `apply_allowed=false`, `may_transmit=false`. Missing,
late, backfill, retrospective, failed, unsupported and stale evidence remain explicit
and fail closed for readiness.

C5 must not reorder the production UI, claim calibrated QSO probability, recommend
or command power, invoke CAT/PTT, authorize FT8, create contacts, alter Wavelog, or
query a provider. Evaluation must be time-blocked and region-held-out, with selection
bias and busy-target censoring addressed, before any later operator-visible proposal.
No Pi interface or runtime composition is added. See `voacap-ft8-phase-c5.md` for
the implemented contract, evaluation and readiness-only policy.

## Offline acceptance

The fake-only suite covers immutable identity and forks, grid4/grid6 precision,
00/06/12/18 rollover cells, monthly response dedup, disabled and unsupported skips,
HTTP-500/429-equivalent failures, timeout, malformed/missing-cell, missing SSN,
version mismatch, oversized response, call/storage bounds, concurrency, lease expiry,
restart/backlog/outage, legacy-table preservation, diagnostics non-mutation, AA4NP
identity, both synthetic exclusions and absence of a network implementation.
