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

### NOAA refresh implementation and queue isolation

A separate `forge_voacap_noaa_refresh_main` utility retrieves exactly one
target month from the pinned NOAA HTTPS feed, validates source provenance
against an immutable plan, and produces snapshot/environment JSON artifacts.
Its `--apply` mode atomically replaces each artifact in the same directory;
the sampler checks their canonical hashes and fails closed on any in-flight
mismatch. The HTTPS publisher is **not** part of the localhost-only sampling
service and must be run under a separately reviewed least-privilege systemd
unit/timer before live activation. No live NOAA fetch or protected publication
is required for its unit tests.

The C4 claim query includes `WHERE plan_id=?`, which isolates the 420
historical pilot slots from a new operational plan. A 15-call-per-cycle,
60-call-per-UTC-day budget does **not** calculate all 15 regions x 7 bands x
4 six-hour slots (420 per day); it is a sampled subset. A future coverage
algorithm must deliberately rotate target regions and bands, rather than
assume the oldest queued 15 slots give balanced international coverage.

**GO/NO-GO:** Keep all three gates OFF pending a dedicated NOAA refresh
unit, a new reviewed operational plan, region/band coverage scheduling, root
owner database acceptance, and reversible deployment. Standing authorization
for recurring software calculations does not bypass these engineering gates.

### Provider-free operational health

Each enabled sampler cycle emits a nested `operational_health` summary for the
exact immutable plan and future UTC-day window it considered. The summary
distinguishes expected, observed, missing, pending/retry/processing,
provider-stored ready, cache-reused ready, unavailable, skipped, and
failed/missed slots. Exact expected and observed slot identities are reconciled
per UTC day using the immutable region/grid, band and forecast-hour tuple; stable
digests plus bounded missing/unexpected samples prevent matching totals from
hiding the wrong coverage. The report also identifies stale targets, invalid or
unclassified records, provider-contacted slots and today's ledger-backed
provider-call count beside both immutable cycle/day limits. All plan, slot and
budget queries share one SQLite read transaction, so the report is a coherent
snapshot even while the sampler is active. A top-level cycle `state=complete`
therefore no longer obscures incomplete forecast coverage.

Administrators can run the same query without scheduler/provider work using
`rolling-thunder-forge-voacap-baseline --config <path> --health`. Health mode
opens the existing SQLite database query-only and reads only the plan artifact;
it does not initialize/migrate the database, read NOAA artifacts, contact the
provider, schedule work, or alter activation gates. `complete_with_unavailable`
means every expected slot is terminal but at least one provider result lacked a
usable prediction; it is distinct from both ready coverage and an incomplete
queue.

### Commissioning-stage timer and deterministic coverage order

The `rolling-thunder-forge-noaa-refresh` example systemd units run the
refresh publisher under a dedicated `rolling-thunder-noaa` account every six
hours. A separately reviewed deployment must create that user, grant only
write permission to the artifact directory, and use the sampler unit dependency to require successful refresh before
each run (calendar ordering alone does not guarantee this).
**The unit files are not installed or enabled by the repository change.**

The queue now orders by forecast UTC, **band**, then region, instead of
region then band. With 15 reviewed targets and 15 calls per cycle, this
prioritizes region-diverse samples before requesting another band's set.
This is deterministic per time/band, rather than a comprehensive all-band
coverage guarantee. The 420 previously scheduled pilot slots remain tied
to their historical plan ID and are not drained by a new plan.

The NOAA publisher writes only under a dedicated /var/lib/rolling-thunder-noaa directory owned by its account; it cannot modify /etc plan or activation configuration. The sampler reads these published artifacts via explicit config paths.

The C6 disabled upgrade helper stages the NOAA refresh units **without**
enabling either timer. It leaves the baseline timer stopped because the
sampler now has a required NOAA refresh dependency. Administrator
commissioning must provision the dedicated NOAA account/directory and validate
a new immutable operational plan before activation. Upgrade rollback restores
earlier units and configuration and leaves the baseline timer disabled.

## C6 scheduled capture v1 — successor plan, source-only candidate

**Status: implemented in source for review; not merged, installed, configured, or run
against the production provider/database.** The original monthly-slot C4/C6 path
remains unchanged and retains its old plan hashes, monthly response reuse, 40/30/20/
17/15/12/10 m inventory, and historical rows. It does not satisfy the owner's
clarified repeated-capture requirement.

The separate `scheduled_capture_v1` mode uses an immutable successor `CapturePlan`
and a dry-run-first `c6-scheduled-capture-manifest-v1`. The owner-reviewed manifest
must contain exactly the same 15 defined site identities and representative grids,
with a new inventory version, new plan UUID, and the prior operational plan UUID as
parent. The mode fixes the bands to 80/40/20/17/15/12/10 m and target hours to
00/06/12/18 UTC. Its four timer boundaries remain 00:10, 06:10, 12:10, and 18:10
UTC. Each boundary creates an independent run identity and issues one API POST for
each site/band: 105 requests/run and 420 expected requests per UTC day. Each
provider response is checked for that band at all four UTC hours, yielding 420
site/band/hour cells per run and 1,680 per day. The monthly C4 response cache is not
consulted and cannot suppress a run. Reusing identical response bytes for storage is
not considered request reuse; every run keeps separate request and provider-attempt
provenance.

