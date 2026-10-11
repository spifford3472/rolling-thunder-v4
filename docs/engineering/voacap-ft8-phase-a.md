# VOACAP / FT8 Intelligence — Phase A: audited architecture and schema decision record

Status: **design-only / review gate**. Baseline: `origin/main` at `e09bc31e5ba4aa66d2abf4219e801099a2f59d59` on 2026-10-11. No runtime code, RF behavior, database migration, service change, or production configuration was authorized.

## Evidence and deployed observations

| Area | As built | Phase A finding / required next gate |
|---|---|---|
| VOACAP HTTP engine | Forge `voacap-service.service` was **active**, `GET http://127.0.0.1:8787/version` returned `{"service":"voacap-service","version":"0.3.0"}`. ExecStart invokes Uvicorn `app.main:app --host 0.0.0.0 --port 8787`. | Verify real `POST /api/v1/summary` schema, network access controls, versioned assumptions and measured runtime budgets. Binding to all interfaces requires security review. This read-only audit did **not** exercise POST. |
| Environmental history | `rolling-thunder-forge-propagation.service` was active on Forge; separate history/storage under `forge_propagation_history.py`. | Being active does not confirm VOACAP per-QSO enablement. Do not conflate environmental collection with correlation. |
| Existing VOACAP adapter | `VoacapSummaryClient.predict(contact)`, `forge_propagation_collectors.py`, GET /version then POST /api/v1/summary; uses frozen `my_grid6`, remote `grid`, contact UTC year/month, resolved band, TX watts, mode and UTC timezone; extracts one UTC-hour cell. Missing grid/power/mode returns no prediction. | Needs explicit direction, true units, assumptions, complete canonical model input, as-of timing, and missing/status reasons. |
| Existing prediction history | `VoacapPrediction`, `save_voacap`, `qso_voacap_prediction` in `forge_propagation_history.py` retain raw request/response, service version, captured time, band-hour MUF/reliability/rating/SNR. | Preserve as legacy history; introduce append-only input-key/versioned records, not mutable authoritative duplicate rows. |
| Successful QSO | `completed_qso_producer.py` post-commit durable destination states; Forge completed-QSO authenticated inbox and leased/retried worker. `forge_propagation_qso_worker_config.py` defaults `enabled`, `ingestion_enabled`, `voacap_enabled` false. | Retain unchanged Wavelog and exactly-once contact contracts. Confirm actual installed service/config flags before enabling; no changes made. |
| Failed/busy/aborted attempts | FT8 attempt performance exists, including `busy_extension_attempts` (Forge performance schema 3), but completed-QSO producer requires a successful terminal contact. | A new durable attempt-event producer/inbox is mandatory. Failure must not create a fabricated `Contact` or Wavelog QSO. |
| Performance placeholders | `ft8/performance.py` exposes nullable `voacap_probability`, `voacap_predicted_snr_db`, `voacap_path`; `forge_ft8_performance.py` serializes those fields. | Keep nullable and backward-compatible. Do not populate ambiguous `probability` as individual QSO success. Link to versioned predictions; deprecate ambiguous interpretation after consumer audit. |
| Ranking / PSK | FT8 ranking cache/browsing and optional directional PSK evidence already exist, with fail-neutral stale/outage tests. | Record precise as-of and geographic coverage for future shadow ranking; no ranking/power change in Phase A. Some existing guide descriptions of these seams are stale. |
| Mobile origin | Shared immutable QSO position/grid convention and 4-/6-character handling; Wavelog station routing uses frozen QSO data. | Prefer recorded contact start position and six-character grid; do not recompute using latest GPS. A 4-character remote grid remains coarse with labeled center/uncertainty. |
| anvilmobile runtime | Direct `geoff@anvilmobile` SSH was denied; `rollingdeploy` dedicated deployment key disallows arbitrary commands. | **Installed Pi SHA not confirmed by this audit.** Use an operator-approved read-only diagnostic through an allowed access route; do not bypass deploy-key restrictions. |

## Data model decisions (proposed; no migration executed)

