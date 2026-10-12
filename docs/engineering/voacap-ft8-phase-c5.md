# VOACAP / FT8 Phase C5 — scientific shadow power advisory

Status: **implemented offline, Forge-only, non-actuating and uncomposed**. C5 adds
versioned evidence pairing, descriptive evaluation, an explanatory shadow advisory,
and configuration-driven readiness. It adds no process, listener, scheduler,
provider adapter, Pi client, UI, CQ reordering, CAT/PTT call, power command,
production migration, deployment, or RF authority. The operational FT8 start-power
baseline remains 20 W and the existing sorting/retry ladder is unchanged.

## Ownership and safety boundary

`forge_ft8_power_advisor.py` owns immutable scientific contracts and offline
evaluation. `forge_ft8_power_advisor_config.py` owns schema-validated YAML and
atomic in-process policy publication. Both are presentation-neutral Forge
capabilities. Neither is composed by a runtime.

Every advisory hardcodes `shadow_only=true`, `apply_allowed=false`, and
`may_transmit=false`. `current_operational_baseline_watts` is exactly 20. Suggested
power is null unless a separately reviewed scientific experiment explicitly marks
it approved; empirical completion probability is null unless calibration is
separately approved. Even then the contract remains non-actuating and an operator
power cap is an absolute ceiling. `armed_when_ready` means readiness calculation
only in C5.

## Immutable evidence and strict as-of pairing

Schema-1 forecast evidence records generation, availability, forecast, frozen
choice and environmental observation/capture times in UTC. Naive timestamps fail
validation. Only audited `field_observed`, `pre_choice`, prospectively available
evidence with `available_at_utc <= choice_at_utc` can be training-eligible. Late,
backfill, post-attempt, retrospective, synthetic and unknown-provenance evidence is
reason-coded and excluded. For C4 NOAA forecast input, capture must not be later than
model generation and the `predicted_ssn` target month must match the modeled month;
an unknown NOAA issue time stays unknown rather than being inferred from capture.

Grid4 and grid6 precision must match the actual locator and carry explicit
uncertainty. The contract separately stores the model's band-center frequency
(for example 7.2 MHz for 40 m) and the actual FT8 dial frequency (7.074 MHz).
VOACAP modeled SNR is named `modeled_snr_db_hz`; decoder reports are
`decoder_snr_db`. No conversion or equality is implied.

Frozen audit identities are:

- AA4NP source UUID `938620bb-b4ff-40b2-9493-081b56bb038c`, SHA-256
  `9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab`;
- retrospective UUID `1aa647cd-ea95-43db-821f-67b16e87e2b1`, SHA-256
  `74264c1f26ed164257f0cfe836771a6b0d0cffccba35185735677de57fc5d877`;
- synthetic exclusions `9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339` and
  `1d99bba6-0f38-4069-a706-77f9a90d4a8c`.

The two audited identities reject changed hashes. The AA4NP field observation can
remain `field_observed` while its later modeled availability is retrospective and
training-ineligible. C5 never modifies or seeds production provenance records.

## Offline descriptive evaluation

The evaluator accepts a versioned, hashed candidate registry and immutable hashed
specification. Inputs and results also receive canonical SHA-256 identities and may
be stored in an additive exact-replay SQLite artifact repository. Changed content
under the same artifact identity conflicts; unrelated legacy tables are preserved.

Evaluation is chronological and forward-only. Callsign groups seen before the
holdout are excluded from the holdout; attempt UUID and QSO group are deduplicated.
Forecast independence is counted by canonical forecast-input identity, so four
hourly cells reused from one monthly VOACAP request are not four independent model
inputs. Busy/unknown outcomes are censored. Non-transmitted, aborted, equipment,
timing, missing, late, retrospective and provenance-invalid rows are not comparable.
No-answer and completed real transmitted attempts remain descriptive outcome
evidence; no-answer is not silently turned into a propagation failure.

Results publish reason-coded `not_comparable` or `insufficient_evidence`, holdout
days/attempts, segment counts, source/model drift, coverage and missingness. They do
not manufacture success probabilities or minimum power. Any synthetic demo sets
`simulated=true` and cannot become real field evidence.

## Shadow advisory contract

