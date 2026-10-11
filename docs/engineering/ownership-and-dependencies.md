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
Provider/session policy belongs in the provider/service modules it composes. It
also owns the single-listener composition of optional radar, weather-alert, and
style-aware map route layers; enabling map tiles must not create another server.

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

Owns DX-specific filtering/presentation semantics and callsign-plus-band
UTC-day worked state at the shared-panel boundary. Provider ingestion is owned
by Forge.

Depends on:
- shared spot domain/selection/UI/tuning;
- radio state and `ReceiveTuningService`;
- pending callsign/contact logging;
- successful local contact-commit notification;
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
- host chrony/NTP readiness with trusted shared GPS UTC as a read-only fallback;
- shared local contact persistence;
- shared QRZ enrichment eligibility and background contact synchronization;
- dashboard context/control infrastructure;
- global status presentation where used.

The typed FT-891 adapter owns menu 11-05 encoding/readback. Existing FT8
receive/preparation services own REAR entry and MIC normal-context cleanup;
UI contexts do not issue CAT writes.

The optional Forge PSK service boundary accepts only an authenticated confirmed event
containing the immutable durable FT8 `Contact` and its matching successful terminal
attempt, keyed by the shared stable UUID. It may use terminal time only to delay PSK
Reporter eligibility; correlation remains anchored to the immutable contact start.
The source/transport owner retains authentication and confirmation authority. The
service reads neither Pi nor contact-sync storage and runs on neither request path.
The independently scheduled provider worker owns two isolated SQLite databases and
non-secret status; its process, ingestion, and provider gates default off. The
lower-level analytics API retains its conservative missing-completion
fallback for non-orchestrated callers; invalid completion data fails closed.

The disabled completed-QSO propagation inbox is a separate Forge-owned consumer of
the immutable `Contact`. Its authenticated private API durably accepts complete
UUID-matched payloads without provider work; exact replays are accepted and changed
payloads fail closed. A separately scheduled bounded worker may perform VOACAP
correlation with identified lease recovery, retry isolation, dead letters, and local
status publication. Process, ingestion, and VOACAP gates default off. The staged
supervisor and typed one-attempt producer client do not make local commit, contact
sync, or Wavelog a producer; an authorized source still needs a durable outbox.

The Pi-side `completed_qso_producer.py` contract owns the source outbox. It
accepts only a durable immutable FT8 `Contact` plus its matching durable successful
terminal attempt, then stores one UUID-keyed event with independent VOACAP and PSK
delivery progress. Runtime calls this boundary only after both authoritative writes;
producer failure cannot roll either back. Network delivery is independently
scheduled and is not part of the FT8 terminal, contact-sync, or Wavelog path. Its
global and receiver gates default off, credentials come from protected environment
state, and each receiver must acknowledge the exact UUID before its destination
advances.

Phase B adds a separate all-terminal-attempt ledger after existing performance
durability. It snapshots frozen location/reports plus per-emission CAT configured
power from their existing owners, then optionally delivers through an independent
disabled scheduler. Forge commits the authenticated attempt before provider work;
its leased worker records append-only full-input-hash VOACAP inputs/runs/links and
read-only diagnostics. This path has no contact, Wavelog, ranking, UI, radio, or
transmit authority.

Phase C1 adds Forge-owned analytics provenance beside, not inside, the immutable
attempt payload. Documented synthetic/test UUIDs are auditable processing and
training exclusions. Unknown provenance preserves Phase B processing compatibility
but is not training evidence. No Pi producer, contact, Wavelog, ranking, UI or radio
ownership changes.

Phase C2 adds a Forge-owned read-only consumer of declared inbox/history snapshots.
It reconciles existing immutable retrospective VOACAP evidence into a privacy-
minimized versioned coverage artifact and fails closed on identity, provenance,
foreign-key, or training-invariant violations. It owns no provider, scheduler,
provenance classification, lease, Pi, UI, contact, Wavelog, ranking, or radio path.
The existing Forge worker remains the sole correlation owner; it records deterministic
missing-input directions before provider work so forward retry exhaustion cannot
erase the reverse unknown-power skip.

