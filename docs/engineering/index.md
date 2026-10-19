# Rolling Thunder Engineering Guide

## Purpose

This directory is the current-code engineering map for Rolling Thunder v4. It exists to let a human or coding agent determine ownership, dependencies, shared consumers, safety boundaries, and required regression coverage before editing code.

This guide describes the implemented repository rather than an aspirational architecture. Existing subsystem documents remain authoritative for detailed protocols and acceptance history where linked below.

## Engineering document set

- `r1-a-ui-timing.md` — bounded UI timing aggregates, R1-C2 correlated slow-refresh diagnostics, validation and interpretation limits.

- `antenna-reference-rf-exposure.md` — manually maintained typed-YAML antenna,
  installation, mode and scenario authority; versioned FCC MPE plane-wave advisory
  calculator; strictly read-only disabled-by-default dashboard; dormant schema-21
  compatibility storage; limits and acceptance tasks.
- `voacap-ft8-phase-a.md` — VOACAP/FT8 Phase A as-built audit, schema decisions, and review gates (design only).
- `voacap-ft8-phase-b.md` — additive attempt ledger, Forge inbox, immutable
  VOACAP correlation, migration/rollback, and offline acceptance.
- `voacap-ft8-phase-c.md` — Phase C1 UUID-keyed synthetic/test exclusion, C2
  read-only retrospective coverage, C3 copied-database audited historical replay,
  conservative provenance, baseline activation gates, and full field-report design
  (no scheduler or activation).
- `voacap-ft8-phase-c4.md` — disabled/uncomposed Forge baseline sampling domain,
  immutable plans and response deduplication, bounded offline acceptance, Gate 0
  gaps, blocked live smoke runbook, and C5 read-only shadow design.
- `voacap-ft8-phase-c5.md` — Forge-only strict as-of evidence pairing, offline
  descriptive evaluation, immutable non-actuating shadow advisory, readiness policy,
  and separately approved C4 pilot plan.

- `system-architecture.md` — deployed topology, process/lifecycle, local-first and recovery boundaries.
- `ownership-and-dependencies.md` — feature ownership and dependency graph.
- `shared-component-contracts.md` — cross-feature invariants that feature agents must not casually change.
- `shared-component-consumers.md` — consumer matrix for high-risk shared components.
- `forge-services.md` — reusable Forge backend/process/API rules.
- `source-file-index.md` — exhaustive catalog of all Python source modules.
- `test-index.md` — test ownership and validation/live-acceptance guidance.
- `AGENTS.md` — maintenance rules for this documentation.
- `codex-deployment-workflow.md` — Codex branch discipline, explicit merge/deploy authorization and guarded release paths.

## How to use this guide

Before editing code:

1. identify the feature or service in this index;
2. read its ownership boundary and shared dependencies;
3. inspect `shared-component-consumers.md`;
4. inspect the source modules and tests named by the relevant subsystem document;
5. read any Forge or hardware contract involved;
6. make the smallest scoped change;
7. update these engineering documents if ownership, dependencies, contracts, or consumers change.

A screen is not automatically the owner of everything displayed on it. UI contexts frequently consume shared services owned elsewhere.

## Runtime topology

### anvilmobile

`anvilmobile` is the Raspberry Pi mobile runtime. Its production checkout is:

```text
/home/geoff/projects/rolling-thunder-v4
```

The Pi owns:

- full-screen Tkinter presentation and context navigation;
- physical control dispatch;
- FT-891 and DigiRig-adjacent local hardware behavior;
- GPS acquisition and current mobile position/grid;
- local contact persistence and retry metadata;
- local-first operator workflow;
- retained/cached Forge client state;
- FT8 receive/QSO orchestration and bounded transmit authority;
- map presentation and installed/offline map usage.

The Pi must remain useful when Forge or public networks are unavailable.

### Forge

Forge owns reusable backend services and provider-facing work that should not run in the dashboard process. Current Forge responsibilities include:

- POTA/DX spot aggregation and durable snapshot publication;
- persistent DX Summit IRC ingestion;
- disabled-by-default persistent DXSpider fallback;
- QRZ enrichment;
- retained weather and weather alerts;
- radar;
- mobile-location intake;
- callsign/contact intelligence;
- contact synchronization to Wavelog.
- disabled-by-default, independently supervised HamQSL/KC2G environmental history.

