# Forge Services Engineering Guide

## Architectural role

Forge is the network/provider/backend side of Rolling Thunder, but its services are intentionally designed as reusable platform capabilities.

A Forge process must not assume that the only future caller is the Rolling Thunder Tkinter dashboard. Provider protocols, normalization, caching, persistence, retry/backoff, authentication, and external-system integration belong behind stable service boundaries that other authorized applications can call later.

Screen-specific presentation belongs on clients, not Forge.

## Current process families

### Spot / weather / radar / map service

Entry point: `rolling-thunder-forge-spots` / `forge_spot_main.py`.

Production service: `rolling-thunder-forge-spots.service`.

Production API: port 8766 on the private network.

Responsibilities include:

- durable provider-neutral spot snapshots;
- POTA provider polling;
- persistent DX Summit IRC ingestion;
- disabled-by-default persistent DXSpider fallback;
- provider health;
- mobile-location state used by backend services;
- retained weather;
- weather alerts;
- radar;
- optional on-demand style-aware map tiles backed by a local TileServer
  GL-compatible renderer;
- HTTP publication of retained state.

The service publishes retained state immediately and performs provider/network work in background lifecycles.

The optional map route is the exception to retained/polled publication: one
bounded tile request is rendered on demand from the local renderer. It is
disabled by default, has no background lifecycle, and is layered into the same
private port 8766 application as spots, weather, location, alerts, and radar.
Map failure does not change those other routes. The standalone
`rolling-thunder-forge-map` entry point remains useful for development/testing,
defaults to port 8767, and must not be used as a second production service unless
deliberately isolated.

#### DX Summit

`forge_dxsummit_provider.py` owns one long-lived IRC session. It registers once, joins `#CQDX`, responds to PING, continuously ingests `dxs` messages, and reconnects only after genuine connection failure using bounded backoff.

Do not reintroduce periodic connect/scrape/disconnect behavior. Connection age is not a reason to reconnect.

`forge_dxsummit_irc_parser.py` is protocol parsing only and must remain network-independent.

#### DXSpider fallback

`forge_dxspider_provider.py` remains disabled by default. If deliberately enabled, it also uses one persistent connection. Initial `show/fdx` is a one-time seed per actual connection, not a polling mechanism.

DX Summit and DXSpider are mutually exclusive providers.

#### POTA

Forge POTA provider code owns public-provider access and normalization. The Pi should consume Forge's provider-neutral retained API rather than duplicating public provider polling.

### Callsign/contact-intelligence service

Entry point: `rolling-thunder-forge-callsign-info` / `forge_callsign_info_main.py`.

Responsibilities:

- QRZ identity/profile lookup;
- latest exact-callsign Wavelog history;
- target current weather;
- bounded caching;
- one compact presentation-neutral contact-intelligence response.

The service must remain useful to clients other than Rolling Thunder. A caller should not need Tkinter concepts or a Rolling Thunder screen ID.

Read `docs/CALLSIGN_INFO.md`.

### Contact synchronization service

Entry point: `rolling-thunder-forge-contact-sync` / `forge_contact_sync_main.py`.

Production service is deployment-isolated from the spot/weather process.

Responsibilities:

- accept local contact synchronization requests over a private API;
- enforce idempotency keyed by stable contact UUID;
- resolve, verify, and when necessary safely create the exact approved Wavelog
  dynamic mobile station from immutable QSO-local routing fields;
- route incomplete location data to verified `Mobile - Unknown Location` and preserve configured-logbook membership;
- convert the normalized contact into deterministic Wavelog-bound data;
- preserve uncertain outcomes safely;
- publish health independently of Pi local logging success.

The service contract is useful to any authorized client capable of providing the normalized contact payload and idempotency key. It must not depend on Rolling Thunder UI state.

Read `docs/FORGE_CONTACT_SYNC.md`.

Station/logbook management remains provider-adapter behavior on Forge. The adapter
uses owner-scoped Wavelog v2 station/logbook resources, treats names as exact
identities, never guesses numeric IDs, verifies canonical create/link results, and
does no writes during health checks. Because Wavelog's station list can hide unlinked
locations under `active_log_only`, the adapter uses a minimal durable name -> verified
ID/UUID recovery binding in the contact-sync SQLite repository. A 201 result is bound
before linking; hidden retries direct-fetch only that known ID and fail closed on any
identity or metadata change. A hidden generic 409 without a prior binding is not
recoverable and never triggers numeric-ID scanning. The application service resolves
this exact target before its durable UUID claim and binds the target ID into the
payload hash.

