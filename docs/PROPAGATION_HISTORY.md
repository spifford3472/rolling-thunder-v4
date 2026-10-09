# Forge Propagation History

## Scope and status

The repository contains an independent, presentation-neutral Forge propagation-
history component. Phase 1 now includes staged systemd and deployment assets, but
the production service remains uninstalled and unactivated until the repository
owner executes the privileged rollout. The checked-in production template is
disabled. Development and test work must not contact production providers.

The opt-in entry point is `rolling-thunder-forge-propagation --config PATH`. It
runs a supervised collection loop; `--once` performs one due check and exits, and
`--status` reports durable provider health without contacting a provider. The
database-free `--check-config` command validates and prints the exact Phase 1
provider plan without provider I/O. Both example configurations are disabled. The
component owns its own SQLite database; it must not point at the contact-sync or
spot/weather databases.

The deployed-candidate environmental entry point wires only the hourly HamQSL and
KC2G collection cycle. It does not ingest QSOs, schedule QSO correlation, or invoke
VOACAP, weather enrichment, or PSK Reporter analytics. A separate Phase 2 entry
point, `rolling-thunder-forge-propagation-qso-worker --config PATH [--once]`, now
composes an authenticated bounded ingestion API, the durable completed-QSO inbox,
bounded VOACAP correlation, and local JSON status publication. Its process,
ingestion, and VOACAP gates are independently false in the production template. A
separate hardened systemd unit and typed producer client define the transport, but
the client is deliberately not attached to local commit, contact sync, Wavelog, or
any live contact store. An authorized source still needs its own durable outbound
delivery/retry composition before automatic end-to-end production ingestion exists.
PSK Reporter orchestration likewise has no production composition.

## Phase 1 deployment boundary

The environmental collector has a separate failure and privilege domain:

- unit: `rolling-thunder-forge-propagation.service`;
- static no-login identity: `rolling-thunder-propagation`;
- application/venv: `/opt/rolling-thunder-forge-propagation`;
- configuration: `/etc/rolling-thunder-forge-propagation/forge-propagation.yaml`;
- state: `/var/lib/rolling-thunder-forge-propagation`;
- database: `propagation-history.sqlite3` in that state directory.

Exact-SHA application releases live below
`/opt/rolling-thunder-forge-propagation/releases/<40-sha>` and the root-managed
`current` symlink selects one release. It shares no service identity, checkout,
virtual environment, configuration, or database with the spot service or contact
sync. The unit has no listener and no
credentials. Its Phase 1 composition can issue bounded HTTP GETs only to the one
HamQSL XML URL and two KC2G GeoJSON URLs compiled into the collectors. Each request
has the configured timeout and response-size cap; each source has a durable minimum
one-hour attempt interval and bounded retry backoff. VOACAP, weather enrichment,
PSK Reporter, completed-QSO ingestion, Wavelog, radio, and contact sync are outside
this service.

The unit is not enabled by installation, and `enabled: false` makes an accidental
manual start exit successfully before database or provider access. The systemd
hardening profile removes capabilities, blocks device access, makes the system tree
read-only, and limits sockets to Unix/IPv4/IPv6 families. Hostname-backed public
providers cannot safely be pinned to static IP addresses in the unit; the application
allowlist, request bounds, and durable cadence are therefore the egress controls.

## Owner-controlled install and activation

Perform these commands only on Forge, from an exact reviewed release artifact. They
are intentionally not run by development or CI. The exact-SHA code deployment and
central-helper integration runbook is documented in
`FORGE_PROPAGATION_DEPLOYMENT_PROPOSAL.md`. It reflects the separately inspected
helper's real `<component> <40hex>` interface, repository variables, `run_as_geoff`
Git boundary, remote-commit validation, and legacy deployment ordering.
An immutable release whose generated launcher refers to a removed staging path must
fail closed and be recovered with a fresh reviewed SHA by following
`FORGE_PROPAGATION_BROKEN_RELEASE_RECOVERY.md`; never edit that release in place.