**Forge is authoritative for predictions and regional model history; Pi is authoritative for local FT8 attempt observations and contacts.** Once locally durable, observation events are delivered asynchronously and independently of logging, PTT and PSK. Never put HTTP/provider traffic on the receive, decoder, UI, CAT or Wavelog critical path.

1. `ft8_attempt_observation_v1`: `attempt_uuid` primary identity, optional `contact_uuid` only when a genuine completed contact exists, `source_event_created_utc`, `started_at_utc`, `ended_at_utc`, `received_at_utc`, terminal phase/reason and outcome classification (`completed`, `no_answer`, `busy_target`, `aborted`, `equipment_fault`, `timing_fault`, `unknown`). Include remote callsign and remote reported grid **with original precision/provenance**, band/frequency/FT8 mode, frozen local GPS latitude/longitude and grid6/grid4, antenna/radio configuration identity, power per FT8 TX period and initial/final/max verified configured watts, transmitted and received SNR reports with direction and decoder units, busy extension count, and optional PSK evidence provenance/coverage. Unknown values remain null; never collapse into measured zeros.
2. `ft8_attempt_tx_period_v1`: composite `(attempt_uuid, period_sequence)`, UTC times, commanded/readback power with source, phase, transmission/disposition and fault flags. Preserve existing FT8 transmit-period telemetry authority; avoid duplicative on-Pi streams without an explicit adapter.
3. `voacap_prediction_input_v1`: immutable `input_uuid`, deterministic canonical SHA-256 of model-relevant fields and schema version, direction (`us_to_dx` or `dx_to_us`), coordinate/grid provenance and uncertainty, frozen event UTC year/month/hour (not query hour), target grid precision/center assumption, frequency/band, power, antenna orientation/gain/noise, mode, model solar index assumptions, service/model/config versions, model path if supported, and raw request. Inputs unavailable to the actual service must be recorded as assumptions or null—not falsely claimed to be model inputs.
4. `voacap_prediction_run_v1`: append-only `prediction_uuid`, `input_uuid`, `requested_at_utc`, `available_at_utc`, `captured_at_utc`, `status` = pending/ready/unavailable/skipped/failed, `retry_count`, structured failure reason, response/raw JSON, parsed band and extraction UTC hour, modeled circuit direction, typed MUF, reliability definition/fraction, SNR with **declared units**, service version and raw response digest. A revised provider or backfill creates a new immutable run/version; never rewrite a historical prediction.
5. `voacap_attempt_link_v1`: unique `(attempt_uuid, direction, model_input_hash, prediction_uuid)`, relation `pre_choice` / `post_attempt` / `retrospective`, associated as-of cutoff and training eligibility. Only `available_at_utc <= choice_at_utc` qualifies as information available for prospective ranking; retrospective model calculations are never presented as prior knowledge.
6. `voacap_baseline_sample_v1` (Phase C reserved design): `sample_uuid`, cadence/coverage version, scheduled UTC slot, actual origin assumption (home/grid6 or named mobile region), target representative grid, band, reference power, antenna/model inputs, prediction UUID, status/skip reason and budget accounting; indexed by origin/region/band/hour/date/version.

Use foreign keys and indexes on attempt UUID, contact UUID, input hash, status/due retry, model/version, destination grid/region, UTC band/hour and sampling slot. Distinguish `observation_event_utc`, `received_at_utc`, and `prediction_available_at_utc` in storage and APIs. Exact replay by same UUID+payload hash is idempotent; changed content under that UUID is an explicit conflict. No duplicated 'authoritative' VOACAP result lives in performance placeholders: those become optional read-model projections sourced from the immutable prediction UUID.

**Schema rollout**: backward-compatible, forward-only, disabled-by-default Forge migrations with a backed-up live-like SQLite copy and integrity/foreign-key/count checks; restore and dry-run procedures required before approval. Never modify live database in Phase A. Retain raw prediction and observation history for a configurable multiyear period (pilot default proposed: 5 years, subject to storage/privacy/operator sign-off); apply explicit archival snapshots and tested backup/restore before pruning. Preserve legacy data and its provenance; retrospective backfill must be tagged `retrospective` with actual calculation time, not manufactured historical availability.