The receive service also owns configured-local-callsign addressed-grid/report
capture; the FT8 panel owns answer/ignore presentation state. Button 2 preserves
the accepted inbound record and enters the QSO controller's explicit responder
start phase; a failed start preserves the alert, and completed-QSO continuation
suppression is bounded to six periods for the same remote. It does not synthesize
CQ activity. Adaptive initial power is
computed from the QSO-frozen Maidenhead grids and applied once by the existing
preparation service. Configured-power telemetry uses typed FT-891 CAT readback
and remains distinct from raw transmit-meter values.

Transmit authority is intentionally FT8-scoped and bounded. It must not become a
general application PTT capability.

Completed FT8 contacts use `ContactLoggingService.commit_completed`. Runtime
composition records worked-today state and invokes the dashboard completion
handler, which requests the same `LogPanelController` background sync used by
ordinary and DMR commits. This callback runs only after durable persistence;
it must not perform network work on the FT8 worker.

Receive diagnostics may query local chrony status and consume the published GPS
UTC observation, but they do not own NTP configuration, GPS acquisition, system
clock writes, or the privileged GPS clock-correction helper. Optional comparison
and PCM retention must remain explicitly time/count bounded.

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

Contact weather is part of the immutable payload, not work owned by contact sync.
The Pi freezes fresh, matching already-published callsign target weather and non-stale
retained local weather proven against the contact's frozen local coordinates (or local
grid when coordinates are unavailable) during both ordinary and FT8 local commit. A separate
background history/propagation worker may reuse the provider-neutral
`WeatherProvider` abstraction, but the Wavelog synchronization path performs no
public weather request and uploads the weather fields it receives unchanged.

### Map/radar

Owns primary map viewport, installed/cache/provider tile resolution, day/night
style, zoom, vehicle marker, map/GPS health projection, POTA marker projection,
and radar overlay lifecycle.

Depends on:
- shared GPS;
- retained weather for local temperature;
- POTA catalog for park markers;
- Forge radar backend.
- optional Forge style-aware callsign-map route backed by a local renderer.

The callsign mini-map is a separate contact-intelligence presentation path and
must not be casually merged with primary-map source rules. It remains worldwide,
online-only, and cache-isolated, but mirrors the authoritative primary map style
through the shared style fan-out used by both solar automation and Settings.
Zoom and installed-package availability remain primary-map-only concerns.

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
  +--> optional asynchronous Forge propagation-history ingestion

Forge contact synchronization owns Wavelog-specific station management. It derives
dynamic routing only from the immutable contact's frozen grid/state/CQ/ITU fields,
selects the exact station before the UUID-ledger claim, and preserves legacy
`Mobile` fallback for insufficient historical/location context. Its Forge SQLite
repository also owns the durable verified dynamic-name -> Wavelog ID/UUID recovery
binding needed when `active_log_only` hides an unlinked created station. Browse,
POTA, DX, FT8, and DMR do not own or fork station-selection policy.

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


## Known/friend callsign classification

Forge callsign intelligence owns durable friend data and private comments.
`known_callsign_client.py` owns Pi background snapshot polling and expiring
classification. Presentation consumes immutable status through
`friend_presentation.py`; it never changes canonical identities or commands.
Consumers are POTA/DX, FT8 CQ, shared pending/Browse callsign, contact overlay,
DMR audio/history and LOG. See `../KNOWN_CALLSIGNS.md`.

CP3.1 retry extensions consume the published FT8 receive target-activity state
inside the coordinator; no additional receive observer or UI policy is created.
The bounded hardware transmit executor suppresses adaptive power increases on
explicit extension periods, independently of the display banner.