The immutable advisory carries:

- candidate IDs, policy/evidence/evaluation digests and contract versions;
- TTL, choice/generation times, model/service versions and operating segment;
- forecast age, independent attempt/input counts and missingness/reason codes;
- optional modeled-circuit and ranking suitability, separately labeled;
- nullable empirical probability and suggested power under the approval rules;
- the operator cap and fixed 20-W current baseline.

It never calls a provider and cannot invoke Pi, CAT, PTT, QSO authorization, live CQ
sorting, logging, Wavelog or contact synchronization.

## Readiness policy and state machine

`config/ft8-power-advisor.example.yaml` is strict and rejects unknown keys. Defaults
are:

- mode `off`, `shadow`, or `armed_when_ready`;
- 20,000 independent forecast inputs;
- 2,000 real independent transmitted attempts;
- 100 attempts per operating segment;
- 30 forward-holdout days and 200 holdout attempts;
- calibration error no greater than 10 percentage points;
- held-out noninferiority versus 20 W required;
- fresh prospective forecast and valid as-of provenance required;
- exact pinned model version;
- fallback start power exactly 20 W.

Reload validates the complete candidate before replacing the immutable current
policy. Invalid files leave the old snapshot intact. Raising thresholds immediately
returns readiness to collecting. Qualification requires consecutive successful
evaluations (two by default) to avoid flapping, but every disqualification is
immediate.

States are `OFF`, `INSUFFICIENT_EVIDENCE/COLLECTING`, `SHADOW_READY`,
`ELIGIBLE_FOR_FUTURE_ACTUATION` and `DEGRADED/SUSPENDED`. The final state is only a
scientific readiness label. Config off, Forge unreachable, stale/missing forecast,
bad as-of provenance, missing/mismatched version, source drift, latency, segment,
hardware, statistics, calibration or noninferiority failure closes the gate.
Crossing sample totals alone is insufficient. Every evaluation appends an immutable
reason-coded transition with policy/evidence digests.

## C4 pilot plan — separately approved and still unscheduled

C5 does not authorize C4. A future C4 pilot needs separate owner approval for each
of: exact release, copied-database migration rehearsal, process installation,
scheduler enablement, provider egress, bounded smoke, ongoing pilot and any later C5
shadow composition. Keep the existing C3 worker `voacap_enabled=false` unless its
own separately approved gate is executed.

Before a pilot:

1. Take SQLite-consistent backups of every affected store, restore them to new
   non-production paths, and verify row counts, `integrity_check`,
   `foreign_key_check`, provenance seeds and rollback.
2. Pin the provider/service/model versions, target inventory, SSN source, origin,
   grid uncertainty, 20-W model reference and privacy/retention policy.
3. Start with one disposable database, one target/band/hour, concurrency one,
   maximum one call, timeout at most ten seconds and response cap at most 1 MB.
   Provider 429/500, timeout, malformed/oversized response or missing cell stops the
   smoke with no retry.
4. For any wider pilot, retain C4's per-cycle/per-day calls, lease/retry, storage and
   backlog bounds. Establish explicit daily/monthly request and storage budgets
   before activation; never infer a budget from provider tolerance.
5. Monitor provider-call ledger, ready/unavailable/skipped/failed/missed counts,
   timing class, age, leases, retries, version drift, response/storage size and
   database integrity. Alert without triggering Pi/radio behavior.
6. Rollback by stopping/disabling only the candidate Forge component and restoring
   all gates false. Preserve immutable evidence for diagnosis. Restore a tested
   backup only if data rollback is explicitly required; never delete production
   tables or use a checkout as a database backup.

No production provider, NOAA/SSN HTTP, Pi, RF, service or database acceptance was
performed by C5.

## Offline acceptance

Tests cover naive UTC rejection, strict timing/provenance, immutable audit hashes,
grid4/grid6 and frequency/unit separation, censored/non-comparable outcomes,
independent attempt/QSO/model-input deduplication, grouped forward holdouts,
missing/stale/version/drift/segment/latency/calibration failures, policy off and
raised thresholds, hysteresis, armed-readiness non-actuation, operator cap,
simulated labeling, atomic reload, and additive immutable SQLite artifacts.