The capture plan and NOAA snapshot are frozen into run evidence. The SQLite addition
uses separate `baseline_capture_*_v1` tables; it does not rewrite or migrate legacy
C4 rows. Each request retains a run ID, scheduled boundary, capture timestamp, target
identity, band, request SHA, response SHA, service/model versions, status, attempt
count and reason. A leased request attempt is counted separately from an actual POST;
`provider_called` is set only after version preflight succeeds, immediately before the
HTTP POST, and cycle/health reports separate attempt and POST counts. Four forecast-hour values are persisted as
separately classified cells. UTC boundaries choose the capture day/month after normalizing timezone-aware
input. A delayed invocation more than 30 minutes after its boundary does not start a
catch-up burst. A replay of an already completed boundary makes no provider requests;
a retry only claims explicitly retryable rows from that same run. At later boundaries
on the same UTC day, due retries from prior runs are handled after the fresh current
run. Unattempted past boundaries and incomplete prior-day rows are marked missed; the
scheduler does not launch previous-day catch-up bursts. Missing model cells,
provider/version errors, expired leases and exhausted storage remain visible.

The plan builder `rolling-thunder-forge-voacap-capture-plan` is dry-run by default.
`--apply` writes only new plan/environment artifacts and never registers a plan or
opens a database. Runtime opt-in requires `capture_mode="scheduled_capture_v1"`, an
explicit `capture_plan_path`, and the existing three independent process/scheduler/
provider gates. `--health` opens the database query-only and distinguishes expected
runs/requests/cells from observed evidence; a missing capture schema is reported as
incomplete. The response-size and capture-response storage caps remain bounded. If
the storage cap is reached, remaining requests are marked skipped and coverage stays
incomplete; no historical data are pruned.

Fake-provider acceptance covers exactly 105 requests at each of four UTC boundaries,
separate attempt and actual-POST counts (including zero POSTs on preflight failure),
zero cross-run cache reuse, run replay, persisted service/model/response provenance,
status and missing-hour classification, bounded retries/storage, month rollover,
query-only health, and SQLite backup/integrity/foreign-key checks, including next-boundary same-day retry
and prior-day missed classification. These tests are not production provider calls.
Live backup/restore, exact installed site inventory,
provider POST count and provenance, protected-database coverage, and cutover/rollback
remain unverified. The current production upgrade helper disables the active timer
and requires gates off; do not switch the production config or enable this mode until
a separate maintenance-window cutover and rollback are reviewed. No Pi, CAT/PTT, RF,
production database, service, or timer action is part of this source candidate.

### Scheduled-capture commissioning integration

The NOAA publisher accepts `--forecast-day current` for scheduled captures;
the default remains `next` for legacy future-day slots. It normalizes the clock
to UTC before selecting the forecast month. The scheduled deployment must use
a service override with the current-day option and retain its immutable legacy
parent as the NOAA source-identity contract. Do not pass CapturePlan to the
legacy-plan parser.

For the historical immutable capture plan (10-second requests, three attempts,
60-second retry delay), install a sampler `TimeoutStartSec=90min` override.
A boundary processes 105 fresh requests followed by due retries from up to
three earlier same-day runs. A fixed invocation clock and positive retry delay
allow at most one attempt per request per invocation: at most 420 requests,
4,200 seconds of configured provider timeout plus version preflight and local
storage overhead. 90 minutes gives approximately 20 minutes of overhead margin
and remains below the six-hour cadence. This is a configured budget, not a
hard proof of wall-clock completion: socket operations and SQLite contention
may still exhaust it; systemd timeout and incomplete health remain visible.
Do not increase plan timeout/attempt/retry settings without reviewing this budget.
The 30-minute window controls invocation admission, not completion duration.
No immediate replay is required at cutover; enable timers for real future boundaries.

### October 27 successor-plan timeout policy (source change)

New CapturePlan construction and the dry-run builder default to a 60-second
provider timeout and one attempt per request. Explicit historical 10-second /
three-attempt plans retain their canonical hashes and policy. Never edit an
existing plan ID or stored payload to adopt these defaults: create a reviewed
successor with a new identity, preserving old plans, requests, responses and runs.
There is no scheduled call quota: each admitted boundary still attempts its 105
site/band requests without consulting the monthly response cache. Storage safety
limits remain explicit incomplete/skipped outcomes, not successful collection.

The installed 90-minute budget applies only to the historical plan. At 60 seconds,
105 sequential calls alone allow 6,300 seconds (105 minutes), plus version preflight
and persistence overhead. A successor needs a separately reviewed service timeout
(for example two hours with approximately 14 minutes for preflight/overhead),
lease/recovery and admission review before activation. Socket timeouts are not a
proof of a whole-cycle wall-clock bound. Do not activate only the new plan under
the old 90-minute unit, and do not replay old boundaries to manufacture coverage.
This source change does not switch production configuration or restart either host.

New terminal scheduled failures persist four explicit `failed` hour cells in the
same transaction as their lease-validated request outcome. Reliability and SNR are
SQL NULL with a bounded failure reason. Retryable legacy attempts create no cells
until success or terminal failure. Earlier rows are not backfilled or reclassified.
A failed request does not suppress the other site/band requests or the next run.

## Response-body deduplication across provider versions

Canonical response bytes are content-addressed independently of the issuer. Blob version fields retain the first observation; each request retains its own verified provider/model versions. Identical bytes from a newer version are accepted without changing old evidence; different bytes under an existing hash remain a hard error. Missing reliability or SNR leaves both derived prediction columns NULL for that hour/band, with other complete transactions unaffected. See [issue-353-response-identity-and-missing-values.md](issue-353-response-identity-and-missing-values.md).
