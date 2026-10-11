# VOACAP / FT8 Phase C — provenance safety and retrospective coverage

Status: **Phases C1, C2 and C3 implemented offline only.** C1 adds an auditable
synthetic/test exclusion boundary. C2 adds a scoped, deterministic, read-only
coverage artifact over existing retrospective attempt/VOACAP history and closes the
retry-exhaustion directional-status gap in the existing worker. C3 adds one exact,
copied-database historical replay with a deterministic fake provider and versioned
audit report. No slice implements or activates scheduled baseline sampling, enables
a live provider, migrates production data, changes ranking/training, deploys, or
authorizes RF.

## C1 provenance contract

Phase B's immutable `FT8AttemptEvent` JSON, payload SHA-256, UUID replay decision,
and inbox retention remain authoritative and unchanged. Analytics provenance is a
separate Forge-owned table keyed by attempt UUID. A documented synthetic/test UUID
is completed by the leased worker without creating model inputs, VOACAP requests,
prediction runs, or training links. Read-only diagnostics expose the classification,
reason, evidence reference/date, and both eligibility decisions.

Two acceptance-test UUIDs are seeded as excluded:
`9ad2f0c2-ed0e-4ba7-8b03-732d8aa8c339`, the documented non-transmitted FT8-P1
API acceptance record in `FT8_P1_FORGE_STAGE_CUTOVER.md`, and
`1d99bba6-0f38-4069-a706-77f9a90d4a8c`, the synthetic authenticated-ingestion
record identified in the October 11 Phase B production acceptance checkpoint.
Neither represents observed RF evidence. Each seed is immutable: initialization fails
if an existing row disagrees. No callsign or on-air QSO is inferred from either record.

Absence from the provenance table means `unknown`, not field-observed. Unknown
attempts retain Phase B VOACAP processing eligibility for compatibility, but are
training-ineligible. A future pre-choice calculation cannot become training-eligible
unless separate audited provenance explicitly establishes `field_observed`. Known
synthetic/test attempts are ineligible for both VOACAP processing and training.
Retrospective links remain training-ineligible regardless of provenance.

This design deliberately does not rewrite or delete an already-created historical
VOACAP run. Before any production migration, the coverage report must identify any
excluded UUID that already has model history; reconciliation must preserve that
history and add an exclusion annotation rather than destroy evidence.

At the C1 checkpoint, UUID `938620bb-b4ff-40b2-9493-081b56bb038c` remained
provenance `unknown`; its identity and the associated AA4NP callsign alone were not
evidence. Before C3, a separate operator audit created and verified the production
`field_observed` provenance entry. That entry already exists outside this source
change. C3 requires it and preserves its exact reason/reference/date; it must not
automatically insert, replace, or reclassify it. Retrospective C3 results remain
training-ineligible despite the field classification.

## C2 scoped retrospective coverage contract

`build_retrospective_coverage_report` opens a declared attempt-inbox snapshot and
attempt-history snapshot with SQLite read-only/query-only connections. Its caller
must provide the exact release identifier, generation UTC, half-open query window,
and stable backup/fingerprint identifiers. The reusable result is versioned JSON-
serializable data; it does not claim leases, initialize/migrate a database, call
VOACAP, or expose callsigns, raw payloads, or exact coordinates.

The scoped artifact reports separate event, transmitted-period, and modeled-input
denominators. It partitions events by UTC day, band, terminal classification,
provenance, remote-grid precision, and queue state; reports missing/present event
coverage; partitions existing immutable inputs, runs, relations, versions, and
training eligibility; and publishes expected-versus-stored input/terminal-run,
unknown-remote-power reverse-skip, unlinked-input/run, and excluded-after-history
reconciliation counts. Known synthetic/test attempts are not expected model work.
Missing values remain `missing`, never zero or failure.

The worker records deterministic missing-input directions before any provider
attempt. Unknown remote power therefore always produces an immutable reverse
`skipped` run even when the forward request exhausts its retry budget. Four-/six-
character Maidenhead inputs are normalized and structurally validated; malformed or
unsupported grids remain missing. A successful response lacking the existing
adapter's requested UTC-hour/band values is `unavailable`, not `ready`. Availability
cannot precede request time, and no provider response field is synthesized.
Each transmitted-period input uses that period's UTC start, frequency-derived band,
exact frequency, and only power explicitly marked as verified configured CAT
readback. A declared model service version is bound into canonical input identity
before provider work, so terminal replay is checked before egress. A later declared
service version or changed modeled assumption therefore creates a distinct append-only
input/run; it never overwrites or suppresses the historical version. When no version
is available before the call, a matching durable terminal input suppresses eager
re-query; legacy unversioned hashes remain stable.