## Scientific semantics

- VOACAP monthly/hourly circuit reliability estimates the **fraction of modeled days** meeting its specified SNR requirement. It is **not** the probability of completing the next FT8 exchange. An absent prediction is not 0% reliability.
- VOACAP modeled SNR can be reported in **dB-Hz** while FT8 decoder signal reports are in their own receiver convention. Preserve raw names/units and direction; no numerical equality, conversion or training target without validated documented mapping and provider contract review.
- Remote Maidenhead grid4 provides area-level location, not a point-position claim. Explicit center-point estimates and grid-cell uncertainty; grid6 is more precise but likewise not an exact antenna position. Mobile path inputs use the **frozen attempt** snapshot.
- Distinguish `us_to_dx` and `dx_to_us`; asymmetrical power, noise, antenna and reports matter. Do not treat remote decoded reception, unobserved PSK reports, or busy-target interruption as an unbiased propagation label.
- Service or PSK outages, disabled gates, clock faults and missing location/power are separate status outcomes. Never treat missing evidence as a negative report.

## Subsequent implementation gates (not part of Phase A PR)

**B — event ledger and per-attempt correlation:** independent bounded Pi-to-Forge durable attempt delivery; authenticated inbox; migration; worker queue/cache/full input hash; retry/lease/dead-letter; read-only correlated attempt diagnostics. Keep successful-QSO/Wavelog flow unchanged. Fakes must cover success/failure/busy/abort, moving GPS, grid4/6, model outage, duplicate/conflicting replay, UTC turnover, power-period changes, direction, and exact as-of timestamps.

**C — daily baseline:** disabled Forge-owned sampling pilot at UTC 00/06/12/18 over provider-supported bands 40/30/20/17/15/12/10 m with deterministic diverse representative grids, budget, clear home/mobile origin assumptions, provenance, skipped-slot coverage and immutable history. No country-centroid false precision. Produce daily, 7/30/90-day and season/hour comparison views with qualified interpretation.

**D — shadow evaluation:** time-blocked/region-held-out, leakage-free observational assessment; calibration/Brier/log loss, coverage, top-K gains vs current distance+PSK ordering; selection-bias accounting and busy-target censoring. Publish separate modeled circuit suitability and **empirically calibrated QSO completion probability**. No UI ranking change without measured superiority and operator approval.

**E — power advisor:** recommend-only from frozen power history, credible PSK coverage and provider sensitivity; obey operator 20 W/day intent if deployed/verified, bounded physical CAT limits and manual overrides. No automatic power command without separate authorization.

## Required checks before Phase B authorization

- Confirm exact Pi runtime SHA, installed Forge worker flags and VOACAP POST response schema with authenticated and authorized diagnostics; assess `0.0.0.0:8787` exposure.
- Resolve stale engineering descriptions of producer composition and live PSK-ranking integration in a focused contract change.
- Test migration on restored representative databases: `PRAGMA integrity_check`, `PRAGMA foreign_key_check`, preserved row counts, UUID cross-links, rollback/recovery.
- Maintain Ruff, MyPy, pytest, pre-commit, clean diff, bounded load and no degradation to FT8 decoding, timing, TX authority, QSO sync or offline operations.
- Phase A acceptance is **design review only**. No merge, production migration, service restart, RF test, or deployment has been approved.

## Acceptance questions at this gate

1. Historical reproducibility: **designed, not implemented**. Existing raw request/response and version partially support it; missing complete immutable input/as-of/direction/unit contract must be added.
2. Non-success attempts without artificial propagation failures: **designed, not implemented** via independent observation ledger and categorical outcomes.
3. Long-lived QSO and regional series: **planned**; current VOACAP QSO history exists, scheduled baseline does not.
4. Prediction known at ranking time: **not yet established**; timestamped as-of links and shadow evaluation are required.
5. FT8/Wavelog independence: existing separation is designed and protected; Phase A makes **no behavior changes**.
