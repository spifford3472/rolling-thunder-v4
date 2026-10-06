# Forge Services Engineering Guide

## Architectural role

Forge is the network/provider/backend side of Rolling Thunder, but its services are intentionally designed as reusable platform capabilities.

A Forge process must not assume that the only future caller is the Rolling Thunder Tkinter dashboard. Provider protocols, normalization, caching, persistence, retry/backoff, authentication, and external-system integration belong behind stable service boundaries that other authorized applications can call later.

Screen-specific presentation belongs on clients, not Forge.

## Current process families

### Spot / weather / radar service

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
- HTTP publication of retained state.

The service publishes retained state immediately and performs provider/network work in background lifecycles.

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
- resolve the exact approved Wavelog station location;
- convert the normalized contact into deterministic Wavelog-bound data;
- preserve uncertain outcomes safely;
- publish health independently of Pi local logging success.

The service contract is useful to any authorized client capable of providing the normalized contact payload and idempotency key. It must not depend on Rolling Thunder UI state.

Read `docs/FORGE_CONTACT_SYNC.md`.

The same private process can expose the presentation-neutral FT8 performance
endpoint. Its additive API accepts old payloads without configured-power
readbacks and new payloads with nullable `tx_power_start_watts`,
`tx_power_end_watts`, and `tx_power_max_watts`. Forge's dedicated FT8 SQLite
schema migrates v1 to v2 without rebuilding or discarding attempts; legacy
payload hashes remain valid for idempotent replay.

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
