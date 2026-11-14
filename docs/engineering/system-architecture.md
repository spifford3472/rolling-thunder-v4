# System Architecture and Runtime Topology

## Purpose

This document describes the current deployed shape of Rolling Thunder and the
major process/lifecycle boundaries an agent must preserve.

## Observed Forge installation versus feature gates (2026-11-13)

The descriptions below of staged/disabled-by-default source composition are **design and default-configuration descriptions**, not evidence that production units are absent or stopped. Read-only systemd inspection on Forge confirmed active processes for `rolling-thunder-forge-propagation.service`, `rolling-thunder-forge-propagation-qso-worker.service`, `rolling-thunder-forge-pskreporter.service`, and `rolling-thunder-forge-psk-evidence.service`. These observations establish service installation and process activity **only**; configured ingestion, provider egress, prediction and scheduling gates have not been independently verified. The separate `rolling-thunder-forge-psk-autoqueue.service` oneshot was failed (`ExecMainStatus=1`) while its timer remained scheduled. See `production-inventory-2026-11-13.md`. Do not infer feature enablement from `systemctl is-active`.

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

The launcher acquires a nonblocking advisory `flock` on a per-user instance lock before its uptime wait and inherits the lock into the dashboard via `exec`. Contending launches fail nonzero; an independently running unmanaged dashboard also fails closed rather than reporting a healthy managed service. The lock prevents duplicate launches through this launcher; independently launched programs that ignore the lock are detected only by the additional process check. The lock path defaults to `${XDG_RUNTIME_DIR:-/tmp}/rolling-thunder-ui-<uid>.lock` and can be overridden for isolated tests. Do not remove the lock file while a dashboard is running. The change does not alter the installed systemd unit or its restart policy.\n\nThe launcher enforces a 180-second minimum **system uptime**, not a fixed delay
after every service restart. Once the Pi has exceeded that uptime, restarting
the service launches the dashboard immediately.

The dashboard process composes the application through:
- `application_runtime.py` — service/adaptor/repository construction and lifecycle;
- `ui_main.py` — Tkinter/context/widget/controller composition;
- typed background polling and worker services;
- local SQLite repositories and retained-state caches.

## Shutdown diagnostic evidence (pending deployment)

The dashboard's SIGTERM handler sets an event; the Tk refresh loop initiates the
existing orderly-close worker. The worker now prints flushed `RT_SHUTDOWN`
records for `close_requested`, `worker_start`, each `step_start` and
`step_end` (with monotonic `duration_ms` and `result`), `cleanup_end`
(with total duration and error count), `worker_end`, and `destroy_root`.
Inspect `journalctl -u rolling-thunder.service` after a parked stop. A
`step_start` without its corresponding `step_end` identifies the last
entered callback when systemd kills a stuck process. These messages contain
step labels, not secrets or radio commands.

This is **diagnostic instrumentation only**: callbacks are still sequential,
and the service's installed `TimeoutStopSec=20` is unchanged. A hung callback
can prevent later cleanup, including radio disconnect. A clean `step_end`
does not independently prove RF-safe hardware state. No additional CAT/PTT
authority, automatic restart, service unit change, or deployment is implied.
The November 13 pre-instrumentation stop exceeded 20 seconds and was killed
by systemd; its exact blocking callback remains unknown. Perform offline
failure/blocked-step tests before any separately approved parked release.

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

## MeshCore read-only consumer contract

The opt-in collector and separate protected broker Unix socket retain all ingest/storage ownership. An additive public-only consumer library uses a separate Rolling Thunder or SCOUT credential to read bounded immutable messages; a manual CLI preview can classify unverified #traffic candidates without ACKs, UI blocking, network TCP or RF commands. No new deployed service/unit, scheduler, Tk caller or automatic alert pipeline exists in this source slice. Future consumer workers must explicitly isolate durable processing, cursor ACK, backoff and presentation outside Tk.

## MeshCore traffic geographic relevance (source-only, disabled)

Additive classified-text georeferences, existing published GPS sample reuse,
externally injected geocode evidence and conservative read-only route analysis
remain uncomposed. No additional GPS, provider calls, service, SQLite migration,
radio/RF authority or operator alerts. See meshcore-intelligence.md.

## MeshCore durable traffic consumer (staged supervision, inactive)

An uncomposed independent public-broker consumer can use the existing local Unix API and per-consumer token, storing processing/duplicate outcomes in a separate owner-only SQLite ledger and ACKing only after full commit. The standalone worker entrypoint supports single-run or cancellable polling with local locking, and has a staged `deploy/meshcore-traffic-worker.user.service` systemd user-unit template that is **not installed/enabled**. There is no additional live source, socket, network listener, GPS pipeline, Tk/UI thread, audio service, radio command, RF transmission, or traffic notification pipeline. Explicit later authorization and documented rollback are required to deploy or activate; see `meshcore-traffic-worker.md`.

## Runtime shutdown failure isolation

`ApplicationRuntime.stop()` attempts each configured worker and hardware cleanup in the established order even if an earlier step raises. It retains labeled errors and raises a grouped shutdown exception after attempting radio disconnect. The dashboard's existing cleanup runner reports this failure without skipping other dashboard cleanup. The runtime marks itself stopped only after radio disconnect returns successfully. This is best-effort cleanup, **not** a guarantee of hardware PTT deassertion or bounded shutdown when a cleanup method hangs; those require separate parked hardware validation.


## Runtime shutdown diagnostic evidence (November 2026)

The UI's `RT_SHUTDOWN` markers measure the outer orderly-close lifecycle.
`ApplicationRuntime.stop()` now additionally emits `RT_RUNTIME_SHUTDOWN`
markers at warning level: `phase=start`, `phase=step_start step='name'`,
`phase=step_end step='name' duration_ms=N result=ok|error`, and
`phase=end duration_ms=N errors=N`. These markers bracket each existing
runtime cleanup callback, including the final radio disconnect. They use
monotonic elapsed time; a missing `step_end` after a `step_start` identifies
the action active when systemd terminated a blocked shutdown. They are
diagnostics only: the cleanup order, exception isolation, radio authority,
systemd timeout, and existing deployment/rollback path are unchanged.
Do not interpret a successful parked stop as proof that intermittent blocking
is fixed. Use parked, RF-idle acceptance and inspect the service journal
for the first unmatched `step_start` before proposing targeted changes.
