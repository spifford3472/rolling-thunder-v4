# Rolling Thunder v4 — Autonomous Execution Report

Date: 2026-10-21 EDT

Mission authority: issue #340 comment `6330482816`

Safety outcome: no RF, CAT/PTT exercise, production restart, provider request,
database mutation, merge, or deployment.

## Issue status

| Issue | Development | CI | Merged | Deployed | Verified | Closed |
|---|---|---|---|---|---|---|
| #340 | Baseline/recovery documentation committed | N/A (docs checkpoint branch) | No | No | Partial; current protected identities blocked | No |
| #345 | No new change justified; source assessment and 207-test no-RF regression | No new PR | Prior #347–#352 already merged; no mission merge | Current Pi deployment unverified | Simulation/regression only; production timing blocked | No |
| #353 | Query-only operational health implemented at `3a6f875` | Local gates green; GitHub CI unavailable | No | No | Deterministic tests only; production DB blocked | No |

## Execution mechanism and durable checkpoints

The mission ran as the owner-launched transient Forge user service
`rt-codex-overnight-340-345-353.service`, with workspace-write sandboxing,
network enabled for sandbox commands, `approval_policy=never`, `Restart=no`, and
a 12-hour hard cap. The run ended well before the mission's ten-hour checkpoint
limit. Infrastructure documentation was committed and pushed to
`spifford3472/ki5vnb-qth-infrastructure` branch
`docs/codex-overnight-runner-20261021` at `4514aea`.

The complete mission comment was retrieved and read (34,250 characters). Initial
workspace and live GitHub `main` were both
`d7a3b574dc53d213764eff341ad77ae976df57e1`. No open overlapping PR was returned
by GitHub search.

The workspace `.git` directory was read-only, so authored changes were committed
through fresh clones in the permitted `/tmp` writable root. No permission was
weakened. Durable Rolling Thunder checkpoints are:

- `engineering/overnight-340-345-353` at `a9964e4` — #340 baseline plus complete
  resumable handoff.
- `fix/353-voacap-operational-health` at
  `3a6f875cbfd731873530fa0c134eddc01f76fe81` — focused #353 implementation.

Connected GitHub write operations for STARTED/checkpoint comments and PR creation
were attempted, but the connector required interactive approval while the runner
was explicitly configured with approvals disabled. These writes were not
bypassed. Remote Desktop Commander read commands were blocked by the same gate.

## Issue #340 — production baseline and recovery inventory

### Work performed

- Read the issue body and every comment chronologically.
- Reconciled the 2026-10-16 Pi/Forge service, package, state/configuration, and
  release-path evidence with the 2026-10-21 restricted preflight handoff.
- Added `production-baseline-and-recovery.md`, explicitly separating GitHub state,
  last verified production evidence, provenance gaps, recovery evidence, and
  fresh deployment gates.
- Recorded the current repository SHA and the direct-install provenance gap for
  callsign-info, contact-sync, and spots rather than inferring source commits from
  package version `4.4.0`.

### Evidence and limitations

Verified production evidence retained from 2026-10-16 includes Pi source
`0c79f2a`, Forge immutable releases `fb9efe0`, `24762a1`, `e09903b`, and
`47c7421`, service-separated state locations, and metadata-only configuration
inventory. The Oct 16 R0-02 snapshot was restored to isolated paths: Pi plus 11
Forge SQLite databases passed integrity checks, and both archives/all 14
manifest-covered files matched hashes and sizes.

The current Pi SHA, current direct-install Forge source provenance, and fresh
protected backup manifest were not independently readable in this run. The
observed failed `forge-radio-config-backup.service` was not repaired or restarted;
its effect on radio/Node-RED recovery remains a separate read-only disposition.
Because production identity and fresh recovery readiness remain uncertain, #340
is not closed and all deployment gates remain closed.

Rollback: documentation-only; revert the focused documentation commits if
incorrect. No production rollback is required.

## Issue #345 — FT8/CAT/UI/radar critical path

### Work performed

Current source includes the merged R1-A/R1-B/R1-C changes: opt-in aggregate and
correlated slow-refresh metrics, two-tile-per-refresh radar/base-map image
budgets, and verified FT8 band presentation without increasing CAT polling.
Source review found no new evidence supporting another behavior change.

