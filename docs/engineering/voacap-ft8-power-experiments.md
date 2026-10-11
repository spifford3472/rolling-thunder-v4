# FT8 prospective power experiments — scientific qualification protocol (design + safe contract)

**Not enabled, not deployed, not wired into Pi/CAT/PTT/UI.** Phase C5.1 now
includes `forge_ft8_power_experiment.py`, a deterministic HMAC-based
pre-choice allocation contract only. It cannot change RF settings. An operator
setting `enabled: true` alone does not authorize experiments.

## Research question and why randomization is needed

The goal is the *least configured transmit wattage that reliably reaches the
selected CQ station*, not the highest possible QSO rate. VOACAP modeled
SNR (dB-Hz), a decoder report (dB), and a received reply are different
measurements. Passive observational data cannot identify the causal advantage
of a lower wattage because band, geography, path, time, congestion, propagation,
remote CQ selection and retry attempts differ.

Once validated prospective, independently grouped holdout data are available,
compare a fixed **20 W control** with **15 W or another separately reviewed,
lower bounded experimental arm**. The default allocation is OFF and enrolls
0%. If a future authorized experiment is activated, cap randomized enrollment
at 10% of otherwise eligible attempts and split enrolled attempts equally
between 20 W and the lower arm using a fixed, secret, audited allocation seed.
This avoids operators or models selecting only easy QSOs for the lower arm.
A versioned experimental protocol, pre-registered outcome definitions,
sample-size/power analysis and stopping rules are required before activating.
The HMAC only creates a *shadow proposed assignment* today; it is not an RF
command and does not prove a 50/50 distribution in a small sample.

## Required frozen fields for a live future pilot

An independent, immutable decision record needs the QSO UUID, explicitly
captured operator CQ authorization/choice UTC, forecast availability at choice,
immutable provider input/version, calibration version, stratification key
(band, rough path class, UTC slot, baseline signal/propagation class), policy
digest, randomization seed ID (never secret), assigned arm, selection
probability, remote target/callsign-group hash, chosen real-time power
readback, later power changes, attempts/retries, QSO result/report, local and
remote grid uncertainty and field/simulated provenance.

The current HMAC prototype is **not stratified** and **not a validated live
trial allocator**. Build and test balanced within-segment allocation, exact
eligibility and assignment logging before any pilot. Existing FT8 attempt events
lack a frozen CQ-choice UTC and must not be silently backfilled from PTT/start
or Forge delivery time.

## Outcome and inference rules

- Primary outcome: successful reciprocal FT8 exchange under a pre-registered,
  bounded number of TX slots; capture no-answer and terminal faults distinctly.
- Analyze intention-to-treat assignments even if an operator interrupts,
  declines, or power-readback fails; separately report per-protocol results.
- Busy targets, QRM, unavailable target, aborts and no decoder report are
  appropriately censored/uncertain, not automatically RF failures.
- Split by forward UTC time and callsign/QSO group, preserve held-out regions,
  and quantify per-segment coverage, error bars, drift and missingness.
- Require confidence-bounded *noninferiority* against 20 W, not just a point
  estimate or arbitrary success-rate delta. Select and register tolerable
  difference and error bounds before collection, include sequential monitoring,
  multiple-comparison correction and minimum sample sizes. No fabricated
  power-saving percentage or predictive success probability.
- Model changes, drift, insufficient/expired holdouts and increase in missed
  contacts suspend the learned policy immediately.

## Operator notification, driving and safety

A future approved Pi control integration must show **FT8 POWER TEST —
assigned NN W** clearly before transmission and throughout the QSO, with
an unambiguous *cancel/decline test* control that is safe while driving.
The operator can keep 20 W, stop the QSO, or abandon a test without affecting
normal radio operation or eligibility for future contacts. Do not use tests
while driving unless their UI was independently safety-reviewed for hands-free
operation and explicitly authorized. An experiment is opt-in, reversible and
never uses unattended PTT. CAT power readback, SWR, ALC, min/max settings,
temperature and hardware ownership interlocks remain authoritative.
Immediately disable experiments when the operator selects off, the panel
cannot show the indicator, radio state is uncertain, Forge unavailable,
anomaly limits are exceeded, or the experimentation quota is reached.
Never deliberately use greater than the operator-set cap. Never treat
assignment output from Forge as permission to transmit.

## One-year unattended qualification and explanation

