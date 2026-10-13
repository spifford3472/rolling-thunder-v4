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

The source tree now contains an uncomposed NOAA/SWPC adapter for the authoritative
`predicted-solar-cycle.json` product. It selects exactly one requested `time-tag`
`YYYY-MM` and maps `predicted_ssn` to the distinct
`monthly_smoothed_predicted_sunspot_number` semantic. It retains exact raw bytes and
SHA-256, obtainable HTTP headers, capture time, published schema identity, record ID
and the mutable-current-feed/append-only revision policy. The feed has no provable
per-record issue timestamp; release therefore remains unknown and capture is not
backdated. NOAA observed `smoothed_ssn` and HamQSL raw `sunspots` are ineligible.
Malformed, redirected, non-HTTPS, ambiguous, oversized, stale, future-captured,
schema-drifted and missing/mismatched-month inputs fail closed.

`rolling-thunder-forge-voacap-plan` builds an initial fixed `EM79xm` plan from an
operator-reviewed target manifest (one to sixteen explicit grid4/grid6 targets) and a
validated SSN snapshot. The manifest states the exact forecast target month and
capture age remains capped at 24 hours. It never invents target geography. Dry-run is the default
and performs no database or artifact write. `--apply` is explicit, refuses to
overwrite artifacts, and database registration occurs only when `--database` is
also supplied. Generated pilot limits are one provider POST per cycle/day, one slot,
one attempt and a 10-second timeout. The full band/hour contract remains
40/30/20/17/15/12/10 m at 00/06/12/18 UTC and 20 W.

The sampler now normalizes any supplied clock to UTC before selecting tomorrow,
fixing local-offset/DST midnight cases that could otherwise schedule the current UTC
day. The controlled pilot CLI is separately operator gated with the exact phrase
`AUTHORIZE_C4_ONE_POST_PILOT`; it requires all three existing gates, the strict pilot
plan limits, an existing database and a successful consistent backup/integrity/
foreign-key check. The backup hash and table counts are recorded, and success or
failure produces a durable audit sidecar. The sampler validates SSN semantic, month
and complete source identity plus the canonical raw NOAA snapshot artifact and exact
provider identity/version before it persists candidate slots. The adapter refuses a
second POST even after an ambiguous timeout;
provider responses become ready/cacheable only after version, size and requested
hour/band reliability/SNR validation. This is staged code,
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

## C6 safe upgrade candidate (not approved for production)

The root-only `deploy/scripts/upgrade-forge-voacap-baseline.sh` is separate from
the first-install helper. It insists on an existing release, an exact, root-owned
staged SHA, verified offline wheel hashes, three disabled gates, and an explicit
NOAA snapshot path in the owner-controlled configuration. It records a private
backup of the current units, configuration and previous release symlink before
installing the new wheel into a new immutable SHA directory. It checks the new
launcher and config before changing the symlink. The timer is temporarily
stopped during the atomic switch, then re-enabled while all provider gates
remain OFF. On an upgrade error after the switch it restores the previous
release symlink, units and configuration. The previous release is retained.

**NO-GO / manual review still required:** current production configuration
does not yet have the required `ssn_snapshot_path`, so this upgrade MUST fail
until an administrator separately reviews/backs up and supplies it. The
running VOACAP service reports service version 0.3.0 via GET /version but no
model/engine fingerprint; the C4 adapter currently labels the model using its
plan's `model_version` without provider proof. Therefore the pilot must not
run until an independently verifiable provider model-identity contract is
implemented and tested. The engine binary may be SHA-256 fingerprinted
out-of-band for audit, but that is not equivalent to the service attesting the
running engine. The script is a candidate only, not blanket installation,
model verification, live provider use, or C6.4 activation authorization.

## C6 model attestation handshake (pending upstream provider rollout)

Before scheduling or POST, C4 GET /version now requires `model_version`
equal to the immutable plan identity; absent or unequal identity fails closed.
Each successful summary POST must independently return the same model identity
before it may become a ready result. The existing VOACAP service 0.3.0 does
not yet serve this contract and MUST be upgraded/verified separately before a
pilot. A local file hash or administrator assertion alone does not satisfy this
network-level handshake. This change never relaxes provider budgets or gates.

## C6 unattended operation (standing owner authorization, staged)

Owner authorizes recurring software-only VOACAP requests under a six-hour
cadence without per-forecast human approvals. This is **not** authorization
for RF transmission, CAT/PTT control, or changes to FT8 transmit power.

`forge_voacap_plan_main --operational` is explicit opt-in and creates an
immutable plan allowing at most 15 provider POSTs per scheduler run and 60
per UTC day, with 10 seconds per POST, one attempt and a 20 W reference input.
The original default/pilot plan remains limited to one POST per day and cycle.

**Activation blockers:** The sampler will reject NOAA evidence older than
24 hours and the systemd service allows only localhost networking; a
separate reviewed NOAA refresh publisher is needed before enabling the timer.
The previous one-post pilot scheduled 420 slots for its immutable plan;
these are not 420 completed forecasts. A fresh operational plan must not
silently drain or rewrite that historical backlog. Database ready-state,
plan lineage, per-region coverage, rollback and fresh snapshot publication
require acceptance before any automatic gates can be enabled. Keep all
three production gates false until these conditions are verified.