Generation fails closed when required schemas are absent, foreign keys fail, seeded
exclusion evidence changes, an inbox UUID/hash disagrees with its validated immutable
event, a model-input hash/identity disagrees with its canonical value, history names
an attempt absent from the inbox snapshot, link/input identities disagree, enum
values or raw response digests are invalid, or a training-eligible link violates
field-provenance, ready-run, pre-choice, and availability-cutoff invariants.
Persistence now also requires a ready result with parsed modeled values before any
new pre-choice link can be training-eligible.

C2 is deliberately not the complete field coverage report required by baseline gate
3 below. It does not emit CSV drill-down, suppress/coarsen small cells, inventory
independent replay/conflict counters, partition every denominator by every dimension,
or compute daily/7/30/90-day or seasonal comparison views. Those additions require
privacy-threshold and output-retention approval. No C2 result is training evidence or
authorization to enable the baseline scheduler/provider.

## C3 audited historical replay contract

C3 is intentionally restricted to the audited AA4NP event:

- attempt UUID `938620bb-b4ff-40b2-9493-081b56bb038c`;
- immutable canonical event SHA-256
  `9de70a6c8d131500cefa580465bfe1033a87f558e3c655fac511443320288cab`;
- frozen path `EM79xm` to `EL98`, 40 m dial frequency `7074000` Hz, and transmit
  audio offset `1906` Hz;
- twelve transmitted periods with CAT-verified configured watts
  `20, 25, 30, 35, 40, 40, 40, 40, 40, 40, 40, 40`;
- remote report of local `-15` and local report of remote `+12`, both exchange-level
  `ft8_decoder_db` observations.

Those reports are not VOACAP dB-Hz, are not per-period measurements, and do not
establish measured RF watts or a causal power threshold. Period `frequency_hz` is
the exact dial frequency; audio offset is retained separately and is not added to
the VOACAP band/frequency identity.

`run_audited_historical_replay` opens the declared inbox and history copies using
read-only/query-only SQLite connections, validates integrity/foreign keys, both C1
exclusions, the exact UUID/SHA and detailed event semantics, and the already-present
`field_observed` row. It then uses SQLite backup to create a new history output and
writes only to that copy. Source logical hashes and the complete target queue/lease
state are verified unchanged after replay. Existing output paths are refused.

The injected `DeterministicFakeVoacapProvider` accepts only a schema-1 local fixture
with a declared model service version. Fixture identity is year, month, selected UTC
hour, band, mode and configured watts. The request itself retains the real summary
shape (`tx_grid`, `rx_grid`, year, month, one band, watts, mode and UTC timezone);
hour selects a returned `best_band_by_hour` cell. Seconds never become model inputs.
Calls are capped at twelve for this UUID. Missing required inputs and fixture-unsupported
identities are `skipped`; a response without the requested modeled cell is
`unavailable`; deterministic timeout/unavailability is `failed`.

Each input binds the fake model service version before execution. Exact terminal
replay is executed a second time and must make zero extra calls. A distinct model
version produces new append-only input/run/link rows while preserving earlier
hashes and responses. Every link is `retrospective` and training-ineligible.

`HistoricalReplayReport` schema 1 publishes release/time identity, source/output
logical database hashes, fixture SHA-256, exact event SHA, preserved provenance,
call cap/count/dedup proof, appended row counts, input and response hashes, explicit
statuses and scientific semantic notes. It embeds the existing C2 coverage result.
It contains no raw attempt payload, exact coordinates, socket endpoint, provider
credential, scheduler, activation, UI, ranking, CAT, PTT or RF authority.

The `rolling-thunder-forge-ft8-historical-replay` CLI requires explicit
`copied-fixture-only` acknowledgement, new history/report output paths, an explicit
timezone-aware replay timestamp and release identifier, and the local fake fixture.
It composes no HTTP/network client and is not a production service.

## Phase C baseline activation gates

All gates remain closed after C3. Before implementing or enabling the daily baseline
pilot described in Phase A:

1. Review and approve the exact release SHA, service account, private network path,
   VOACAP contract/version, timeout, concurrency and daily request budget.
2. Back up the inbox and history databases with SQLite-consistent methods; restore
   them to non-production paths; verify legacy row counts, `integrity_check`,
   `foreign_key_check`, WAL mode, seeded provenance, and rollback.
3. Produce the field coverage report below from a read-only database snapshot. Every
   known synthetic/test UUID must be excluded; unknown provenance must be reported
   separately and remain training-ineligible.
