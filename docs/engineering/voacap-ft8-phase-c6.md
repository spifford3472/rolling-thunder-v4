# C6: Forge C4 bounded production sampler — staged only

A new one-shot `rolling-thunder-forge-voacap-baseline` entry point composes the
C4 `BaselineRepository` and `BaselineService` with a loopback-only provider
adapter. Its three activation gates default false, and an absent plan or SSN
snapshot is not synthesized. A valid immutable `BaselinePlan` and a fresh,
source-identified `EnvironmentSnapshot` (captured within 24h) must be
supplied explicitly; stale solar evidence fails closed.

The worker idempotently schedules 00/06/12/18 UTC slots from the frozen plan,
one to three complete future UTC days, beginning tomorrow, and invokes the existing bounded lease, replay,
retry and per-day/provider-call/storage budgets. The provider adapter maps
the canonical C4 request to the VOACAP summary API, keeping immutable model
and service version identity. Provider calls are **zero** unless all three
gates are enabled, and localhost is the only permitted endpoint.

The proposed systemd service uses the dedicated C4 owner account and
restricts network to loopback. A six-hour timer is staged as a candidate,
NOT installed or enabled. Activation additionally requires separate approval
of provider budget, exact target inventory/model version, verified as-of
solar provenance and the operator-approved installer/rollback.

**Important:** disabled provider mode does not schedule any slots. A real pilot
must use a new, audited plan and approved provider gates before scheduling.
No baseline data are training eligible by virtue of being present.

## C6.2 staged continuation (2026-10-12)

The source tree now contains an uncomposed normalized SSN adapter contract and
append-only snapshot store. It accepts only explicitly identified monthly smoothed
observed SSN and retains source ID/URL/version/record ID, observation/release/capture
times and raw SHA-256. Malformed, ambiguous, oversized, stale and future-knowledge
inputs fail closed. The existing propagation-history HamQSL reader is query-only and
labels its raw `sunspots` value ineligible; no conversion is implemented.

The exact authoritative public upstream and wire schema remain deliberately
unresolved. The normalized adapter is not evidence that NOAA or SILSO implements
that wire contract. A provider-specific adapter must wait for review of the
published upstream schema, version/revision behavior, release timestamps and terms.

`rolling-thunder-forge-voacap-plan` builds an initial fixed `EM79xm` plan from an
operator-reviewed target manifest (one to eight explicit grid4/grid6 targets) and a
validated SSN snapshot. The manifest must state the reviewed maximum observation
age; capture age remains capped at 24 hours. It never invents target geography. Dry-run is the default
and performs no database or artifact write. `--apply` is explicit, refuses to
overwrite artifacts, and database registration occurs only when `--database` is
also supplied. Generated pilot limits are one provider POST per cycle/day, one slot,
one attempt and a 10-second timeout. The full band/hour contract remains
40/30/20/17/15/12/10 m at 00/06/12/18 UTC and 20 W.

The sampler now normalizes any supplied clock to UTC before selecting tomorrow,
fixing local-offset/DST midnight cases that could otherwise schedule the current UTC
day. The controlled pilot CLI is separately operator gated with the exact phrase
`AUTHORIZE_C4_ONE_POST_PILOT`; it requires all three existing gates, the strict pilot
plan limits, an existing database and a successful consistent backup/integrity
check. Its adapter verifies exact service version before POST and refuses a second
POST even if called again. This is staged code,
not authorization to invoke the command or enable any gate.

C6.4 unattended activation remains **NO-GO** pending authoritative source-adapter
verification, an owner-reviewed real target manifest and parent lineage, review of
the pilot backup location/command, explicit one-request approval, successful pilot
evidence and a separate bounded unattended activation approval. Installed Forge
state, timers, gates, databases, Pi/radio behavior and 20-W operational baseline are
unchanged.

## C6.4 bounded unattended activation plan (not authorized)

The first unattended child plan must not reuse the one-shot pilot UUID. It must name
the successful pilot plan as parent and freeze the reviewed target inventory, SSN
semantic/source version, provider 0.3.0 and model version. The candidate six-hour
timer is the maximum starting cadence; missed/offline timer cycles may schedule only
complete future UTC days and must not trigger catch-up provider bursts for elapsed
forecast hours.

Before any activation, reviewers must choose explicit plan values for provider calls
per cycle/day, maximum slots, attempts, exponential retry base/cap, backlog days,
response bytes and total SQLite bytes. A conservative initial review should retain
concurrency one, 10-second timeout and 20-W model input. Version mismatch,
unavailable/malformed cells, stale solar input, exhausted daily budget and storage
cap remain zero-POST or terminal fail-closed states as applicable. Retries must never
cross the plan's daily cap.

Provider-free health must publish last cycle/result, last successful ready future
slot, oldest pending/retry slot, missed/late/backfill counts, provider calls today,
retry/dead-letter reasons, storage bytes/cap, active plan/model/service/source
identities and solar capture age. Offline recovery is timer-driven and bounded: no
parallel worker, no unbounded replay, no rewriting terminal slots, and no promotion
of late/backfill evidence to prospective. Recovery must remain independent of C3,
C5 readiness, Pi availability and radio operation.

Go requires: reviewed source adapter fixtures; reviewed child plan/inventory;
successful one-POST pilot with a ready future pre-choice slot; backup/restore drill;
green exact-SHA staging and permission checks; health/alert review; all gates proven
OFF immediately before the approved change; explicit owner activation approval; and
a documented rollback that disables the timer/provider gates without deleting the
database. Any missing item, provider/version drift, stale SSN, failed restore test,
unexpected POST count or health ambiguity is NO-GO. Activation and deployment are
outside this branch.

C5.4 readiness timer and Pi 20-W radio operation are unaffected. No TX,
CAT/PTT, Pi deployment, service restart or real provider HTTP call performed.
