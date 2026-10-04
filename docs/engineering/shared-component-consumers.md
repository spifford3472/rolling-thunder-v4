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
| Map runtime | `live_map*.py`, `map_*.py` | primary map, GPS state, POTA markers, radar, weather info | High: provider/cache/viewport changes have broad visual impact |
| Operator preferences | `operator_preferences.py`, settings controllers | map zoom/style, radar image, callsign info and future preferences | Medium: persisted keys are cross-session contracts |
| Physical controls | `physical_controls.py`, dispatcher/source modules | all active contexts | Critical: action remapping can change behavior across every screen |
| Context navigation | `context_navigation.py` | all screens, physical NEXT/BACK/home behavior, keyboard test shortcuts | High |
| Forge spot API | `forge_spot_api.py`, Pi Forge spot clients | POTA, DX, health/status | High: reusable external contract |
| Forge weather API | `forge_weather*.py`, Pi weather clients | WEATHER, map local temperature, alerts/status | High: shared retained-state contract |
| Forge callsign intelligence | `forge_callsign_info*.py` | shared callsign overlay; potentially future clients | High: reusable backend API |
| Forge contact sync | `forge_contact_sync*.py` | local contact sync, LOG status; potentially future clients | Critical: idempotency and Wavelog target safety |
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
