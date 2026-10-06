# Source File Index

## Purpose

This is the exhaustive module-level catalog for `src/rolling_thunder` on the
current engineering baseline. It is a navigation aid, not a replacement for
reading code. Before editing a module, read the owning subsystem documentation,
its tests, and `shared-component-consumers.md`.

**Cataloged Python modules: 265.**

A one-line purpose statement answers why the file exists. Files marked by their
group as shared or composition roots have broad change impact even when a task
originates from one screen.


## Application/UI composition

- `src/rolling_thunder/application_runtime.py` — Pi composition root; owns construction and lifecycle of shared application services.
- `src/rolling_thunder/cli.py` — Command-line entry points for supported Rolling Thunder operations.
- `src/rolling_thunder/dashboard_state.py` — Builds shared dashboard state snapshots.
- `src/rolling_thunder/main.py` — Core application bootstrap for configuration, logging, storage, and backup initialization.
- `src/rolling_thunder/ui/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/ui_main.py` — Full-screen Tkinter composition root; binds contexts, widgets, controllers, overlays, controls, and refresh.

## Configuration and preferences

- `src/rolling_thunder/application_secrets.py` — Environment-backed secret loading without committing credentials.
- `src/rolling_thunder/config.py` — Typed YAML configuration models, validation, defaults, and path resolution.
- `src/rolling_thunder/operator_preferences.py` — Module providing operator preferences behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.

## Controls and navigation

- `src/rolling_thunder/active_panel_commands.py` — Context-aware shared POTA/DX active-panel command handling.
- `src/rolling_thunder/browse_control.py` — Background receive-only controls for free-form Browse operation.
- `src/rolling_thunder/context_navigation.py` — Stable dashboard context IDs, order, shortcuts, and navigation state.
- `src/rolling_thunder/control_dispatcher.py` — Routes normalized physical controls into application commands.
- `src/rolling_thunder/control_protocol.py` — Physical/application control infrastructure for protocol.
- `src/rolling_thunder/control_source_factory.py` — Physical/application control infrastructure for source factory.
- `src/rolling_thunder/control_source_lifecycle.py` — Physical/application control infrastructure for source lifecycle.
- `src/rolling_thunder/operator_commands.py` — Shared operator-command controller used by UI/physical input paths.
- `src/rolling_thunder/physical_controls.py` — Typed physical-control events/actions and safety gating.
- `src/rolling_thunder/serial_control_source.py` — Module providing serial control source behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.

## Radio and CAT

- `src/rolling_thunder/cat_transport.py` — Typed transport interface for semicolon-terminated CAT communication.
- `src/rolling_thunder/drivers/radio/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/ft891_radio.py` — Installed FT-891 radio adapter implementing typed radio capabilities.
- `src/rolling_thunder/mock_radio.py` — Deterministic test/development fake for radio.
- `src/rolling_thunder/pyserial_cat_transport.py` — PySerial implementation of the CAT transport boundary.
- `src/rolling_thunder/radio.py` — Typed radio capability boundary.
- `src/rolling_thunder/radio_band.py` — Module providing radio band behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/radio_polling.py` — Module providing radio polling behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/receive_tuning.py` — Shared typed receive-tuning authority used instead of feature-specific raw CAT.

## GPS and time

- `src/rolling_thunder/chrony_clock.py` — Module providing chrony clock behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/clock_sync.py` — Module providing clock sync behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/drivers/gps/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/gps.py` — Typed GPS receiver/state boundary.
- `src/rolling_thunder/gps_polling.py` — Background GPS polling and immutable state publication.
- `src/rolling_thunder/maidenhead.py` — Maidenhead locator conversion/validation shared by location-aware features.
- `src/rolling_thunder/mock_gps.py` — Deterministic test/development fake for gps.
- `src/rolling_thunder/serial_gps.py` — Installed serial GPS adapter and NMEA state handling.

## Contact logging and log

