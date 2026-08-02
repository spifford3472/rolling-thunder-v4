# Rolling Thunder v4 Architecture

## Purpose

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system.
Its primary client runs on the Raspberry Pi 4 named `anvilmobile`.

The application supports local contact logging, voice callsign capture, physical
operator controls, POTA assistance, GPS state, Yaesu FT-891 state and
receive-only control, connectivity status, park-detail mapping, and optional
network enrichment. Forge may provide Home Station Platform services, but the Pi
client remains authoritative for mobile operation and must remain useful when
Forge, WireGuard, cellular service, or the public internet is unavailable.

The approved `docs/RollingThunder_v4.1.0_Architecture_Specification.md` remains
the product architecture baseline. This document describes the current
implemented software architecture and the near-term integration direction.

## Design Goals

- Remain useful without internet, WireGuard, or Forge.
- Preserve completed contacts in durable local storage before remote work.
- Keep hardware-specific details outside application and UI logic.
- Support mock hardware for development and automated testing.
- Avoid blocking serial, audio, GPS, database-maintenance, or network work in the
  Tkinter thread.
- Keep configuration typed, centralized, actionable, and free of secrets.
- Route graphical and physical controls through the same application-command
  boundaries.
- Fail visibly and safely when hardware or network services disappear.
- Add no software PTT, MOX, keying, or unattended transmit authority.
- Make each subsystem independently testable without physical hardware or
  internet access.

## Current High-Level Components

```text
+--------------------------------------------------------------------+
| Raspberry Pi 4: anvilmobile                                        |
|                                                                    |
|  +-------------------------- Tkinter UI -------------------------+  |
|  | persistent dashboard | POTA panel | overlays | status ticker |  |
|  +------------------------------+--------------------------------+  |
|                                 |                                   |
|  +---------------- Application Controllers ---------------------+  |
|  | operator commands | logging | POTA selection/tune intent      |  |
|  | active-panel commands | navigation | connectivity presentation |  |
|  +------------------------------+--------------------------------+  |
|                                 |                                   |
|  +------------------- Runtime / Application Services ------------+  |
|  | radio polling | GPS polling | speech | contact sync            |  |
|  | POTA polling/cache | enrichment | network keepalive            |  |
|  | physical-control dispatch and lifecycle                         |  |
|  +------------------------------+--------------------------------+  |
|                                 |                                   |
|  +-------------------- Typed Ports and Domain --------------------+ |
|  | Radio | CatTransport | GPSReceiver | ControlSource             | |
|  | repositories | remote clients | immutable state/value objects  | |
|  +------------------------------+--------------------------------+ |
|                                 |                                   |
|  +-------------------------- Adapters ----------------------------+ |
|  | FT-891 CAT | serial GPS | ESP32 serial | mock hardware         | |
|  | SQLite | HTTP/Home Platform | POTA | QRZ | weather | boundaries | |
|  +----------------------------------------------------------------+ |
+----------------------------------+---------------------------------+
                                   |
                        optional network connectivity
                                   |
                      +------------v-------------+
                      | Home Station Platform    |
                      | and external data APIs   |
                      +--------------------------+
```

## Layer Responsibilities

### Domain and Value Types

Domain code represents stable project concepts and validation rules, including:

- callsign and Maidenhead grid
- frequency, band, and radio mode
- radio and GPS state
- contact and synchronization state
- POTA spots, park references, and tune intent
- immutable presentation and service snapshots

Domain code must not depend on Tkinter, pyserial, HTTP clients, SQLite details,
Raspberry Pi device paths, or network availability.

### Ports and Protocols

External capabilities are exposed through small typed interfaces. Current
examples include:

- `Radio`
- `CatTransport`
- `GPSReceiver`
- `ControlSource`
- contact and retry repositories
- Home Station Platform clients
- POTA, QRZ, weather, image, and boundary providers

Ports expose only capabilities required by Rolling Thunder. They must not mirror
an entire vendor API or allow an adapter to bypass application safety policy.

### Adapters

Adapters contain hardware, persistence, and network details. Current examples
include:

- `Ft891Radio` over a typed CAT transport
- `SerialGPSReceiver` for checksummed NMEA data
- `SerialControlSource` for ESP32 events
- deterministic mock radio, GPS, and control sources
- SQLite contact, retry, and POTA-cache repositories
- HTTP Home Station Platform, POTA, QRZ XML, Open-Meteo, Census, and
  geoBoundaries adapters