```bash
cd /path/to/exact-reviewed-release

sudo install -o root -g root -m 0644 \
  deploy/sysusers.d/rolling-thunder-forge-propagation.conf \
  /etc/sysusers.d/rolling-thunder-forge-propagation.conf
sudo systemd-sysusers rolling-thunder-forge-propagation.conf
sudo install -d -o root -g rolling-thunder-propagation -m 0750 \
  /opt/rolling-thunder-forge-propagation
sudo install -d -o root -g rolling-thunder-propagation -m 0750 \
  /opt/rolling-thunder-forge-propagation/releases
sudo install -d -o root -g rolling-thunder-propagation -m 0750 \
  /etc/rolling-thunder-forge-propagation
sudo install -o root -g rolling-thunder-propagation -m 0640 \
  config/forge-propagation.production.example.yaml \
  /etc/rolling-thunder-forge-propagation/forge-propagation.yaml
sudo install -d -o rolling-thunder-propagation \
  -g rolling-thunder-propagation -m 0750 \
  /var/lib/rolling-thunder-forge-propagation
sudo install -d -o root -g rolling-thunder-propagation -m 0750 \
  /opt/rolling-thunder-forge-propagation/docs
sudo install -o root -g rolling-thunder-propagation -m 0640 \
  docs/PROPAGATION_HISTORY.md \
  /opt/rolling-thunder-forge-propagation/docs/PROPAGATION_HISTORY.md
sudo install -o root -g root -m 0644 \
  deploy/systemd/rolling-thunder-forge-propagation.service \
  /etc/systemd/system/rolling-thunder-forge-propagation.service
sudo install -o root -g root -m 0755 deploy/forge-propagation-rollout \
  /usr/local/sbin/rolling-thunder-forge-propagation-rollout
sudo systemctl daemon-reload
```

These are first-install commands for the non-code Phase 1 assets. Separately, follow
the central-helper integration runbook to preserve a backup, install the reviewed
component hook as root-owned mode `0750`, add the early propagation branch without
editing the three legacy branches, and deploy one exact pushed lowercase
40-character SHA. The hook consumes only a fresh root-owned, non-writable offline
wheelhouse with a recorded SHA-256 manifest and creates a side-by-side immutable
release; it never performs an in-place `pip install`. Stop if the application root,
dedicated config, sysusers definition, unit, rollout helper, or component hook already
exists unexpectedly. Do not alter the owner or mode of the shared
`/etc/rolling-thunder` directory. Record the staged wheel/wheelhouse manifest,
installed sysusers/unit/config/helper hashes, exact release SHA and `current` target,
and the pre-rollout enabled/active states. Installation ends here: do not enable or
start the unit.

The safe inspection sequence is provider-free:

```bash
systemctl is-enabled rolling-thunder-forge-propagation.service || true
systemctl is-active rolling-thunder-forge-propagation.service || true
sudo /usr/local/sbin/rolling-thunder-forge-propagation-rollout dry-run
```

`dry-run` validates the installed unit, service-account execution/read/write access,
the dedicated database path, and disabled QSO-enrichment controls. It runs
`--check-config` as the dedicated identity and neither creates the SQLite database
nor performs network I/O. Only after reviewing that output may the owner change the
single Phase 1 `enabled` field to `true`. Keep every QSO-enrichment field false. With
the service still stopped, the explicitly confirmed one-shot smoke test makes at most
one due request to HamQSL and one to each KC2G endpoint:

```bash
sudoedit /etc/rolling-thunder-forge-propagation/forge-propagation.yaml
sudo /usr/local/sbin/rolling-thunder-forge-propagation-rollout \
  network-smoke --confirm-hamqsl-kc2g-egress
sudo /usr/local/sbin/rolling-thunder-forge-propagation-rollout provider-status
```

`provider-status` reads durable health without contacting a provider. Review the
journal and database ownership, then activate only with separate authorization:

```bash
sudo /usr/local/sbin/rolling-thunder-forge-propagation-rollout \
  activate --confirm-activate
```

