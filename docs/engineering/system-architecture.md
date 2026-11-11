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

### Propagation completed-QSO service (staged, disabled)

Entry point: `forge_propagation_qso_worker_main.py` for the double-gated VOACAP
worker and independently gated authenticated ingestion listener. It owns a durable inbox, separate history database, local status file, hardened systemd unit, isolated exact-SHA release tree, and private production paths. The separate PSK Reporter composition has an authenticated bounded FT8 event API, scheduler, isolated orchestration and history databases, provider-free local status, hardened service unit, and its own exact-SHA release tree. The Pi can optionally feed both through a distinct durable outbox and background scheduler, but every source, ingestion, and provider gate defaults off. Neither receiver is part of Phase 1, contact sync, Wavelog, local logging, or radio execution.

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


### MeshCore passive collection (opt-in, disabled by default)

A dedicated version-1 MeshCore SQLite database provides identity and observation history, leaving Rolling Thunder's existing contact database at schema 22. Pure parsing, a bounded worker, dedicated persistence and an exclusive USB listener are composed in `application_runtime.py` **only** when `meshcore_passive.enabled: true`. With the default `false`, no MeshCore port is opened and no MeshCore database is created. The USB receive service runs off the Tk thread, reuses published immutable GPS and has no command-writing interface. The existing GPS owner is the sole intended source of receiver coordinates. Physical USB-by-path identity, parked hardware acceptance, sustained receive evidence and RF-power/separation review are prerequisites to production enablement. The code itself can be deployed inactive. Firmware-managed ordinary mesh transmissions are owner-permitted; application-originated RF remains disallowed. See draft architecture PR #384.

## Optional MeshCore message broker

The independent MeshCore user-service retains sole USB serial ownership. Explicit operator opt-in adds a bounded host-local serial dequeue state machine, separate protected SQLite public/personal/quarantine inbox and a *second* token-scoped local Unix read/ack socket. The existing passive observation DB/socket and published GPS snapshot are unchanged. No new TCP ports, firewall configuration, RF commands, or additional process. A source deploy alone does not activate the broker; refer to `meshcore-message-broker.md`.