Forge services are backend capabilities, not Rolling-Thunder-screen implementations. Their APIs should remain usable by other authorized programs.

## Major application composition roots

### `application_runtime.py`

Primary Pi composition root. It constructs and owns radio, GPS, polling, local logging, map, Forge clients, weather, callsign intelligence, FT8 services, preferences, synchronization, and lifecycle state. Changes here can affect many features even when the visible request is screen-specific.

### `ui_main.py`

Full-screen dashboard composition and Tkinter orchestration. It wires contexts, widgets, controllers, physical controls, refresh behavior, overlays, and active-panel commands. It is a high-coupling presentation root and should not accumulate provider, persistence, or hardware policy.

### `forge_spot_main.py`

Composition/lifecycle root for the retained Forge spot/weather/radar service. It owns service startup/shutdown ordering and provider composition but should delegate protocol/provider logic to dedicated modules.

### `forge_contact_sync_main.py`

Independent Forge contact-sync process. It is intentionally deployment-isolated from the spot/weather runtime.

### `forge_callsign_info_main.py`

Independent Forge callsign/contact-intelligence process. It keeps QRZ, Wavelog history, and target-weather provider work off the Pi UI process.

### `forge_propagation_main.py`

Independent disabled-by-default Forge HamQSL/KC2G environmental collector. It owns
only its dedicated propagation database and has no radio, contact-sync, Wavelog, or
QSO-ingestion path.

### `forge_propagation_qso_worker_main.py`

Independent disabled-by-default completed-QSO service. It owns an authenticated,
bounded private ingestion listener, durable inbox, separate history/status paths,
and double-gated VOACAP worker. A typed producer client defines the reusable
transport, but no local-logging, contact-sync, Wavelog, or live-contact source is
composed into it.

### `forge_pskreporter_worker_main.py`

Independent triple-gated completed-FT8 PSK Reporter service. It composes the
existing durable orchestration and analytics contracts with an authenticated,
bounded private event API, one scheduler, isolated orchestration/history databases,
and atomic local diagnostics. Its process, ingestion, and provider gates default
off; no completed-QSO producer is wired into the Pi or another Forge service.

## Feature ownership map

### POTA and DX

POTA and DX share provider-neutral spot presentation, stable selection, tuning, and active-panel command paths. POTA additionally owns park-specific enrichment, catalog behavior, worked state, and park map markers.

Primary shared modules include:

- `spot_domain.py`
- `spot_selection.py`
- `shared_spot_panel.py`
- `shared_spot_ui.py`
- `shared_spot_tuning.py`
- `shared_spot_tune_status.py`
- `active_panel_commands.py`
- `receive_tuning.py`

POTA-specific modules include the `pota_*.py` family and `shared_pota_contact.py`.

DX provider ingestion lives on Forge and must not be reintroduced as direct Pi/provider scraping.

Read: `docs/SHARED_SPOT_DOMAIN.md`, `docs/FORGE_SPOT_SERVICE.md`.

### Callsign/contact information overlay

The contact-information overlay is shared operator infrastructure, not a POTA-owned popup. It consumes pending callsign state plus optional POTA location context and Forge intelligence. A feature agent must not redesign it without reviewing all consumers.

Primary modules:

- `callsign_info.py`
- `callsign_info_client.py`
- `callsign_info_service.py`
- `callsign_info_ui.py`
- `forge_callsign_info*.py`
- `qrz_profile_image.py`
- `qrz_xml.py`

Read: `docs/CALLSIGN_INFO.md`.

### Contact logging and synchronization

Local QSO commit is authoritative and must remain independent of network success. Remote sync is background/retry-safe.

Primary modules:

- `contact_logging.py`
- `contact_commit_controller.py`
- `contact_repository.py`
- `contact_retry.py`
- `contact_sync.py`
- `contact_metadata.py`
- `contact_qrz_enrichment.py`
- `contact_backup.py`
- `contact_export.py`
- `contact_import.py`
- `log_panel.py`
- `log_ui.py`
- `forge_contact_sync*.py`

Read: `docs/FORGE_CONTACT_SYNC.md`.

### FT8

FT8 is a dedicated subsystem with its own typed domain, receive path, encoder/decoder, timing, QSO state machine, bounded transmit authorization/session boundary, performance telemetry, logging adapter, and UI.