- `src/rolling_thunder/contact_backup.py` — Shared contact workflow module for backup.
- `src/rolling_thunder/contact_commit_controller.py` — Coordinates operator Commit across shared pending-contact workflow.
- `src/rolling_thunder/contact_export.py` — Shared contact workflow module for export.
- `src/rolling_thunder/contact_import.py` — Shared contact workflow module for import.
- `src/rolling_thunder/contact_logging.py` — Local-first contact creation/logging service.
- `src/rolling_thunder/contact_metadata.py` — Shared contact workflow module for metadata.
- `src/rolling_thunder/contact_qrz_enrichment.py` — Shared contact workflow module for qrz enrichment.
- `src/rolling_thunder/contact_repository.py` — Local contact persistence repository.
- `src/rolling_thunder/contact_retry.py` — Durable retry metadata for remote contact synchronization.
- `src/rolling_thunder/contact_sync.py` — Background synchronization orchestration for locally committed contacts.
- `src/rolling_thunder/log_panel.py` — Local contact-log panel repository/controller.
- `src/rolling_thunder/log_panel_commands.py` — Module providing log panel commands behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/log_ui.py` — Tk presentation for recent local contacts.
- `src/rolling_thunder/wavelog.py` — Module providing wavelog behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.

## Callsign capture/intelligence

- `src/rolling_thunder/callsign_capture.py` — Module providing callsign capture behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/callsign_country.py` — Module providing callsign country behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/callsign_info.py` — Provider-neutral callsign/contact-intelligence models.
- `src/rolling_thunder/callsign_info_client.py` — Pi HTTP client for Forge callsign-intelligence API.
- `src/rolling_thunder/callsign_info_service.py` — Background pending-callsign lookup lifecycle and stale-response rejection.
- `src/rolling_thunder/callsign_info_ui.py` — Shared pure presentation and Tk overlay for contact intelligence.
- `src/rolling_thunder/live_callsign_capture.py` — Module providing live callsign capture behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/phonetic_callsign.py` — Module providing phonetic callsign behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/qrz_profile_image.py` — Module providing qrz profile image behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/qrz_xml.py` — Module providing qrz xml behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.

## Shared spot domain

- `src/rolling_thunder/shared_spot_panel.py` — Shared POTA/DX filtering, selection, and panel presentation controller.
- `src/rolling_thunder/shared_spot_tune_status.py` — Translates shared tune execution into operator status.
- `src/rolling_thunder/shared_spot_tuning.py` — Background staged spot tuning execution.
- `src/rolling_thunder/shared_spot_ui.py` — Tk presentation for the shared POTA/DX panel.
- `src/rolling_thunder/spot_domain.py` — Provider-neutral POTA/DX spot records, identity, metadata, snapshots, and validation.
- `src/rolling_thunder/spot_selection.py` — Stable spot-selection state independent of row position.

## DX

- `src/rolling_thunder/dx_worked.py` — Durable UTC-day DX callsign-and-band worked markers and no-I/O panel lookup state.

## POTA

