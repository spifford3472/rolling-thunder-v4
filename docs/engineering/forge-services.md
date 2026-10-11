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
`tx_power_end_watts`, and `tx_power_max_watts`. Forge's dedicated FT8 SQLite
schema migrates v1 to v2 without rebuilding or discarding attempts; legacy
payload hashes remain valid for idempotent replay.

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