The same private process can expose the presentation-neutral FT8 performance
endpoint. Its additive API accepts old payloads without configured-power
readbacks and new payloads with nullable `tx_power_start_watts`,
`tx_power_end_watts`, and `tx_power_max_watts`, plus paired nullable frozen
`local_latitude` and `local_longitude`. Forge's dedicated FT8 SQLite schema
migrates transactionally through v1 configured base fields, v2 configured-power
readbacks, v3 busy-extension counts, and v4 coordinates without rebuilding or
discarding attempts. Historical coordinate columns remain null; payload hashes are
not rewritten, and the existing v1/v2/v3 hash shapes remain valid for idempotent
replay. This endpoint writes only performance telemetry and never calls Wavelog or
contact synchronization.

Contact sync performs no weather-provider work. It uploads the immutable contact it
receives; existing structured weather is retained, while requested notes render
missing weather as `N/A`. `contact_weather.py` and `OpenMeteoForgeWeatherProvider`
remain reusable outside synchronization, including for a separate background
propagation/history worker.

### Propagation environmental history (Phase 1 assets staged, disabled)

`forge_propagation_*` provides a separate disabled-by-default environmental entry
point, typed collectors, and dedicated SQLite history. That Phase 1 process runs only
the hourly HamQSL/KC2G cycle with provider-I/O-free status. A distinct double-gated,
disabled completed-QSO entry point composes its durable UUID-idempotent inbox,
identified bounded leases, retry/dead-letter processing, existing VOACAP summary
client, authenticated bounded private listener, and atomic local status publication.
Its typed producer client defines one authenticated delivery attempt. The optional
Pi source outbox now composes that client behind disabled-by-default gates and an
independent scheduler. It is not composed into the environmental process, contact
sync, Wavelog, or local logging.

The disabled-by-default PSK service accepts a confirmed event containing the
immutable FT8 contact and matching successful terminal attempt. It durably owns exact
event replay, absolute request-window identity, a cross-process 300-second provider
gate, bounded query batches, and provider-free health. Batched provider XML is stored
once per query rather than copied into every QSO summary. It reuses the existing
analytics/history contracts and adds no propagation engine. The separate PSK Reporter service has a bounded scheduler, authenticated private event ingestion, provider-free health/status, isolated databases and independently hardened systemd/sysusers/configuration templates. Process, ingestion and provider egress are separately gated and disabled by default. The VOACAP service independently provides authenticated completed-QSO ingestion and prediction through a disabled worker. Both use isolated exact-SHA release trees and dedicated no-login identities. Optional Pi production delivery is also gated off by default; neither service is installed/activated by source composition. Phase 1 propagation, logging, contact-sync and Wavelog remain unchanged. See
`docs/PROPAGATION_HISTORY.md`.

Phase B extends only the disabled propagation-QSO service with an authenticated
all-terminal FT8 attempt inbox and read-only per-attempt diagnostics. Ingestion
commits before provider work. The bounded worker uses identified leases,
retry/dead-letter isolation, immutable full-input hashes and append-only runs/links.
It preserves direction, event-hour UTC, per-period verified configured power, grid
precision, dB-Hz units, missing values and retrospective availability. It does not
create contacts or affect the completed-QSO/Wavelog path.

Phase C1 adds a separate UUID-keyed provenance table to that attempt history.
Documented synthetic/test UUIDs finish their durable queue lifecycle without a
VOACAP request or training link; diagnostics publish the evidence-backed exclusion.
Unknown provenance remains explicit and training-ineligible. Raw payloads, hashes,
replay, legacy completed-QSO correlation and all disabled activation gates are
unchanged. See `engineering/voacap-ft8-phase-c.md`.

Phase C2 adds only a reusable provider-free report function over explicitly declared
read-only inbox/history snapshots. It returns privacy-minimized, versioned
retrospective coverage and reconciliation data, fails closed on source/invariant
corruption, and has no listener, provider, scheduler, lease, activation, or UI
contract. It is a scoped prerequisite artifact, not completion of the full baseline
field-coverage gate.