Verify that spot, contact-sync, and Pi services were not restarted or reconfigured.
Phase 1 live acceptance requires healthy durable status after the smoke test and
after at least one supervised scheduled cycle.

## Rollback

The operational rollback is isolated and does not touch radio, FT8, Wavelog, contact
sync, or their data:

```bash
sudo /usr/local/sbin/rolling-thunder-forge-propagation-rollout deactivate
sudoedit /etc/rolling-thunder-forge-propagation/forge-propagation.yaml
sudo /usr/local/sbin/rolling-thunder-forge-propagation-rollout dry-run
```

Restore `enabled: false`. Preserve the dedicated SQLite database for diagnosis and
forward recovery; do not delete it during rollback. `deactivate` fails instead of
claiming success if systemd cannot stop/disable the unit or still reports it active or
enabled. If code or unit rollback is also required, restore the recorded prior
artifact/unit/config only after the service is stopped, run `systemctl daemon-reload`,
and repeat the provider-free dry run. No core service restart is part of this rollback.

## Completed-QSO ingestion contract

`CompletedQsoIngestionRepository.enqueue` durably records the complete immutable
`Contact` JSON and returns without calling VOACAP or any other provider. The stable
contact UUID is the ingestion identity. An exact replay is accepted, while any
changed payload under the same UUID fails closed. This preserves the contact's UTC
start, frozen grids and coordinates, actual frequency/mode, and configured TX power.

The independently invoked `CompletedQsoCorrelationWorker` claims at most its
configured batch size under expiring UUID leases. Each active lease records a stable,
non-secret worker identity while its random token remains the finalization authority.
Failed jobs use bounded exponential backoff, exhaust into an explicit dead-letter
state, and do not suppress other jobs in the batch. An expired final permitted
attempt dead-letters without another provider call. Completed and dead-letter jobs
are not selected again. SQLite restart preserves pending, retry, terminal, and
lease-recovery state.

The history tables use propagation schema version 3; the inbox has its own schema
metadata at version 2, with an additive v1 migration for worker identity. Both
namespaces may coexist in the same dedicated propagation SQLite database without
changing either migration lineage. The separate worker configuration deliberately
uses distinct inbox and history paths; neither may share the contact-sync or
spot/weather database.

Fully disabled startup creates no database or status file. When `enabled` and
`voacap_enabled` are deliberately true, one cycle is bounded by batch, lease, retry,
and provider timeout controls. Every completed cycle atomically publishes versioned non-secret
JSON containing worker identity, cycle result, per-QSO dispositions, queue counts,
due count, dead letters, and timing. The same entry point owns the independently
gated authenticated listener described below.

`VoacapCompletedQsoCorrelator` first archives the exact QSO through the propagation
history repository and then invokes the existing VOACAP client. Eligible results
retain exact request JSON, full response JSON, service version, collection UTC, and
actual-hour derived fields. Missing required frozen inputs produce a terminal
`skipped` result rather than invented values. Storage is idempotent, while worker
delivery is deliberately at-least-once: a process failure after provider success but
before durable job completion can repeat the read-only VOACAP request after lease
expiry.

The inbox is not part of local QSO commit, ContactSyncService, or Wavelog upload.
Those paths perform no VOACAP call and do not wait for propagation work.

### Authenticated ingestion API

When `enabled: true` and `ingestion_enabled: true`, the isolated service listens on
the configured private address and accepts only `POST /api/v1/completed-qsos`.
Requests must use `application/json`, carry the complete `Contact` JSON, supply an
`Idempotency-Key` equal to `contact_id`, and authenticate with
`Authorization: Bearer ...`. The independent secret comes only from
`ROLLING_THUNDER_PROPAGATION_QSO_INGEST_TOKEN`; it is never stored in YAML, status,
logs, or the repository and must contain at least 32 characters. Disabled ingestion
fails closed before authentication. Authentication is checked before the bounded
request body is read. The bearer credential must travel only over the trusted
private/WireGuard path; if that path cannot provide confidentiality, terminate TLS
in front of the listener before activation. Bearer authentication alone does not
make a public or sniffable network safe.