- `src/rolling_thunder/pota_catalog.py` — POTA-specific module for catalog; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_catalog_main.py` — POTA-specific module for catalog main; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_dashboard_controller.py` — POTA-specific module for dashboard controller; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_dashboard_filters.py` — POTA-specific module for dashboard filters; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_dashboard_panel.py` — POTA-specific module for dashboard panel; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_dashboard_state.py` — POTA-specific module for dashboard state; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_enrichment.py` — POTA-specific module for enrichment; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_enrichment_ui.py` — POTA-specific module for enrichment ui; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_map_markers.py` — POTA-specific module for map markers; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_receive_tune_executor.py` — POTA-specific module for receive tune executor; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_runtime.py` — POTA-specific module for runtime; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_spot_cache_repository.py` — POTA-specific module for spot cache repository; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_spot_polling.py` — POTA-specific module for spot polling; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_spot_ranking.py` — POTA-specific module for spot ranking; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_spot_service.py` — POTA-specific module for spot service; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_spot_source.py` — POTA-specific module for spot source; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_spots.py` — POTA-specific module for spots; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_tune_execution_controller.py` — POTA-specific module for tune execution controller; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_tune_intent.py` — POTA-specific module for tune intent; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_tune_presentation.py` — POTA-specific module for tune presentation; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_tune_ui_controller.py` — POTA-specific module for tune ui controller; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/pota_worked.py` — POTA-specific module for worked; shared spot/radio/GPS contracts remain externally owned.
- `src/rolling_thunder/shared_pota_contact.py` — Module providing shared pota contact behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.

## FT8

- `src/rolling_thunder/ft8/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/ft8/activity.py` — FT8 subsystem module for activity; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/attempt_history.py` — FT8 subsystem module for attempt history; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/audio.py` — FT8 subsystem module for audio; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/audio_buffer.py` — FT8 subsystem module for audio buffer; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/audio_output.py` — FT8 subsystem module for audio output; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/authorization.py` — FT8 subsystem module for authorization; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/band_control.py` — FT8 subsystem module for band control; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/bands.py` — FT8 subsystem module for bands; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/coordinator.py` — FT8 subsystem module for coordinator; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/decoder.py` — FT8 subsystem module for decoder; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/diagnostics.py` — Bounded FT8 audio/clock/decoder diagnostics, NTP-primary readiness, and morning comparison-session accounting.
- `src/rolling_thunder/ft8/distance.py` — Maidenhead distance plus deterministic 20–70 W initial-power thresholds.
- `src/rolling_thunder/ft8/domain.py` — Core shared domain models used across application services.
- `src/rolling_thunder/ft8/encoder.py` — FT8 subsystem module for encoder; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/hardware_transmit.py` — FT8 subsystem module for hardware transmit; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/logging.py` — FT8 subsystem module for logging; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/operator_qso.py` — FT8 subsystem module for operator qso; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/panel.py` — Presentation-safe CQ selection plus incoming-call answer/ignore state.
- `src/rolling_thunder/ft8/performance.py` — Backward-compatible FT8 attempt telemetry including requested and configured-power readbacks.
- `src/rolling_thunder/ft8/performance_outbox.py` — FT8 subsystem module for performance outbox; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/performance_recording.py` — FT8 subsystem module for performance recording; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/performance_sync.py` — FT8 subsystem module for performance sync; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/qso.py` — FT8 subsystem module for qso; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/radio_preparation.py` — FT8 subsystem module for radio preparation; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/receive.py` — Continuous receive/diagnostics plus configured-local-callsign addressed-decode publication.
- `src/rolling_thunder/ft8/session.py` — FT8 subsystem module for session; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/start_control.py` — FT8 subsystem module for start control; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/status.py` — FT8 subsystem module for status; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/timing.py` — FT8 subsystem module for timing; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/transmit.py` — FT8 subsystem module for transmit; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8/worked_today.py` — FT8 subsystem module for worked today; see FT8 engineering documents before modifying its contract.
- `src/rolling_thunder/ft8_active_panel_commands.py` — FT8 dashboard integration for active panel commands.
- `src/rolling_thunder/ft8_ui.py` — FT8 dashboard integration for ui.
- `src/rolling_thunder/ft8_widgets.py` — FT8 dashboard integration for widgets.

## Repeaters

- `src/rolling_thunder/fm_repeater.py` — Module providing fm repeater behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/repeater_active_override_controller.py` — Repeater subsystem module for active override controller.
- `src/rolling_thunder/repeater_configuration.py` — Repeater subsystem module for configuration.
- `src/rolling_thunder/repeater_csv.py` — Repeater subsystem module for csv.
- `src/rolling_thunder/repeater_domain.py` — Repeater subsystem module for domain.
- `src/rolling_thunder/repeater_nearby.py` — Repeater subsystem module for nearby.
- `src/rolling_thunder/repeater_panel.py` — Repeater subsystem module for panel.
- `src/rolling_thunder/repeater_panel_runtime.py` — Repeater subsystem module for panel runtime.
- `src/rolling_thunder/repeater_repository.py` — Repeater subsystem module for repository.
- `src/rolling_thunder/repeater_ui.py` — Repeater subsystem module for ui.
- `src/rolling_thunder/repeater_widgets.py` — Repeater subsystem module for widgets.

## DMR