The no-RF focused suite exercised UI timing/composition, live map/radar,
slow/unavailable Forge clients, physical controls, FT8 timing/audio/receive/QSO
coordination/hardware-transmit fail-safes/band presentation, and contact
durability/synchronization: **207 passed in 10.16 seconds**.

### Evidence and limitations

This is successful deterministic simulation/regression evidence, not production
performance evidence. The approved interface could not expose a current Pi
diagnostic window for radar off/on p50/p95/p99/max, correlated >100 ms phase
lines, FT8 boundary lateness/drop counters, or physical-control latency.
Therefore long-tail >400 ms refresh behavior remains unverified, no new code was
created, and #345 is not closed.

Rollback: none; no #345 change or production action occurred.

## Issue #353 — VOACAP six-hour forecast collection

### Work performed

Source investigation confirmed a bounded, evidence-backed observability defect:
normal sampler output could report `state=complete` with scheduled, processed,
and provider-call counts but no classification of actual expected coverage.

Commit `3a6f875` adds:

- query-only plan/day health over the existing SQLite schema;
- expected/observed/missing and pending/retry/processing counts;
- provider-stored ready versus cache-reused ready counts;
- unavailable, skipped, failed/missed classification;
- provider-contacted slots and UTC-day call ledger beside the plan limit;
- explicit `complete`, `complete_with_unavailable`, `incomplete`, or `failed`
  coverage state;
- the health object in each enabled cycle's JSON; and
- provider-free `--health` mode that does not initialize/migrate the database,
  read NOAA artifacts, schedule work, contact the provider, or change gates.

Engineering and operator documentation now reflect active Forge-only C6
scheduling and explain why a successful timer exit is not coverage proof.

### Tests

- Focused Ruff: pass.
- Focused strict MyPy: pass.
- Focused C6 suite: 44 passed.
- Repository Ruff: pass.
- Repository strict MyPy: pass, 341 source files.
- Repository pytest: **3,392 passed, 7 skipped** in 35.66 seconds.
- `git diff --check`: pass.

### Release status and limitations

The branch is pushed, but PR creation was connector-blocked. GitHub CI does not
run for a bare `fix/**` push in the current workflow, so CI is unverified and the
change is not merge-qualified. The protected production database, exact installed
C6 release, current coverage, fresh backup, and C6-specific deployment helper were
not accessible. No provider call or production validation was attempted. #353
remains open.

Rollback if later deployed: select the previous immutable C6 release with the
approved component-specific procedure; the change has no schema migration and
does not rewrite historical records. Never restore a stale database over newer
forecast evidence.

## Production, backup, and safety summary

- GitHub `main`: verified at `d7a3b574dc53d213764eff341ad77ae976df57e1`.
- Current Pi source SHA: unverified in this run; last verified evidence was
  `0c79f2a` on 2026-10-16.
- Current Forge direct-install source SHAs: unresolved; immutable service release
  identifiers are historical evidence only until rechecked.
- Current service health: not independently rechecked because the approved remote
  read tool was connector-blocked. The immediately preceding 2026-10-21 issue
  handoff reported Pi main service, Forge contact-sync, and C6 timer active, but
  this report treats it as prior evidence rather than a new observation.
- Backup status: Oct 16 isolated restore verified; Oct 21 timer/forward success is
  prior evidence; fresh protected manifest/integrity remains unverified.
- Outstanding safety risks: uncertain installed identity/recovery freshness,
  unobserved current Pi operating state, unresolved real Pi responsiveness tail,
  and uninspected protected C6 coverage. These block merge/deploy/closure as
  applicable.

No new follow-up issue was created because GitHub writes were blocked. The two
highest-value follow-ups are: (1) provide an approved noninteractive metadata-only
read path and GitHub write path consistent with `approval_policy=never`; and (2)
open the #353 PR, obtain green CI/review, then run its query-only health command as
the C6 service identity against the protected production configuration.

The next execution should resume #340's fresh identity/backup check first, collect
#345's bounded production diagnostic window second, and only then consider #353
merge/deployment gates. No unattended execution remains scheduled by this report.