Phase C3 adds an operator-run fake-only CLI and reusable offline replay function for
the approved AA4NP historical event. Source inbox/history snapshots are query-only;
the function requires the exact UUID/payload SHA and the already-present audited
`field_observed` row, then writes only to a newly created history copy. It neither
inserts nor changes provenance. The local fake fixture is strictly versioned and
keyed by the real provider's year/month plus selected hour/band/mode/watts semantics;
there is no HTTP client or socket path. The report records immutable input/response
hashes, bounded calls, zero-call terminal replay, append-only version forks, explicit
missing/unsupported/provider failures, C2 reconciliation, and source/lease
non-mutation. It is not a service, scheduled worker, production migration, or
baseline activation path.

Phase C4 adds a reusable but uncomposed baseline-sampling service boundary in
`forge_voacap_baseline.py`. It persists immutable plan lineage, fixed bounded slots,
canonical monthly provider responses, leases/retries/budget activity and deterministic
read-only diagnostics. Its process, scheduler and provider configuration gates all
default false; no provider HTTP adapter, daemon, unit, port or Pi consumer is added.
All C4 tests use an injected fake and all results are training-ineligible. See
`engineering/voacap-ft8-phase-c4.md`.

Phase C5 adds reusable but uncomposed offline contracts in
`forge_ft8_power_advisor.py` and a strict atomic YAML policy loader. It performs
prospective as-of pairing and grouped chronological descriptive evaluation, stores
immutable hashed audit artifacts, emits only explanatory shadow advisories, and
computes readiness states. It contains no provider/network adapter, listener,
scheduler, Pi client, radio import or production migration. Advisory flags prohibit
application and transmission; armed mode is readiness-only and the fallback/current
baseline is 20 W. See `engineering/voacap-ft8-phase-c5.md`.

The same slice persists deterministic missing-input directions before provider work,
so unknown remote power retains a reverse skipped run even if forward retries
dead-letter. Structurally invalid grids are not sent, and an existing-adapter response
without requested hour/band values is unavailable rather than ready.
Forward model identity uses each transmitted period's UTC/frequency-derived band and
strictly verified configured-power evidence. An explicitly configured model service
version is included in canonical input hashes before egress, allowing terminal replay
to avoid provider calls while upgraded models or changed assumptions append distinct
evidence. If no version is known before the call, matching durable terminal history
fails safe by suppressing eager re-query; legacy runs and hashes are not rewritten.

Phase 1 uses its own no-login `rolling-thunder-propagation` identity, application
root, configuration, StateDirectory, and SQLite database. The systemd unit has no
listener and is not enabled by installation. Its production template remains
disabled, and its preflight `--check-config` performs neither database nor provider
access. Activation and the bounded HamQSL/KC2G network smoke test require separate
explicit confirmations. Stopping/disabling this unit is the complete operational
rollback and never restarts or changes radio, FT8, spot, Wavelog, or contact-sync
services.

The staged deployment integration gives propagation its own exact-40-SHA component
hook and immutable release/current-link layout. The verified central dispatcher uses
`<component> <40hex>`, `SOURCE_REPO`, `run_as_geoff`, and
`verify_remote_sha`. Its propagation branch must run immediately after common SHA
syntax validation and before legacy `STATE_FILE`, virtualenv, database, stop, backup,
or rollback work. It fetches and validates the pushed origin commit, then `exec`s the
fixed propagation hook. The hook accepts no caller-controlled paths or service names
and can restart only the propagation unit when it was already active. Exact-commit
wheels are prepared separately from a Git archive, manifested, reviewed, and only
then promoted into the root-owned staging contract. See
`../FORGE_PROPAGATION_DEPLOYMENT_PROPOSAL.md`.

The component hook creates each virtualenv at its immutable final SHA path so pip
console launchers are not invalidated by directory relocation. Before selecting a
release, it executes the installed propagation launcher with provider-free `--help`
as the dedicated service identity. Broken existing releases fail closed without a
`current` change; recovery uses a new reviewed SHA under
`../FORGE_PROPAGATION_BROKEN_RELEASE_RECOVERY.md` rather than mutating an immutable
release.

## Reusable service design rules

### C6.2 NOAA predicted-SSN adapter