- `src/rolling_thunder/dmr_active_panel_commands.py` — DMR hotspot subsystem module for active panel commands.
- `src/rolling_thunder/dmr_activity.py` — DMR hotspot subsystem module for activity.
- `src/rolling_thunder/dmr_commit.py` — DMR hotspot subsystem module for commit.
- `src/rolling_thunder/dmr_contact.py` — DMR hotspot subsystem module for contact.
- `src/rolling_thunder/dmr_dashboard_config.py` — DMR hotspot subsystem module for dashboard config.
- `src/rolling_thunder/dmr_dashboard_runtime.py` — DMR hotspot subsystem module for dashboard runtime.
- `src/rolling_thunder/dmr_monitor.py` — DMR hotspot subsystem module for monitor.
- `src/rolling_thunder/dmr_panel_commands.py` — DMR hotspot subsystem module for panel commands.
- `src/rolling_thunder/dmr_panel_runtime.py` — DMR hotspot subsystem module for panel runtime.
- `src/rolling_thunder/dmr_selection.py` — DMR hotspot subsystem module for selection.
- `src/rolling_thunder/dmr_ui.py` — DMR hotspot subsystem module for ui.
- `src/rolling_thunder/dmr_widgets.py` — DMR hotspot subsystem module for widgets.
- `src/rolling_thunder/dmr_wpsd.py` — DMR hotspot subsystem module for wpsd.

## Settings

- `src/rolling_thunder/settings_panel.py` — Settings state/controller and operator preference actions.
- `src/rolling_thunder/settings_ui.py` — Tk presentation for Settings context.

## Map and radar

- `src/rolling_thunder/census_state_outline.py` — Module providing census state outline behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/geoboundaries_outline.py` — Module providing geoboundaries outline behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/live_map.py` — Map controller coordinating current/last-known GPS presentation.
- `src/rolling_thunder/live_map_info.py` — Pure map information/status projection.
- `src/rolling_thunder/live_map_service.py` — Background base-map viewport/tile service and immutable snapshot publication.
- `src/rolling_thunder/live_map_ui.py` — Tk rendering for map, overlays, marker, and map status.
- `src/rolling_thunder/map_refresh.py` — Primary-map subsystem module for refresh.
- `src/rolling_thunder/map_solar.py` — Primary-map subsystem module for solar.
- `src/rolling_thunder/map_sources.py` — Primary-map subsystem module for sources.
- `src/rolling_thunder/map_tiles.py` — Primary-map subsystem module for tiles.
- `src/rolling_thunder/map_zoom.py` — Primary-map subsystem module for zoom.
- `src/rolling_thunder/radar_coverage.py` — Radar domain/presentation module for coverage.
- `src/rolling_thunder/radar_domain.py` — Radar domain/presentation module for domain.
- `src/rolling_thunder/radar_tiles.py` — Radar domain/presentation module for tiles.

## Weather