Operating-system paths such as `/dev/ttyUSB0` and `/dev/ttyACM0` belong only in
typed configuration and adapter composition.

### Application Services and Controllers

Application services coordinate use cases without knowing concrete hardware.
Current examples include:

- pending-callsign capture, Commit, and Discard
- durable local contact creation
- background contact synchronization
- radio and GPS polling
- POTA spot retrieval, filtering, ranking, selection, and receive-only tune
  intent
- physical-control event mapping, gating, and dispatch
- POTA enrichment and timed detail-overlay state
- navigation and context-sensitive panel commands

The shared operator-command boundary is important: physical buttons and the GUI
invoke the same Commit, Discard, Voice, navigation, and active-panel behavior.
There is no parallel ESP32-only application path.

### User Interface

The Tkinter UI presents immutable state and invokes application controllers. It
must not:

- open serial or audio devices directly
- parse NMEA, CAT, or ESP32 protocol messages
- issue raw CAT commands
- perform blocking HTTP requests
- access SQLite implementation details
- decide retry or synchronization policy
- grant physical controls additional authority

UI refreshes may read cached snapshots and drain bounded, nonblocking application
queues. Slow hardware and network work belongs in workers owned by services.

## Runtime Composition and Lifecycle

`ApplicationRuntime` is the current composition root for radio, GPS, logging,
connectivity, POTA, and enrichment services. The UI composes additional
presentation controllers and the physical-control source lifecycle around that
runtime.

Startup and shutdown must be explicit:

1. Load and validate configuration.
2. Build mocks or physical adapters through factories.
3. Connect hardware through the adapter boundary.
4. Start lifecycle-managed polling and worker services.
5. Start UI refresh and bounded event dispatch.
6. On shutdown, stop producers before closing adapters and the UI.

A failed optional service must not prevent unrelated local functions from
starting. Hardware errors must result in visible disconnected, degraded, or
error state rather than an application crash or hidden stale state.

## Configuration and Secrets

`ApplicationConfig` is the authoritative typed YAML boundary. It currently
covers:

- operator identity
- mock or physical hardware mode
- radio and GPS device paths
- speech configuration
- Home Station Platform and network keepalive settings
- POTA retrieval settings
- physical-control transport, limits, and mappings
- local database and backup paths

Real hardware mode currently requires both radio and GPS device paths. Milestone
10 may refine hardware enablement so GPS and radio can be integrated and tested
in separate focused phases without weakening validation.

Secrets are not stored in YAML or Git. Optional QRZ credentials are loaded once
through the centralized application-secrets boundary from local environment
variables. Secret values, session keys, and authentication responses must not be
logged or included in tests, issues, pull requests, or chat.

## Local Logging and Offline Operation

The Pi client is local-first:

1. A callsign is captured or selected and held as pending state.
2. No QSO is written until the operator explicitly presses Commit.
3. Commit captures the valid current operating state and writes immediately to
   SQLite.
4. The contact remains locally available regardless of network state.
5. Synchronization occurs later through an idempotent remote boundary with
   persisted retry eligibility.
6. Remote failure never removes or invalidates the local contact.

Discard clears the pending callsign and writes no QSO.

## Radio Architecture and Safety

The `Radio` boundary and `Ft891Radio` adapter support the approved safe scope:

- connect and disconnect
- read current VFO-A frequency and receive mode
- background state refresh
- set frequency and receive mode
- deterministic band changes
- explicit receive-only POTA tune execution after the existing confirmation
  intent flow

The radio state always reports `transmitting=False` in this scope. No component
may expose PTT, MOX, CW keying, voice keying, automatic transmission, or
unattended transmit control. Voice recognition and ESP32 events are operator
input mechanisms, not radio-control authority.

Milestone 10 Phase B validates the existing adapter with the installed FT-891.
The sequence is read-only connection and polling first, then explicit
receive-only changes. Hardware validation must be performed by the repository
owner before merge.

## GPS Architecture

The `GPSReceiver` boundary has mock and serial implementations. The serial
adapter currently reads checksummed `GPGGA` and `GNGGA` sentences and provides:

- connection state
- fix state
- latitude and longitude
- altitude
- satellite count
- immutable update time

GPS polling runs independently of Tkinter and converts temporary read or parse
failures into visible state while allowing recovery.

Milestone 10 Phase A validates the real receiver first. Add support for other
NMEA sentences only when live observation demonstrates a requirement. Trusted
GPS UTC, speed, heading, movement hysteresis, and commit-time GPS capture should
follow as focused changes after the base receiver path is stable.

## Physical Controls

The physical-control architecture is input-only and fail-closed:

```text
ESP32 firmware
    -> RTCTRL/1 EVENT lines
    -> bounded nonblocking serial source
    -> typed input events
    -> duplicate/repeat gate
    -> configuration-driven action mapper
    -> shared operator-command controller
    -> existing application behavior
```

The ESP32 emits opaque identifiers; it cannot name arbitrary Python functions or
request PTT. The Pi owns all mappings and the safety allowlist.

The implemented panel supports:

- Voice, Commit, and Discard
- Panel and Context short/long presses
- direct context selection and context-sensitive panel commands
- encoder clockwise/counterclockwise movement
- encoder short activation and long back/cancel behavior

Malformed, oversized, unsupported, duplicate, rapidly repeated, and incomplete
messages fail closed. Startup failure leaves the UI operational without physical
controls.

The current connection is intentionally one-way from ESP32 to Pi. Future LED
feedback requires a separate typed output protocol and lifecycle. It must not be
bolted onto the input parser or driven directly from Tkinter widgets.

## POTA, Mapping, and Enrichment

The core POTA workflow is provider-independent and remains usable from cached
state when the public endpoint is unavailable. It includes filtering, ranking,
selection, explicit tune intent, receive-only execution, and a durable SQLite
cache.

Optional enrichment is background-only and independently degradable:

- QRZ XML callsign names and optional primary profile photos
- Open-Meteo temperature, WMO condition, day/night state, and park-local time
- U.S. Census generalized state outlines
- geoBoundaries DX first-level subdivision outlines with country fallback
- locally rendered park markers and callsign badges

The UI never performs these HTTP requests. Results are cached as immutable
snapshots. Failure of mapping, QRZ, or weather must not hide successful results
from the other providers or affect logging, radio state, or POTA spot selection.
See `docs/POTA_ENRICHMENT.md` for configuration and operator behavior.

## Concurrency and Reliability

Potentially blocking work must not execute in the UI thread, including:

- serial GPS and CAT operations
- speech capture and recognition
- HTTP requests and image normalization
- synchronization and retry work
- database maintenance
- long calculations

Every worker or polling service must define:

- startup and shutdown ownership
- timeouts
- cancellation or stop behavior
- stale-state semantics
- device removal and recovery behavior
- bounded queues, reads, or batches
- observable error state

Avoid adding an event bus merely to match the long-term specification. Introduce
it when demonstrated coordination needs justify the migration and the change can
be delivered incrementally.

## Development and Approval Model

Development occurs through focused branches and pull requests, never directly on
`main`.

The expected division of responsibility is:

- the AI assistant acts as Chief Software Architect and Senior Technical Lead
- the AI assistant inspects GitHub, designs the slice, edits code and tests,
  updates documentation, runs available validation, and opens a focused draft PR
- the repository owner reviews behavior, performs real hardware and full-screen
  tests on `anvilmobile`, requests changes when needed, and explicitly approves
  and merges larger changes
- GitHub Actions must pass before merge

The normal loop is:

```text
clean main
    -> focused feature/docs branch
    -> implementation, tests, and documentation
    -> Ruff, MyPy, pytest, pre-commit
    -> draft pull request
    -> CI
    -> owner hardware/UI validation
    -> owner approval and merge
    -> synchronize and delete the feature branch
```

## Near-Term Delivery Order

The next milestone is executed as separate, reviewable phases:

1. Real GPS integration and live validation on `anvilmobile`.
2. Real Yaesu FT-891 CAT integration and safe receive-only validation.
3. Broader live mapping, movement presentation, contact visualization, and
   selected operating intelligence.

Do not combine the first GPS and FT-891 hardware changes in one branch or pull
request. Each phase must preserve mock mode and deterministic tests.