Payloads are capped at 32 KiB, connections and request-body time are bounded, and
the existing inbox transaction completes before an accepted response is returned.
A new event returns HTTP 202, an exact replay returns HTTP 200, changed data under
the same UUID returns HTTP 409, and storage failure returns HTTP 503. `GET /health`
is provider-free and exposes only gates plus non-secret queue counts/times. It never
calls VOACAP. The reusable `HttpCompletedQsoIngestionClient` implements this exact
producer-side protocol but intentionally performs only one delivery attempt; the
source owner must persist outbound state and retry independently.

The service can run as ingestion-only with `voacap_enabled: false`, allowing the
authenticated transport and durable inbox to be accepted without provider access.
VOACAP work occurs only when both the process and VOACAP gates are true. `--once`
runs only one bounded worker cycle and never starts the listener. `--check-config`
validates and prints the non-secret plan without opening SQLite or contacting a
provider. `--status` reads only the atomic local status file; a missing file reports
`never_run` and does not create storage.

### Completed-QSO service supervision (staged, disabled)

The production assets are intentionally not installed or activated by code deploy:

- unit: `rolling-thunder-forge-propagation-qso-worker.service`;
- executable: the QSO entry point from the reviewed propagation exact-SHA release;
- configuration: `/etc/rolling-thunder-forge-propagation-qso-worker/worker.yaml`;
- secret environment: `/etc/rolling-thunder-forge-propagation-qso-worker/ingestion.env`;
- state: `/var/lib/rolling-thunder-forge-propagation-qso`;
- private API: `192.168.9.170:8790` in the production example.

The unit reuses the propagation release's read-only code and unprivileged service
identity but has a separate unit lifecycle, config directory, StateDirectory,
inbox, history database, and status file. Its sandbox makes the environmental
collector state and the shared contact/Wavelog paths inaccessible. It does not
restart or modify the hourly collector. Installation must copy the production
example with all three gates false and replace the deliberately invalid `replace-me`
secret with an independent random value before ingestion can start. Installing the
unit must not enable or start it.

After verifying that the reviewed exact-SHA propagation release contains the QSO
launcher, an authorized Forge administrator can stage only the inactive assets with:

```bash
sudo install -d -o root -g rolling-thunder-propagation -m 0750 \
  /etc/rolling-thunder-forge-propagation-qso-worker
sudo install -o root -g rolling-thunder-propagation -m 0640 \
  config/forge-propagation-qso-worker.production.example.yaml \
  /etc/rolling-thunder-forge-propagation-qso-worker/worker.yaml
sudo install -o root -g rolling-thunder-propagation -m 0640 \
  deploy/systemd/forge-propagation-qso-worker.env.example \
  /etc/rolling-thunder-forge-propagation-qso-worker/ingestion.env
sudo install -o root -g root -m 0644 \
  deploy/systemd/rolling-thunder-forge-propagation-qso-worker.service \
  /etc/systemd/system/rolling-thunder-forge-propagation-qso-worker.service
sudo systemctl daemon-reload
```

Stop there. Do not enable or start the unit. Replace the placeholder secret through
the administrator's secret-generation and transfer procedure; never place the real
value in shell history or Git. The unit's `StateDirectory` is created only when it is
eventually started, so staging does not create or inspect contact/inbox databases.

Provider-free inspection is:

```bash
/opt/rolling-thunder-forge-propagation/current/.venv/bin/rolling-thunder-forge-propagation-qso-worker \
  --config /etc/rolling-thunder-forge-propagation-qso-worker/worker.yaml \
  --check-config
/opt/rolling-thunder-forge-propagation/current/.venv/bin/rolling-thunder-forge-propagation-qso-worker \
  --config /etc/rolling-thunder-forge-propagation-qso-worker/worker.yaml \
  --status
systemctl is-enabled rolling-thunder-forge-propagation-qso-worker.service || true
systemctl is-active rolling-thunder-forge-propagation-qso-worker.service || true
```