- `src/rolling_thunder/open_meteo.py` — Module providing open meteo behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/weather_alert_audio.py` — Alert audio adapter/policy execution.
- `src/rolling_thunder/weather_alert_notification_policy.py` — Module providing weather alert notification policy behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/weather_alert_notification_repository.py` — Module providing weather alert notification repository behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/weather_alert_panel.py` — Weather-alert presentation/controller logic.
- `src/rolling_thunder/weather_alert_viewport.py` — Alert text viewport/scroll state for driving-safe rendering.
- `src/rolling_thunder/weather_panel.py` — Pure/current retained weather presentation controller.
- `src/rolling_thunder/weather_ui.py` — Tk presentation for Weather context.

## Pi Forge clients

- `src/rolling_thunder/pi_forge_location_publisher.py` — Pi-side retained Forge integration for location publisher.
- `src/rolling_thunder/pi_forge_runtime.py` — Pi composition helpers for retained Forge polling/location services.
- `src/rolling_thunder/pi_forge_spot_polling.py` — Pi-side retained Forge integration for spot polling.
- `src/rolling_thunder/pi_forge_spot_service.py` — Pi-side retained Forge integration for spot service.
- `src/rolling_thunder/pi_forge_weather_alert_polling.py` — Pi-side retained Forge integration for weather alert polling.
- `src/rolling_thunder/pi_forge_weather_alert_service.py` — Pi-side retained Forge integration for weather alert service.
- `src/rolling_thunder/pi_forge_weather_polling.py` — Pi-side retained Forge integration for weather polling.
- `src/rolling_thunder/pi_forge_weather_service.py` — Pi-side retained Forge integration for weather service.

## Forge backend

- `src/rolling_thunder/forge_callsign_info.py` — Forge callsign-intelligence service logic and caches.
- `src/rolling_thunder/forge_callsign_info_api.py` — HTTP API contract for callsign intelligence.
- `src/rolling_thunder/forge_callsign_info_config.py` — Forge backend module for callsign info config; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_callsign_info_main.py` — Independent Forge callsign-intelligence process entry/composition.
- `src/rolling_thunder/forge_client.py` — Forge backend module for client; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_config.py` — Forge backend module for config; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_contact_sync.py` — Forge contact-sync application service and Wavelog handoff.
- `src/rolling_thunder/forge_contact_sync_api.py` — HTTP API contract for idempotent contact synchronization.
- `src/rolling_thunder/forge_contact_sync_config.py` — Forge backend module for contact sync config; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_contact_sync_main.py` — Independent Forge contact-sync process entry/composition.
- `src/rolling_thunder/forge_dx_connection.py` — Forge backend module for dx connection; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_dx_spot_parser.py` — Forge backend module for dx spot parser; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_dxspider_provider.py` — Persistent disabled-by-default DXSpider fallback provider.
- `src/rolling_thunder/forge_dxsummit_irc_parser.py` — Network-independent parser for DX Summit IRC messages.
- `src/rolling_thunder/forge_dxsummit_provider.py` — Persistent DX Summit IRC provider lifecycle, cache, health, and reconnect behavior.
- `src/rolling_thunder/forge_ft8_performance.py` — Forge backend module for ft8 performance; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_location_client.py` — Forge backend module for location client; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_map_main.py` — Forge backend module for map main; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_mobile_location.py` — Forge backend module for mobile location; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_mobile_location_repository.py` — Forge backend module for mobile location repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_noaa_radar.py` — Forge backend module for noaa radar; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_nws_weather_alerts.py` — Forge backend module for nws weather alerts; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_open_meteo_weather.py` — Forge backend module for open meteo weather; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_pota_provider.py` — Forge-side POTA provider adapter and normalization.
- `src/rolling_thunder/forge_qrz_enrichment.py` — Forge backend module for qrz enrichment; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_qrz_provider.py` — Forge backend module for qrz provider; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_radar.py` — Forge backend module for radar; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_radar_api.py` — Forge backend module for radar api; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_radar_client.py` — Forge backend module for radar client; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_radar_polling.py` — Forge backend module for radar polling; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_snapshot_repository.py` — Forge backend module for snapshot repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_spot_aggregation.py` — Persistence-before-publication core for retained provider-neutral spot snapshots.
- `src/rolling_thunder/forge_spot_api.py` — Versioned HTTP API for retained Forge spot/health state.
- `src/rolling_thunder/forge_spot_cache_repository.py` — Forge backend module for spot cache repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_spot_main.py` — Forge spot/weather/radar process composition and lifecycle root.
- `src/rolling_thunder/forge_spot_polling.py` — Forge backend module for spot polling; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_spot_provider.py` — Forge backend module for spot provider; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather.py` — Forge backend module for weather; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_alert_api.py` — Forge backend module for weather alert api; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_alert_cache_repository.py` — Forge backend module for weather alert cache repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_alert_client.py` — Forge backend module for weather alert client; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_alert_polling.py` — Forge backend module for weather alert polling; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_alert_repository.py` — Forge backend module for weather alert repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_alerts.py` — Forge backend module for weather alerts; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_cache_repository.py` — Forge backend module for weather cache repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_client.py` — Forge backend module for weather client; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_polling.py` — Forge backend module for weather polling; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_repository.py` — Forge backend module for weather repository; keep provider/backend contracts reusable by non-UI clients.
- `src/rolling_thunder/forge_weather_unavailable.py` — Forge backend module for weather unavailable; keep provider/backend contracts reusable by non-UI clients.

## Status and connectivity

- `src/rolling_thunder/connectivity_status.py` — Module providing connectivity status behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/network_keepalive.py` — Background connectivity keepalive without UI-thread network work.
- `src/rolling_thunder/runtime_connectivity.py` — Module providing runtime connectivity behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/station_health.py` — Builds operator-facing station subsystem health.
- `src/rolling_thunder/status_bar_ui.py` — Tk presentation for global status state.
- `src/rolling_thunder/status_messages.py` — Thread-safe global status-message arbitration.
- `src/rolling_thunder/status_monitor.py` — Module providing status monitor behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/status_strip.py` — Builds compact system/status strip presentation.

