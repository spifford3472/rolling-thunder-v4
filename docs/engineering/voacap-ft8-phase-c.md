# VOACAP / FT8 Phase C — C1 provenance safety and baseline gates

Status: **Phase C1 implemented offline only.** This slice adds an auditable
synthetic/test exclusion boundary and specifies baseline activation and coverage
reporting. It does not implement or activate scheduled baseline sampling, enable a
provider, migrate production data, change ranking/training, deploy, or authorize RF.

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

## Phase C baseline activation gates

All gates remain closed after C1. Before implementing or enabling the daily baseline
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

## C1 offline acceptance

- Exact synthetic UUID: raw payload/hash and exact replay remain unchanged; changed
  replay still conflicts; provider calls, inputs, runs and links are zero.
- Unknown UUID: Phase B correlation remains available, provenance is explicitly
  unknown, and every link remains training-ineligible.
- Mixed-release database: legacy tables and rows remain, the additive provenance
  table is seeded exactly once, and SQLite integrity/foreign-key checks pass.
- Full repository Ruff, strict MyPy, pytest and `git diff --check` pass before commit.

No live provider, production database, deployed service, operator identity claim, or
RF evidence is part of this acceptance.