Do not enable the unit until an authorized source has a reviewed durable outbox,
the bearer secret has been installed at both ends, private-network reachability has
been restricted, and ingestion-only acceptance has succeeded with VOACAP still
false. A later, separate approval is required to set `voacap_enabled: true` and run
a bounded provider smoke test. No such live acceptance is performed by repository
tests.

Rollback is limited to stopping/disabling this one unit and restoring all three
gates to false. Preserve its dedicated state for diagnosis; do not delete the inbox
or history database. Rollback never restarts the environmental collector, contact
sync, Wavelog, or any Pi service.

## Data model

The schema retains raw observations as well as derived QSO features:

- `solar_observation`: complete HamQSL XML, raw required field strings, source
  update text, source URL, and an independent UTC collection timestamp.
- `kc2g_snapshot`: complete gzip-compressed GeoJSON bytes, source URL, SHA-256,
  metric, and UTC collection timestamp.
- `weather_observation`: reserved structured QSO weather observations.
- `qso_observation`: immutable serialized Contact keyed by `contact_id`.
- `qso_ionosphere`: reserved per-QSO ionosphere features.
- `qso_voacap_prediction`: exact request, service version, complete response, and
  actual UTC-hour/band MUF, reliability, rating, and SNR when present.
- `pskreporter_query`: one complete PSK Reporter provider-query payload and its
  parameters, result state, timing, parse count, and error provenance.
- `qso_pskreporter_summary`: explicit per-QSO collection status, eligibility
  audit, provider-query reference, and matched parsed reception facts.

Collectors enforce a minimum one-hour interval per source. Durable attempt state
preserves that gate across restarts. Failures are isolated; one provider cannot
suppress the others, and repeated failures use bounded exponential backoff. The
supervised loop checks for due work at a separately configured short interval so a
stop request does not have to wait for the hourly gate.

## Providers

HamQSL uses `https://www.hamqsl.com/solarxml.php`. Raw text is preserved because
several values are categorical or decorated strings. `collected_at_utc` is a local
timestamp and is never inferred from the source `<updated>` value.

KC2G archives the complete current interpolated MUF(3000) and foF2 GeoJSON files as
gzip-compressed, SHA-256-verified raw snapshots so estimates can be recomputed.
Estimator `contour_idw_v1` reads `level-value` isolines from both `LineString` and
`MultiLineString` features, measures geodesic distance to contour segments, and
produces endpoint estimates. QSO paths are great-circle sampled at no more than
100 km spacing with a hard cap of 512 samples; the stored path MUF is the minimum
sampled MUF estimate. Correlation uses the nearest snapshot within 90 minutes of
the QSO, preferring the earlier snapshot on an exact tie.

VOACAP calls the existing `/version` and `/api/v1/summary` endpoints. It sends the
full frozen grids, actual QSO band and configured TX power, UTC year/month/timezone,
and maps FT8 to `mode=FT8` even though its hardware setting is FT-891 HF/SSB power.
Correlation is best-effort and belongs on a background worker, never the contact-
sync request path. The environmental collector's `voacap_enabled` and
`weather_enrichment_enabled` fields remain inactive reserved controls. The separate
completed-QSO provider worker requires both its own `enabled` and `voacap_enabled`
gates; ingestion additionally requires `ingestion_enabled`.

Read-only verification on 2026-10-07 confirmed that the documented Forge endpoint
`http://192.168.9.170:8787/version` responded as `voacap-service` version `0.3.0`.
No summary/prediction request was made and no service state was changed.

## PSK Reporter FT8 analytics