Primary code lives under `src/rolling_thunder/ft8/` plus:

- `ft8_ui.py`
- `ft8_widgets.py`
- `ft8_active_panel_commands.py`
- `ft891_cat.py`
- `ft891_radio.py`

FT8 transmit authority is intentionally narrow. Do not generalize it into application-wide PTT authority.

Read: `docs/FT8_ENGINEERING_GUIDE.md`, `docs/FT8_ARCHITECTURE.md`.

The optional source-owned completed-QSO producer is a post-durability FT8 adapter
with an independent local SQLite outbox and per-consumer retry state. It is inactive
by default; production composition creates authenticated clients and a background
scheduler only under explicit configuration. Read:
`docs/COMPLETED_QSO_PRODUCER.md`.

### Browse

Browse provides free-form receive tuning and contact logging. It uses shared radio state, callsign capture, contact logging, current GPS/grid, band advisory, and optional callsign intelligence. Browse does not own those shared services.

Primary module: `browse_control.py`, with composition in `ui_main.py`.

### Repeaters

The repeater subsystem owns local six-meter repeater data, stable identity, nearby filtering, active overrides, presentation, and typed radio configuration workflow.

Primary modules are the `repeater_*.py` family and `fm_repeater.py`.

Read: `docs/REPEATERS.md`, `docs/REPEATER_SINGLE_PRESS_WORKFLOW.md`, `docs/FT891_FM_REPEATER_CAPABILITIES.md`.

### DMR

DMR owns hotspot monitoring, activity/caller state, selection, staged local contact workflow, and DMR-specific presentation. It shares local logging and dashboard command infrastructure where appropriate.

Primary modules are the `dmr_*.py` family.

Read: `docs/DMR_HOTSPOT.md`.

### Weather and alerts

Weather presentation consumes retained Pi Forge weather state. Provider calls and normalization live on Forge; Tkinter renders immutable state only.

Primary Pi modules:

- `weather_panel.py`
- `weather_ui.py`
- `weather_alert_panel.py`
- `weather_alert_viewport.py`
- `weather_alert_audio.py`
- `pi_forge_weather*.py`

Forge provider/service modules use the `forge_weather*.py`, `forge_open_meteo_weather.py`, and `forge_nws_weather_alerts.py` families.

Read: `docs/WEATHER_PANEL.md`, `docs/WEATHER_ALERTS.md`, `docs/FORGE_WEATHER_API.md`.

### Maps and radar

Map code owns local/offline tile resolution, viewport behavior, solar/day-night style, zoom, GPS presentation, POTA marker projection, and optional radar overlay. Callsign mini-map behavior is deliberately separate from the primary installed/offline map path.

Primary modules:

- `live_map.py`
- `live_map_service.py`
- `live_map_ui.py`
- `live_map_info.py`
- `map_*.py`
- `pota_map_markers.py`
- `radar_*.py`
- `live_radar_service.py`
- `forge_radar*.py`

Read: `docs/LIVE_MAP.md`, `docs/MAP_ZOOM.md`, `docs/WEATHER_RADAR.md`.

### GPS and location

GPS is shared by mapping, current-grid logging, FT8, repeater distance, Forge location publishing, weather applicability, and other mobile context. A screen must not create its own GPS interpretation.

Primary modules:

- `gps.py`
- `serial_gps.py`
- `gps_polling.py`
- `maidenhead.py`
- `pi_forge_location_publisher.py`
- `forge_mobile_location*.py`

Read: `docs/REAL_GPS_INTEGRATION.md`, `docs/GPS_UTC.md`, `docs/GPS_CLOCK_SYNC.md`.

### Radio control

`Radio`, CAT transport, FT-891 adapter, radio polling, band resolution, and `ReceiveTuningService` form shared radio infrastructure. Feature code should request typed actions rather than issue raw CAT.

Primary modules:

- `radio.py`
- `cat_transport.py`
- `pyserial_cat_transport.py`
- `ft891_cat.py`
- `ft891_radio.py`
- `radio_polling.py`
- `radio_band.py`
- `receive_tuning.py`

Read: `docs/REAL_FT891_INTEGRATION.md`.

### Physical controls and navigation

Physical input is normalized into typed actions and routed through shared application command boundaries. Feature-specific active-panel command controllers interpret only the actions appropriate to their context.