4. Approve the origin model explicitly: frozen actual grid6, or a named coarse mobile
   region with documented representative-grid method. Do not use a country centroid
   or silently substitute current GPS for historical position.
5. Approve deterministic target-grid inventory, versions, supported bands
   (40/30/20/17/15/12/10 m), UTC slots (00/06/12/18), reference power, antenna/noise/
   solar assumptions, skip reasons, retry policy, storage retention, and budget
   accounting.
6. Demonstrate offline scheduling determinism, duplicate-slot idempotency, missed-slot
   recording, provider-outage behavior, restart recovery, and immutable append-only
   results using a fake provider.
7. Keep process, baseline scheduler and provider-egress gates independently false in
   shipped configuration. Enabling each gate, a bounded provider smoke test, and any
   production migration or restart require separate owner approval.
8. Confirm that baseline results have no UI, ranking, CAT power, QSO authorization,
   contact, Wavelog, PSK, or transmit authority. Phase D evaluation and any training
   use require later review and explicit activation.

## Field coverage report design

The report is a deterministic, read-only artifact over a declared database snapshot
and exact code/config version. It must publish its query window, generation UTC,
source database fingerprints or backup identifiers, schema versions, exclusion-set
version, and row-count reconciliation. It must not call VOACAP or mutate leases.

Use the raw inbox attempt UUID as the event denominator. Also provide separate
transmitted-period and modeled-direction denominators; never mix them. Partition each
denominator by UTC day, band, terminal classification, provenance classification,
remote-grid precision, and processing state. Required counts and rates are:

- total immutable events, exact replays/conflicts when independently available, and
  inbox pending/processing/retry/completed/dead-letter states;
- documented synthetic/test exclusions, provenance-unknown events, audited field
  events, and any exclusion added after a historical model run;
- present/absent local grid, paired coordinates, remote grid and its stated source,
  dial frequency/band, transmitted periods, configured-power readback and source,
  directional decoder reports, start/end/source-created UTC, terminal outcome/reason,
  and busy-extension count;
- remote grid4 versus grid6, transmitted periods with distinct power inputs, reverse
  direction skipped for unknown remote power, and every other structured skip reason;
- VOACAP ready/unavailable/skipped/failed runs by service version and input-contract
  version, plus queue retry/dead-letter coverage and orphan input/run/link checks;
- training-eligible links, with an invariant that synthetic/test, unknown-provenance,
  retrospective, post-attempt, missing-input and failed-provider rows contribute zero.

Missing values are reported as missing, never zero or failure. Percentages must show
integer numerator and denominator. Cells smaller than the approved privacy threshold
must be suppressed or coarsened without changing totals. Report generation must fail
closed on UUID count mismatch, invalid provenance values, changed seeded evidence,
foreign-key errors, or a supposedly eligible row that violates an invariant.

Suggested machine-readable outputs are versioned JSON plus CSV detail containing only
the minimum fields needed to reproduce aggregates. Callsigns, raw payloads and exact
coordinates are excluded from the aggregate report by default; access to a protected
diagnostic drill-down remains a separate authorization.

## C1/C2/C3 offline acceptance

- Exact synthetic UUID: raw payload/hash and exact replay remain unchanged; changed
  replay still conflicts; provider calls, inputs, runs and links are zero.
- Unknown UUID: Phase B correlation remains available, provenance is explicitly
  unknown, and every link remains training-ineligible.
- AA4NP UUID `938620bb-b4ff-40b2-9493-081b56bb038c` requires the independently
  created `field_observed` row; C3 never seeds it, and retrospective links remain
  training-ineligible.
- Mixed-release database: legacy tables and rows remain, the additive provenance
  table is seeded exactly once, and SQLite integrity/foreign-key checks pass.
- C2: declared snapshot/window metadata is retained; denominators and partitions
  reconcile; sensitive fields are absent; logical database contents remain unchanged;
  UUID/hash, response-digest, provenance seed and training-invariant corruption fail
  closed; exhausted forward retries still retain the reverse unknown-power skip;
  terminal replay causes zero additional provider calls, while distinct declared
  model versions append distinct immutable results.
- C3: exact AA4NP UUID/SHA and existing field provenance are required without
  seeding; copied source hashes and active lease state do not change; twelve forward
  period calls plus one reverse missing-power skip reconcile through C2; a terminal
  second pass makes zero calls; a new fake model version appends; malformed,
  timeout, unavailable and unsupported fake outcomes remain bounded and explicit.
- Full repository Ruff, strict MyPy, pytest and `git diff --check` pass before commit.

No live provider, production database, deployed service, operator identity claim, or
RF evidence is part of this acceptance.