The C5.1 service needs a *separate future* immutable evidence adapter and
calibration worker. When all pre-registered gates pass, archive a signed or
content-hashed human-readable qualification certificate:
model ID, forecast source and immutable hash, first/last eligible timestamps,
independent observations, eligible/denominator counts by arm/band/region,
unanswered/censored/excluded counts, effective sample sizes, grouped
forward holdout boundaries, confidence intervals, noninferiority test,
failure/fallback conditions, operator cap, code/config SHAs, review protocol
version, randomness seed ID, automatic activation UTC and *reason codes*.
Recompute validity on schedule and append every transition without
silently revising an old certificate. If no valid certificate exists, never
claim the feature turned on. When it eventually is eligible, show a simple
operator-facing explanation such as: "Learned power qualified for 40 m /
this path: 2,3xx real attempts, 3x held-out days, control-vs-test confidence
interval ...; baseline 20 W; use 15 W only in approved conditions."
These counts are examples, not observations.

The numeric threshold configuration is *necessary but not sufficient*.
Threshold crossing alone cannot activate experiments, or power control.
This contract leaves `apply_allowed=false` and `may_transmit=false` even
for hypothetical complete policies. No standalone code in C5.1 can override
radio authority; the future reviewed Pi adapter and opt-in remain separate.

## Immutable qualification certificate schema (C5.1)

`forge_ft8_qualification.py` now defines a versioned, immutable
`QualificationCertificate` with exact input, evaluation, policy and code
hashes, evidence/holdout UTC intervals, number of independent forecast inputs
and transmitted attempts, control/test group sizes, censoring/missingness,
per-segment counts, calibration metrics, noninferiority confidence bound and
plain-English qualification explanation. Unqualified certificates retain
`result=insufficient_evidence`. A syntactically qualified certificate is
rejected without explicitly validated prospective provenance, grouped
holdouts, model stability, verified radio power, registered protocol, actual
control/experiment comparison, completed 30-day/200-attempt forward window
and independent minimum totals. This is a *contract and verifier*, not an
operational or statistical analysis producer. Its example minimum totals
remain policy-dependent in the live gate: the service must also compare
against the currently loaded policy and raised thresholds, never just these
schema minimums. Certificates still cannot actuate RF under any circumstances.

## Pre-registered offline two-arm noninferiority calculation

`forge_ft8_power_statistics.py` now implements a conservative offline
two-arm comparison for externally verified prospectively assigned real FT8
attempt observations. Each observation requires frozen choice and forecast
availability UTC, independently identified forecast families, QSO and
callsign-group identities, immutable source/assignment digests, 20 W control or
sub-20 W randomized assignment, and actual power readback. It refuses
retrospective, synthetic, missing-power, misordered and unverified rows.
Busy/fault/abort are censored explicitly instead of being labeled propagation
failures. No-answer is a separate failure outcome under a registered bounded
protocol, not a proxy for a received SNR report.

The confidence test uses a Bonferroni-conservative combination of
two-sided 97.5% per-arm Wilson intervals, giving at least approximately 95%
simultaneous interval coverage for binomial trials under independent
randomization. It considers the lower bound on (test exchange rate minus
20 W exchange rate); a result below the pre-registered 5 percentage point
illustrative margin fails. Neither the confidence level nor the margin is
automatically an approved operating protocol: preregister a clinically/
operationally acceptable margin and collect enough *independent* grouped
samples for it. Correct for within-callsign/path/time correlation in the
future full statistical approval. The current per-arm minimum 100 is only a
developer fixture; production eligibility must also pass the separate full
policy, holdout days/attempts, data-quality and per-segment tests. A model
probability calibration and energy-optimality claim require additional
science beyond this causal arm comparison.

**Critical temporal dependency:** Real controlled lower-power trials must be
collected under a separately authorized, visible, opt-in study before a
scientifically honest claim that 15 W performs noninferiorly to 20 W is
possible. Passive 20 W-only logs and C4 forecasts cannot establish this
counterfactual, regardless of how many months elapse. The program must never
auto-start experiments or apply reduced power solely because its baseline
sample-count thresholds have been met.

## FT8 immutable event v2 — prospective operator selection UTC

The Pi's existing FT8 selection seed captures `selected_at_utc` before CAT
radio preparation. Development now forwards that timestamp through the
terminal performance record into a **new v2 FT8 analytics event**. Legacy
v1 event serialization expressly omits the new field, preserving unchanged
historical payload identity and avoiding reinterpretation of AA4NP.

If the seed is unavailable or does not belong to the terminal QSO UUID,
the event remains v1 with missing choice metadata and is ineligible for
prospective C5 joins. Preparation failure carries the seed selection time,
but remains an excluded/nontransmitted record for propagation learning.
A v2 event is valid only if its frozen selection UTC is no later than
QSO start; future Forge C5 pairing must use that time, not RX/first PTT or
Forge receipt. This does not initiate power experiments or authorize RF.
It is additive in the feature branch only, and requires Pi-to-Forge staged
compatibility/deployment acceptance before live telemetry can accumulate.