## Mocks

- `src/rolling_thunder/mock_home_platform.py` — Deterministic test/development fake for home platform.

## Infrastructure

- `src/rolling_thunder/storage.py` — SQLite schema initialization and shared storage infrastructure.
- `src/rolling_thunder/threaded_poll_scheduler.py` — Module providing threaded poll scheduler behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/threading_scheduler.py` — Module providing threading scheduler behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.

## Package boundaries

- `src/rolling_thunder/drivers/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/drivers/audio/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/drivers/device_input/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/platform/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/ring1/__init__.py` — Package marker/export boundary.

## Shared utilities

- `src/rolling_thunder/__init__.py` — Package marker/export boundary.
- `src/rolling_thunder/domain.py` — Core shared domain models used across application services.
- `src/rolling_thunder/ft891_cat.py` — FT-891 CAT command/value helpers and radio-specific protocol semantics.
- `src/rolling_thunder/home_platform.py` — Module providing home platform behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/home_platform_health.py` — Module providing home platform health behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/http_home_platform.py` — Module providing http home platform behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/http_pota_spot_source.py` — Module providing http pota spot source behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/live_radar_service.py` — Module providing live radar service behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/logging_setup.py` — Module providing logging setup behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/pi_weather_alert_location_guard.py` — Module providing pi weather alert location guard behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/speech_recognition.py` — Module providing speech recognition behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/station_state.py` — Module providing station state behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/us_extra_band_advisory.py` — Module providing us extra band advisory behavior within its owning subsystem. Inspect its tests and callers before changing public behavior.
- `src/rolling_thunder/value_types.py` — Validated shared value types used by domain/application code.

## Maintenance rule

Update this catalog in the same branch whenever a Python source module is added,
removed, renamed, or materially repurposed. A new feature should be placed under
the smallest correct ownership group; shared behavior must not be mislabeled as
screen-owned.


## Known/friend callsign directory

- `src/rolling_thunder/known_callsigns.py` — bounded presentation-neutral directory contracts and normalized classification.
- `src/rolling_thunder/forge_known_callsigns.py` — dedicated Forge SQLite admin records and comment-free snapshot/batch queries.
- `src/rolling_thunder/forge_known_callsign_admin.py` — escaped private-network admin forms, CSRF protection and delete confirmation.
- `src/rolling_thunder/known_callsign_client.py` — Pi snapshot/batch HTTP client, expiring bounded cache and scheduled worker lifecycle.
- `src/rolling_thunder/friend_presentation.py` — no-I/O remote callsign star semantics and shared gold color.

Existing callsign-info composition/router/configuration now wires this optional
directory. ApplicationRuntime owns its Pi poller; existing remote-call
presentation adapters consume its immutable classification only.

### Checkpoint A coordinate persistence responsibilities

- `domain.py`: immutable paired optional local QSO coordinates and numeric bounds.
- `contact_metadata.py`: resolves paired coordinates with the existing local grid
  usability/freshness policy from the passed snapshot.
- `contact_logging.py`: copies ordinary resolved coordinates or explicit completed
  QSO coordinates; never reads GPS at completed-QSO logging.
- `ft8/logging.py`: transfers frozen authorization coordinates into Contact.
- `contact_repository.py`: preserves coordinates in every persistence/read/recovery
  path and includes them in local idempotent payload comparison.
- `storage.py`: schema 16 nullable coordinate additions; no backfill/table rebuild.
- `contact_export.py`: complete-contact format 3; imports retain formats 1/2.

Consumers and ownership remain unchanged.
