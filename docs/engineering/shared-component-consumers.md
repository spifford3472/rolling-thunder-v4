# Shared Component Consumers

This document prevents feature-scoped work from accidentally breaking shared behavior. It is intentionally conservative: when a component is listed as shared, an agent must inspect all named consumers before modifying its contract.

| Shared component | Primary modules | Known consumers | Change risk |
| --- | --- | --- | --- |
| Callsign/contact-info overlay | `callsign_info*.py`, `callsign_info_ui.py` | POTA-selected contacts, DX-selected contacts, Browse/pending callsign workflow, dashboard overlay lifecycle | High: visual or lifecycle changes can affect multiple operating modes |
| Pending callsign capture | `callsign_capture.py`, `live_callsign_capture.py` | Browse, selected spot workflows, contact commit, callsign info | High: stale/replacement semantics affect logging and overlays |
| Local contact logging | `contact_logging.py`, `contact_commit_controller.py`, repositories | Browse, POTA/DX contacts, FT8 logging, DMR logging, LOG screen, remote sync | Critical: local-first durability invariant |
| Current GPS/grid | `gps*.py`, `serial_gps.py`, `maidenhead.py` | Map, logging, FT8 QSO context, repeater distance, Forge location publication, weather applicability | Critical: a QSO must capture the intended current grid at the correct lifecycle point |
| Radio state/control | `radio.py`, `ft891_radio.py`, `radio_polling.py`, `receive_tuning.py` | Browse, POTA, DX, FT8 preparation/transmit, repeater configuration, station status | Critical: safety and hardware coupling |
| Shared spot domain | `spot_domain.py`, `spot_selection.py` | POTA, DX, Forge snapshots, Pi retained spot cache | High: identity/filter changes can redirect actions |
| Shared spot UI/controller | `shared_spot_panel.py`, `shared_spot_ui.py` | POTA and DX | High: one provider must not inherit unintended behavior from the other |
| Shared spot tuning | `shared_spot_tuning.py`, `active_panel_commands.py`, `shared_spot_tune_status.py` | POTA and DX, global status bar | High: staged identity/frequency/mode must remain exact |
| Global status messages | `status_messages.py`, `status_bar_ui.py`, `status_strip.py` | radio/tuning, connectivity, operator feedback, multiple contexts | Medium-high: priority/expiry changes affect unrelated alerts |
| Map runtime | `live_map*.py`, `map_*.py` | primary map, callsign mini-map style mirror, GPS state, POTA markers, radar, weather info | High: provider/cache/viewport changes have broad visual impact |
| Operator preferences | `operator_preferences.py`, settings controllers | map zoom/style, radar image, callsign info and future preferences | Medium: persisted keys are cross-session contracts |
| Physical controls | `physical_controls.py`, dispatcher/source modules | all active contexts | Critical: action remapping can change behavior across every screen |
| Context navigation | `context_navigation.py` | all screens, physical NEXT/BACK/home behavior, keyboard test shortcuts | High |
| Forge spot API | `forge_spot_api.py`, Pi Forge spot clients | POTA, DX, health/status | High: reusable external contract |
| Forge map API layer | `forge_map.py`, `forge_map_api.py`, `forge_spot_main.py` | callsign mini-map and future authorized private clients; shares the spot/weather/radar listener | High: route or listener changes must preserve every existing Forge API |
| Forge weather API | `forge_weather*.py`, Pi weather clients | WEATHER, map local temperature, alerts/status | High: shared retained-state contract |
| Forge callsign intelligence | `forge_callsign_info*.py` | shared callsign overlay; potentially future clients | High: reusable backend API |
| Forge contact sync | `forge_contact_sync*.py`, `wavelog.py` | ordinary/POTA/DX commits, FT8, DMR, local retry, LOG status; potentially future clients | Critical: immutable-QSO routing, station/logbook safety, and UUID idempotency |
| Completed FT8 event contract | `ft8/performance.py`, `domain.py`, `forge_pskreporter_orchestration.py`, `forge_pskreporter_worker.py` | future authorized completed-QSO producer and independent authenticated PSK service | Critical: only matching durable successful terminal attempts may authorize delayed analytics; never transmit, logging, or Wavelog authority |
| Completed-QSO producer outbox | `completed_qso_producer.py`, `completed_qso_ingestion_client.py`, `completed_ft8_ingestion_client.py`, `application_runtime.py` | isolated VOACAP ingestion and PSK event ingestion | Critical: capture only after contact and terminal-attempt durability; exact replay only; disabled-by-default independent authenticated background delivery must never block radio/logging and must verify receiver UUID acknowledgement |
| Completed-QSO ingestion API | `completed_qso_ingestion_client.py`, `forge_propagation_qso_api.py`, `forge_propagation_qso_ingestion.py` | future authorized durable source outboxes and isolated VOACAP worker | Critical: authenticate before body read, UUID-idempotent durable acceptance, never couple provider success to local logging or Wavelog |
| FT8 attempt ledger/correlation | `ft8/attempt_ledger.py`, `ft8_attempt_ingestion_client.py`, `forge_ft8_attempt_api.py`, `forge_ft8_attempt_correlation.py` | FT8 terminal performance, transmit-period evidence, disabled Forge propagation-QSO service, read-only diagnostics, `forge_ft8_attempt_coverage.py`, future training readers | Critical: every terminal outcome stays independent of contacts/RF; preserve raw replay, UUID-keyed provenance exclusion, direction/units/missingness/as-of semantics and bounded leases; unknown provenance is not training evidence; coverage readers must remain provider-free and read-only |
| FT8 bounded transmit path | `ft8/authorization.py`, `session.py`, `hardware_transmit.py`, `transmit.py` | FT8 only by design | Critical: must not become general transmit authority |
| Friend classification | `known_callsigns.py`, `known_callsign_client.py`, `friend_presentation.py` | POTA/DX, FT8 CQ, pending/Browse, callsign overlay, DMR audio/history, LOG | Informational only; no command/identity changes, no UI HTTP or comment leakage |

## Required rule

If a change alters a shared component's inputs, outputs, state transitions, persistence, timing, ownership, or visual contract:

1. review all listed consumers;
2. run the component's targeted tests;
3. run relevant consumer regression tests;
4. update this table if the consumer set changed;
5. update the Operator's Guide if visible behavior changed.

## Specific cross-feature protections

### Callsign information

The overlay is not owned by POTA. POTA may supply a higher-confidence current operating location, but the overlay lifecycle and presentation are shared.

### Logging

FT8, DMR, Browse, and ordinary contact workflows must not fork incompatible local durability semantics. Feature-specific metadata may differ, but local persistence remains authoritative.

### GPS/grid

Do not independently calculate or retain a competing “current grid” inside a feature unless the feature explicitly snapshots the shared grid for a bounded action. In particular, FT8 deliberately captures a QSO grid for the lifetime of one attempt.

### Radio authority

A feature needing one additional radio operation should extend the narrow typed capability required for that operation. It should not expose raw CAT or general PTT authority to UI/controller code.

### Forge

A Pi screen may consume a Forge service, but it does not own that service. Forge APIs should remain presentation-neutral and reusable by future authorized clients.
