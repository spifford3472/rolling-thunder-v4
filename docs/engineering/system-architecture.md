# System Architecture and Runtime Topology

## Purpose

This document describes the current deployed shape of Rolling Thunder and the
major process/lifecycle boundaries an agent must preserve.

## Topology

```text
                             Internet / provider networks
                                       |
       +-------------------------------+-------------------------------+
       |               |               |              |                |
     POTA          DX Summit IRC    Open-Meteo        NWS          QRZ/Wavelog
       |               |               |              |                |
       +---------------+---------------+--------------+----------------+
                                       |
                                  +----v----+
                                  |  Forge  |
                                  +----+----+
                                       |
                         private routed / WireGuard network
                                       |
                          versioned backend service APIs
                                       |
                               +-------v-------+
                               |  anvilmobile  |
                               | Raspberry Pi  |
                               +-------+-------+
                                       |
              +------------------------+-------------------------+
              |                 |                |               |
           FT-891              GPS          DigiRig/audio    local SQLite
          CAT/radio           serial             FT8         + map storage
```

## Process model on anvilmobile

The installed dashboard is started by `rolling-thunder.service`, which invokes
`deploy/rolling-thunder-autostart`.

The launcher enforces a 180-second minimum **system uptime**, not a fixed delay
after every service restart. Once the Pi has exceeded that uptime, restarting
the service launches the dashboard immediately.

The dashboard process composes the application through:
- `application_runtime.py` — service/adaptor/repository construction and lifecycle;
- `ui_main.py` — Tkinter/context/widget/controller composition;
- typed background polling and worker services;
- local SQLite repositories and retained-state caches.

## Pi concurrency rule

Tkinter is a presentation/command surface. Slow or blocking work belongs in
owned background services.

Do not perform provider HTTP, SQLite, filesystem, serial, CAT, map-tile, audio,
or long-running work directly inside UI refresh/callback paths.

Published UI-facing state should be immutable and cheap to read.

## Local-first data path

For local contact logging:

```text
operator action
   -> validated/staged contact
   -> local durable persistence
   -> UI/local state
   -> background synchronization
   -> Forge/Wavelog
```

Remote failure must not erase the locally committed contact.

For retained provider data, the established pattern is:

```text
provider/network candidate
   -> normalize/validate
   -> persist complete valid state
   -> publish immutable state
   -> client consumes retained API
```

The last good state may remain available while health reports a later failure.

## Forge process model

Forge intentionally separates backend concerns into callable services.

### Primary retained spot/weather/radar process

Entry point: `forge_spot_main.py`.

Responsibilities include:
- POTA provider polling;
- persistent DX Summit IRC;
- disabled persistent DXSpider fallback;
- retained provider-neutral spot snapshot;
- mobile location;
- weather;
- weather alerts;
- radar;
- health/API publication.

Provider/network work runs independently of HTTP request cadence.

### Callsign information process

Entry point: `forge_callsign_info_main.py`.

Combines configured QRZ identity, Wavelog latest-QSO history, and target weather
behind a compact programmatic API.

### Contact synchronization process

Entry point: `forge_contact_sync_main.py`.

Accepts normalized contact synchronization work and performs controlled,
idempotent Wavelog integration.

### Propagation environmental collector

Entry point: `forge_propagation_main.py`.

The independently supervised Phase 1 process is disabled by default and owns only
hourly HamQSL solar XML plus KC2G MUF(3000)/foF2 snapshot collection into its
dedicated SQLite database. It has a separate service identity, application root,
configuration, and StateDirectory. It has no API listener and no path to radio,
contact logging, Wavelog, contact sync, VOACAP, weather enrichment, or PSK Reporter.
Its staged deployment layout selects one immutable exact-40-SHA release through a
root-managed `current` symlink. A propagation-only component hook cannot select or
restart any other service. Its virtualenv is built at the final SHA path, and its
real pip-generated launcher must execute provider-free as the service identity before
`current` can change. Existing broken releases fail closed and are recovered with a
new reviewed SHA rather than in-place mutation. Central deploy-helper integration is
not installed and must wait for privileged inspection of the existing unreadable
helper.

### Propagation QSO analysis components (undeployed)

Entry point: `forge_propagation_qso_worker_main.py` for the double-gated VOACAP
worker. It owns a durable inbox, separate history database, and local status file,
but no service unit or completed-QSO producer. The separate PSK composition root owns
an authenticated private ingestion API, one scheduler, isolated orchestration/history
databases, and local status. Its three gates and production template default off, its
systemd assets are uninstalled, and it still has no authorized completed-QSO producer.
Neither component is part of the Phase 1 service, Pi runtime, FT8 execution, contact
synchronization, Wavelog, or local logging.

## Reusable backend boundary

Forge is a backend platform, not a hidden extension of one Tkinter screen.

Forge service contracts must:
- be callable by other authorized programs;
- use provider/domain terms rather than UI widget terms;
- expose independent health and error state;
- own provider credentials and protocol etiquette;
- tolerate multiple clients and client restart/refresh timing;
- preserve documented versioning/idempotency/retention guarantees.

## Persistent DX connection

The production DX source is DX Summit IRC.

Forge owns a single long-lived connection and continuously consumes the stream.
It responds to IRC keepalive traffic and reconnects with bounded backoff after
genuine failure.

Pi polling, HTTP requests, elapsed connection age, or a quiet band are not
reasons to reconnect.

## Shared runtime state

The most important cross-feature shared state includes:
- radio state;
- GPS/current location/grid;
- pending callsign;
- local contacts and sync state;
- shared POTA/DX snapshot and selection;
- callsign information;
- operator preferences;
- status messages;
- weather/map/radar retained state.

See `shared-component-contracts.md` and
`shared-component-consumers.md` before changing any of these boundaries.

## Recovery principle

Code checkout, runtime configuration, secrets, and durable databases are
separate assets.

A release/rollback point must identify:
- exact Git commit/tag;
- relevant installed service units;
- production configuration;
- database-safe backups/snapshots where required.

Experimental Codex work should begin only after such a restore point exists.