The disabled-by-default PSK Reporter adapter uses the official
`https://retrieve.pskreporter.info/query` XML endpoint. One adapter instance permits
at most one network attempt per 300 seconds, including after a failed attempt and
under concurrent calls. The production-inactive orchestration repository additionally
makes that gate durable and global across workers sharing its dedicated database.
Due FT8 QSOs are batched into one recent-window request using `senderCallsign`, `mode=FT8`,
a negative `flowStartSeconds`, `rronly=1`, `noactive=1`, `nolocator=1`, a bounded
`rptlimit`, and a URL-encoded `frange` spanning the due QSO frequencies. Requests have
typed timeout, response-size, 24-hour-window, report-count, and QSO-count limits.
The parser rejects a provider response containing more reception records than the
requested report limit; it does not silently truncate the analytics.

A QSO is not eligible before its FT8 terminal `ended_at_utc` plus
`report_latency_s`, whose safe default and minimum are both 300 seconds. Completion
lookup is keyed by the stable contact UUID, which is the FT8 attempt UUID. When the
terminal time is not yet available, eligibility conservatively falls back to
`Contact.started_at + correlation_window_s + report_latency_s`; malformed, naive,
or pre-start completion timestamps fail closed without a network request. Every
per-QSO summary records the reference source, reference time, and resulting
eligibility time. Successful zero-report results and successful report-bearing
results are terminal only after that boundary and are read from SQLite before
completion lookup or retrieval, so a completed window is not queried again after
process restart. Failures remain explicit and retryable. Persisted states distinguish
`not_queried`, `not_due`, `query_failed`, `queried_zero_reports`, and
`queried_with_reports`; provider, HTTP, size, decode, and document-parse failures
never become zero reports.

Correlation policy `rolling_thunder_ft8_time_frequency_v1` accepts only the configured
sender, FT8 records (with query-filter provenance when the optional record mode is
absent), the same amateur band, frequencies within 10 kHz, and report timestamps from
60 seconds before through the configured post-QSO window. When multiple QSOs overlap,
the closest time/frequency candidate receives the report. The complete raw provider
XML and query provenance are stored once in `pskreporter_query`; every QSO row
references that query and retains only its own matched parsed reception facts,
canonical receiver summaries, report count, unique grids, strongest/weakest SNR,
and furthest receiver when both coordinates are known. One batched response is never
duplicated across the QSO rows it serves.

Receiver coordinates come only from the center of a structurally valid Maidenhead
locator. Missing and malformed locators remain explicit with null coordinates. There
is no authoritative DXCC/continent resolver in this subsystem, so continent is stored
as null (including the explicit unknown group) rather than inferred from longitude or
callsign prefixes.

### Completed-FT8 orchestration boundary

`forge_pskreporter_orchestration.py` accepts only a versioned event containing the
immutable FT8 `Contact` and its matching successful terminal
`FT8PerformanceAttempt`. It rejects non-FT8, unsuccessful, UUID-, callsign-, start-,
or frequency-mismatched events. Exact replay is accepted and changed payload under
the stable UUID fails closed. The narrow sink performs no provider work and has no
authority to read Pi/contact-sync storage or to create contacts.

Eligibility is stored as terminal end plus at least 300 seconds. One SQLite
transaction reserves the bounded due batch, exact absolute query window and contact
IDs, and global provider slot before I/O. Valid zero-report and report-bearing
responses are terminal; provider and parse failures remain retryable and never
become zero. Startup reconciles already-terminal history summaries before another
reservation, closing the crash window after analytics persistence. Provider-free
health reports pending, due, completed, expired, last/next attempt, window state,
and error. There is no scheduler, service unit, producer, or enabled production
configuration for this component.

## Remaining integration

Phase 1 stages supervision only for the environmental HamQSL/KC2G collector. Phase 2
provides a disabled VOACAP worker composition but no deployment assets or producer.
The PSK component provides durable orchestration but no process composition. Before
either QSO-analysis path can be deployed, define and authenticate a producer only
after local QSO and terminal-attempt durability, add independent supervision and
provider-free preflight/status acceptance, and preserve separate owned databases.
Keep both paths outside the Phase 1 collector, FT8 execution, contact sync, Wavelog,
and local QSO logging. Live-provider and crash-window acceptance for VOACAP and PSK
Reporter remains required.