The uncomposed boundary in `forge_solar_ssn.py` maps NOAA/SWPC's documented
`predicted-solar-cycle.json` records into exact-target-month
`monthly_smoothed_predicted_sunspot_number` evidence. It uses bounded injected HTTPS
transport and retains raw bytes/hash, obtainable HTTP headers, capture time, source
schema and the mutable-current-feed/append-only revision policy. NOAA publishes no
per-record issue timestamp in this wire contract, so release time remains null and
capture is never backdated into an as-issued claim. The CLI can capture one month or
inspect the local revision store; it is not runtime-composed. HamQSL raw `sunspots`
and NOAA observed `smoothed_ssn` remain explicitly ineligible substitutes.

All Forge additions and modifications must follow these rules:

1. **Presentation-neutral contracts.** Responses contain domain/service data, not Tkinter labels, colors, widget coordinates, or screen-specific layout.
2. **Stable typed schemas.** Validate inputs and outputs explicitly; version contracts when incompatible changes are unavoidable.
3. **Independent lifecycle.** Provider sessions, polling, caches, and retries are owned by the Forge process, not triggered by a UI refresh.
4. **Durable state where correctness requires it.** Restarts must not silently erase idempotency or retained-state guarantees.
5. **Bounded external work.** Use timeouts, size limits, cache limits, stale rules, and backoff.
6. **Provider isolation.** External-provider quirks remain behind provider adapters.
7. **Private credentials.** Secrets stay on Forge and are never exposed to clients.
8. **Failure transparency.** Health/degraded/retained state must truthfully distinguish live data from retained data and errors.
9. **Multi-client safety.** Do not rely on one caller's timing, screen state, or refresh cadence.
10. **No radio authority.** Forge backend availability or provider results must not directly key a transmitter.

## Production data and deployment

Forge services use service-owned configuration and state outside Git working trees. Deployment must preserve production YAML/environment files and SQLite databases.

Do not run two writers against the same SQLite state database.

Service processes should be independently restartable where their failure domains are separate.

## API evolution checklist

Before changing a Forge API:

- identify all current Pi consumers;
- determine whether other future clients could reasonably depend on the existing shape;
- preserve backward compatibility when practical;
- document intentional breaking changes;
- add request/response validation tests;
- verify retained/offline/error semantics;
- update this guide and the relevant API/subsystem documentation.


## Known/friend directory

The callsign-info process also owns the optional SQLite known-callsign directory,
private browser admin, bounded active snapshot and batch classification routes.
Comments stay on Forge; clients receive only classification. No new process or
port is introduced. See `../KNOWN_CALLSIGNS.md` for contracts and deployment.

C5.1 includes a **candidate** separate Forge readiness timer and one-shot CLI.
It is not deployed; the existing approved generic Forge deploy helper has no
readiness component. No listener, provider egress, Pi dependency or radio control.
The C4 inventory count is not a qualified prospective C5 calibration cohort.
See `voacap-ft8-phase-c51.md`.

## Forge C6 six-hour VOACAP forecasting (v4.4.1)

The Forge-owned NOAA service `rolling-thunder-forge-noaa-refresh.timer`
refreshes predicted SSN evidence at 00/06/12/18 UTC under the isolated
`rolling-thunder-noaa` account. The forecast timer
`rolling-thunder-forge-voacap-baseline.timer` executes at 00:10/06:10/12:10/18:10
UTC, allowing time for the upstream capture. The sampler remains strictly
Forge-only; no Pi CAT/PTT, RF transmission, or autonomous transmit-power change
is permitted. The immutable operational C6 plan limits provider requests to
15 per cycle and 60 per UTC day; actual quotas depend on the installed plan.
The C6 acceptance checkpoint had 15 successful real provider calls and
15 ready forecasts, with the original pilot evidence kept separately.
The deployment's configuration, NOAA artifacts, plan, and database must be
backed up and validated independently of a source release.

Cycle JSON includes provider-free operational coverage health. It separately
counts provider-stored and cache-reused ready slots, unavailable outcomes,
pending/retry/processing work, skipped work, failed/missed work, missing
expected slots, stale targets, unexpected identities, and the current UTC-day
provider-call ledger. Per-day identity digests and bounded missing/unexpected
samples bind totals to the immutable plan inventory. The same coherent SQLite
read snapshot is available through the query-only `--health` CLI mode; this mode
never schedules work or contacts NOAA/VOACAP.
