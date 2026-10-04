# Ownership and Dependencies

## Purpose

Rolling Thunder is intentionally composed from shared services. A screen is a
consumer of capabilities, not necessarily the owner of the code it displays.

Use this document before making a feature-scoped change to determine where the
behavior belongs and what other features must be regression-tested.

## Ownership rule

Ownership follows the layer that defines the invariant:

- **domain/value modules** own validated meaning and identity;
- **application services/controllers** own use-case state transitions;
- **adapters/repositories** own hardware, provider, storage, and protocol details;
- **presentation modules** own formatting/layout only;
- **composition roots** wire dependencies but should not duplicate their policy.

When a feature uses a shared service, the feature may adapt or present that
service but must not silently redefine its contract.

## High-coupling roots

### `application_runtime.py`

Owns Pi-side construction and lifecycle of shared runtime services. It connects
radio, GPS, contact persistence/sync, Forge clients, map/radar/weather, POTA,
callsign intelligence, FT8, preferences, and status infrastructure.

Treat changes as cross-feature unless proven otherwise.

### `ui_main.py`

Owns full-screen UI composition, context wiring, physical-control routing,
refresh, overlays, and widget lifecycle. It is a consumer of many application
services. Do not move provider, persistence, CAT, or other blocking work here.

### `forge_spot_main.py`

Owns the lifecycle/composition of the primary retained Forge backend process.
Provider/session policy belongs in the provider/service modules it composes.

## Feature ownership

### POTA

Owns park-specific catalog/enrichment, POTA filters/metadata, worked state,
park markers, and POTA-specific staging/presentation.

Depends on:
- shared spot domain/selection/UI/tuning;
- radio state and `ReceiveTuningService`;
- GPS/location and map;
- pending callsign/contact logging;
- shared callsign-info overlay;
- Forge spot snapshots.

POTA does **not** own the shared contact-info overlay, shared spot identity,
general radio control, GPS, local contact durability, or Forge API.

### DX

Owns DX-specific filtering/presentation semantics at the shared-panel boundary.
Provider ingestion is owned by Forge.

Depends on:
- shared spot domain/selection/UI/tuning;
- radio state and `ReceiveTuningService`;
- pending callsign/contact logging;
- shared callsign-info overlay;
- Forge DX snapshot and provider health.

DX does not own the DX Summit connection. Forge does.

### Browse

Owns free-form receive tuning behavior and Browse-specific operator controls.

Depends on:
- shared radio state/control;
- pending callsign capture;
- current GPS/grid for logging;
- contact logging/commit;
- band/mode advisory;
- callsign-info overlay.

Browse must not create alternate implementations of those shared services.

### FT8

Owns native FT8 receive/decode activity, CQ eligibility, band control, timing,
explicit one-QSO authorization, bounded transmit session, QSO state machine,
attempt history/performance telemetry, FT8 logging adaptation, and FT8 UI.

Depends on:
- FT-891/CAT/audio adapters;
- shared GPS/grid snapshot at QSO start;
- shared local contact persistence;
- shared QRZ enrichment eligibility and background contact synchronization;
- dashboard context/control infrastructure;
- global status presentation where used.

The typed FT-891 adapter owns menu 11-05 encoding/readback. Existing FT8
receive/preparation services own REAR entry and MIC normal-context cleanup;
UI contexts do not issue CAT writes.

Transmit authority is intentionally FT8-scoped and bounded. It must not become a
general application PTT capability.

Completed FT8 contacts use `ContactLoggingService.commit_completed`. Runtime
composition records worked-today state and invokes the dashboard completion
handler, which requests the same `LogPanelController` background sync used by
ordinary and DMR commits. This callback runs only after durable persistence;
it must not perform network work on the FT8 worker.

### Repeaters

Owns local repeater catalog parsing, stable repeater identity, nearby filtering,
active overrides, repeater panel/controller, and typed repeater radio setup.

Depends on:
- shared current GPS for distance;
- radio/CAT typed capabilities;
- physical/context controls;
- shared status where applicable.

### DMR

Owns hotspot monitoring, talkgroup interpretation, activity/history, selection,
staged DMR QSO state, DMR presentation, and DMR-specific commit metadata.

Depends on:
- shared local contact persistence;
- dashboard control/navigation infrastructure.

DMR monitoring must not gain transmit authority.

### Weather and alerts

Pi owns presentation and local notification/deduplication state. Forge owns
provider access, normalization, retained state, and APIs.

Weather presentation is also consumed by the map information overlay, so
format/state semantics are shared beyond the WEATHER context.

### Map/radar

Owns primary map viewport, installed/cache/provider tile resolution, day/night
style, zoom, vehicle marker, map/GPS health projection, POTA marker projection,
and radar overlay lifecycle.

Depends on:
- shared GPS;
- retained weather for local temperature;
- POTA catalog for park markers;
- Forge radar backend.

The callsign mini-map is a separate contact-intelligence presentation path and
must not be casually merged with primary-map source rules.

### LOG

Owns recent-contact presentation and log-panel interaction. It does not own
contact persistence semantics; those belong to the shared contact repository and
logging services.

### SETTINGS

Owns operator-facing preference controls/presentation. Individual preference
meaning remains owned by the feature consuming the preference.

### AI

A navigation context exists, but the current implementation is reserved/
placeholder. Do not infer an implemented advisor architecture from the presence
of the context ID.

## Shared dependency graph

```text
GPS/current grid
  +--> map
  +--> contact logging
  +--> FT8 QSO snapshot
  +--> repeater distance
  +--> Forge mobile location
  +--> weather-alert relevance

Radio/CAT
  +--> Browse
  +--> POTA/DX receive tuning
  +--> FT8 preparation/transmit
  +--> repeater configuration
  +--> station status

Contact persistence
  +--> Browse/POTA/DX Commit
  +--> FT8 successful QSO logging
  +--> DMR staged logging
  +--> LOG screen
  +--> background Forge/Wavelog synchronization

Pending callsign
  +--> ordinary contact workflow
  +--> shared callsign-info overlay
  +--> POTA/DX preload
  +--> Browse voice/manual capture

Forge spot service
  +--> POTA
  +--> DX
  +--> provider health/status

Retained weather
  +--> WEATHER
  +--> map local-temperature presentation
```

## Regression expectation

A change to a leaf/presentation-only module can often use targeted tests plus the
full suite.

A change to a shared module requires:
1. its targeted tests;
2. tests for every named consumer affected by the contract;
3. the full repository suite;
4. operator/hardware acceptance when installed behavior changes.

See `shared-component-consumers.md` and
`shared-component-contracts.md`.