Primary modules:

- `physical_controls.py`
- `control_protocol.py`
- `control_dispatcher.py`
- `control_source_factory.py`
- `control_source_lifecycle.py`
- `serial_control_source.py`
- `context_navigation.py`
- `operator_commands.py`
- `*_active_panel_commands.py`

## Current dashboard contexts

The current stable context IDs are:

1. POTA
2. DX
3. BROWSE
4. FT8
5. REPEATERS
6. AI
7. WEATHER
8. SETTINGS
9. LOG
10. DMR
11. ANTENNAS / RF EXPOSURE (only when `antenna_reference.enabled` is true)

The Operator's Guide describes user-facing behavior for each context. Context order and keyboard development shortcuts are defined in `context_navigation.py`.

## Shared-component dependency guide

See `shared-component-consumers.md` before editing any shared module.

## Forge engineering guide

See `forge-services.md` for process boundaries, ports, provider ownership, persistence, and the reusable-service rule.

## Detailed source catalog

See `source-file-index.md`. The source catalog should be updated whenever modules are added, removed, renamed, or materially change responsibility.

## Existing authoritative subsystem documents

Do not duplicate protocol details unnecessarily. Use these documents for deeper behavior:

- `docs/FT8_ENGINEERING_GUIDE.md`
- `docs/FT8_ARCHITECTURE.md`
- `docs/SHARED_SPOT_DOMAIN.md`
- `docs/FORGE_SPOT_SERVICE.md`
- `docs/FORGE_CONTACT_SYNC.md`
- `docs/WAVELOG_STATION_PROFILE_RESOLVER_DESIGN.md`
- `docs/CALLSIGN_INFO.md`
- `docs/LIVE_MAP.md`
- `docs/WEATHER_PANEL.md`
- `docs/WEATHER_ALERTS.md`
- `docs/WEATHER_RADAR.md`
- `docs/REPEATERS.md`
- `docs/DMR_HOTSPOT.md`
- `docs/PI_AUTOSTART.md`

## Change-safety checklist

Before changing code, answer:

- Who owns this behavior?
- Is the visible screen merely a consumer?
- What other contexts consume the same module/state/service?
- Does the change alter radio or transmit authority?
- Does it alter local persistence or remote synchronization semantics?
- Does it alter a Forge API or provider lifecycle?
- Can the Pi still degrade safely if Forge/network disappears?
- Which targeted tests prove the behavior?
- Which cross-feature regression tests are required?
- Which engineering and operator documents must be updated?

### FT8 selected-target status (CP3.1 Step 2)

The FT8 map banner consumes the existing read-only target activity snapshot from `FT8ReceiveService`, synchronized to the highlighted browser target or active QSO remote callsign on the UI refresh path. `ft8.status.target_activity_status` formats fresh decoder-attributed remote observations separately from the white local operator status. The live map paints a green second line inside the unchanged banner bounds; it does not own decode, selection, RF authority, or retry policy.

- [VOACAP/FT8 Phase C5.1 scheduled readiness inventory candidate](voacap-ft8-phase-c51.md) — offline read-only, non-actuating, requires separate deployment helper and verified evidence adapter.

- [FT8 scientific power-experiment protocol](voacap-ft8-power-experiments.md) — pre-registered control/lower-power trial, future qualification certificate, and strict RF/UI safeguards (disabled).

- [C5.2 Forge prospective source-audit checkpoint](voacap-ft8-phase-c52.md) — read-only v2 FT8 evidence inventory and as-of exclusion checks; not an auto-qualifying service.

- [C5.3 Forge readiness preflight / commissioning gates](voacap-ft8-phase-c53.md) — protected source paths, read-only schema checks and service rollout conditions.

- [C5.4 proposed Forge readiness service installer](voacap-ft8-phase-c54.md) — pinned offline packaging, private source preflight, component-only rollback and commissioning gates (not deployed).

- [C6 Forge C4 bounded baseline sampler](voacap-ft8-phase-c6.md) — three-gate
  prospective provider worker, exact-month NOAA predicted-SSN evidence and staged
  6-hour timer; no production activation.

- [C6.1 Forge sampler exact-SHA installer](voacap-ft8-phase-c61.md) — offline stage, disabled installation and rollback preconditions.
