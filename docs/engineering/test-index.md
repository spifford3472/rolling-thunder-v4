# Test Index and Validation Guide

## Purpose

Rolling Thunder has broad automated regression coverage. This index groups the
current Python test modules by engineering ownership so an agent can identify
targeted coverage before running the full suite.

**Cataloged Python test modules: 296.**

The final gate remains the full suite; this index does not authorize skipping
cross-feature regression tests when a shared contract changes.

## Standard automated gate

```bash
ruff check .
mypy src/rolling_thunder
pytest
git diff --check
```

The project also uses GitHub Actions and pre-commit. Exact release/merge heads
must be validated rather than assuming an earlier green commit covers later
changes.

## Live acceptance

Automated tests do not replace installed acceptance for changes involving:
- FT-891/CAT or DigiRig/audio behavior;
- GPS serial behavior or system clock;
- full-screen readability/layout;
- physical controls;
- systemd/autostart;
- Forge production provider sessions or persistence;
- network routing/firewall/deployment;
- bounded RF transmission.

Live acceptance should use an exact commit SHA and record rollback information.


## Application/runtime/UI

- `tests/test_autostart_launcher.py`
- `tests/test_dashboard_health_compatibility.py`
- `tests/test_dashboard_state.py`
- `tests/test_home_platform_runtime.py`
- `tests/test_ui_main.py`

## Configuration/settings

- `tests/test_config.py`
- `tests/test_home_platform_config.py`
- `tests/test_operator_preferences.py`
- `tests/test_settings_panel.py`
- `tests/test_settings_ui.py`
- `tests/test_speech_config.py`

## Controls and navigation

- `tests/test_browse_control.py`
- `tests/test_context_navigation.py`
- `tests/test_control_dispatcher.py`
- `tests/test_control_protocol.py`
- `tests/test_control_source_factory.py`
- `tests/test_control_source_lifecycle.py`
- `tests/test_operator_commands.py`
- `tests/test_physical_control_transport_config.py`
- `tests/test_physical_controls.py`
- `tests/test_physical_controls_config.py`
- `tests/test_serial_control_source.py`

## Radio and CAT

- `tests/test_application_runtime.py`
- `tests/test_application_secrets.py`
- `tests/test_mock_radio.py`
- `tests/test_operator_context_notifications.py`
- `tests/test_pyserial_cat_transport.py`
- `tests/test_radio_band.py`
- `tests/test_radio_polling.py`
- `tests/test_receive_tuning.py`

## GPS and time

- `tests/test_application_runtime_clock_sync.py`
- `tests/test_chrony_clock.py`
- `tests/test_clock_sync.py`
- `tests/test_gps_polling.py`
- `tests/test_gps_utc.py`
- `tests/test_maidenhead.py`
- `tests/test_mock_gps.py`
- `tests/test_serial_gps.py`
- `tests/test_serial_gps_buffer_freshness.py`

## Contact logging and synchronization

- `tests/test_contact_backup.py`
- `tests/test_contact_commit_controller.py`
- `tests/test_contact_export.py`
- `tests/test_contact_import.py`
- `tests/test_contact_logging.py`
- `tests/test_contact_metadata.py`
- `tests/test_contact_qrz_enrichment.py`
- `tests/test_contact_qrz_runtime.py`
- `tests/test_contact_repository.py`
- `tests/test_contact_retry.py`
- `tests/test_contact_sync.py`
- `tests/test_contact_sync_manual_retry.py`
- `tests/test_log_panel.py`
- `tests/test_log_panel_commands.py`
- `tests/test_log_ui.py`
- `tests/test_logging_setup.py`
- `tests/test_wavelog.py`
- `tests/test_wavelog.py` owns Wavelog station/logbook routing coverage: exact
  dynamic reuse, active-log-only hidden creation and restart recovery, durable
  binding identity/metadata rejection, recoverable and unrecoverable 409 cases,
  ambiguity/incompatibility rejection, membership preservation/verification,
  read-only health, legacy fallback/grid PATCH, dynamic no-PATCH behavior, and
  blank-only ADIF `NOTES` defaulting.
- `tests/test_wavelog_history.py`
- `tests/test_wavelog_http_errors.py`
## Callsign intelligence

- `tests/test_callsign_capture.py`
- `tests/test_callsign_info.py`
- `tests/test_live_callsign_capture.py`
- `tests/test_phonetic_callsign.py`
- `tests/test_qrz_profile_image.py`
- `tests/test_qrz_xml.py`

## POTA / DX / shared spots

- `tests/test_dx_worked.py`
- `tests/test_http_pota_spot_source.py`
- `tests/test_pota_catalog.py`
- `tests/test_pota_config.py`
- `tests/test_pota_dashboard_controller.py`
- `tests/test_pota_dashboard_filters.py`
- `tests/test_pota_dashboard_panel.py`
- `tests/test_pota_dashboard_state.py`
- `tests/test_pota_enrichment.py`
- `tests/test_pota_enrichment_ui.py`
- `tests/test_pota_map_markers.py`
- `tests/test_pota_receive_tune_executor.py`
- `tests/test_pota_runtime.py`
- `tests/test_pota_runtime_receive_tune.py`
- `tests/test_pota_spot_cache_repository.py`
- `tests/test_pota_spot_polling.py`
- `tests/test_pota_spot_ranking.py`
- `tests/test_pota_spot_service.py`
- `tests/test_pota_spot_source.py`
- `tests/test_pota_spots.py`
- `tests/test_pota_tune_execution_controller.py`
- `tests/test_pota_tune_intent.py`
- `tests/test_pota_tune_presentation.py`
- `tests/test_pota_tune_ui_controller.py`
- `tests/test_pota_worked.py`
- `tests/test_shared_pota_contact.py`
- `tests/test_shared_spot_active_panel_commands.py`
- `tests/test_shared_spot_panel.py`
- `tests/test_shared_spot_tune_status.py`
- `tests/test_shared_spot_tuning.py`
- `tests/test_shared_spot_ui.py`
- `tests/test_spot_domain.py`
- `tests/test_spot_selection.py`

## FT8

- `tests/test_ft8_contact_sync.py` — composed dashboard completion notification
  and shared Pi/Forge/Wavelog Mobile path, including optional QRZ and replay.

- `tests/test_forge_ft8_performance.py` — structured configured-power fields, legacy replay, and additive Forge schema migration.
- `tests/test_forge_ft8_performance_api.py`
- `tests/test_forge_pskreporter.py` — bounded provider parsing, concurrency etiquette, terminal eligibility, correlation, restart-safe zero/failure distinctions, and raw-query archival.
- `tests/test_forge_pskreporter_orchestration.py` — confirmed event validation, exact replay, terminal latency, durable global pacing, bounded batching, restart reconciliation, disabled behavior, and provider-free health.
- `tests/test_ft891_cat.py`
- `tests/test_ft891_fm_repeater_cat.py`
- `tests/test_ft891_fm_repeater_radio.py`
- `tests/test_ft891_radio.py`
- `tests/test_ft891_radio_concurrency.py`
- `tests/test_ft8_active_panel_commands.py`
- `tests/test_ft8_activity.py`
- `tests/test_ft8_attempt_history.py`
- `tests/test_ft8_audio.py`
- `tests/test_ft8_audio_buffer.py`
- `tests/test_ft8_audio_output.py`
- `tests/test_ft8_authorization.py` — fail-closed selection freshness and preparation-delay regression coverage.
- `tests/test_ft8_band_control.py`
- `tests/test_ft8_bands.py`
- `tests/test_ft8_config.py`
- `tests/test_ft8_coordinator.py`
- `tests/test_ft8_decoder.py`
- `tests/test_ft8_distance.py` — Maidenhead distance and conservative adaptive initial-power thresholds.
- `tests/test_ft8_domain.py`
- `tests/test_ft8_encoder.py`
- `tests/test_ft8_hardware_transmit.py`
- `tests/test_ft8_logging.py`
- `tests/test_ft8_operator_qso.py`
- `tests/test_ft8_panel.py` — CQ selection plus explicit incoming-call answer/ignore/staleness behavior.
- `tests/test_ft8_performance.py`
- `tests/test_ft8_performance_http.py`
- `tests/test_ft8_performance_outbox.py`
- `tests/test_ft8_performance_sync.py`
- `tests/test_ft8_physical_controls.py`
- `tests/test_ft8_qso.py`
- `tests/test_ft8_radio_preparation.py`
- `tests/test_ft8_receive.py` — continuous capture plus addressed-call publication without changing diagnostics.
- `tests/test_ft8_diagnostics.py` — NTP-primary/GPS-fallback readiness, audio health, and bounded 05:15 New York comparison-session accounting.
- `tests/test_ft8_schema_migration.py`
- `tests/test_ft8_session.py`
- `tests/test_ft8_start_control.py`
- `tests/test_ft8_status.py`
- `tests/test_ft8_timing.py`
- `tests/test_ft8_ui.py`
- `tests/test_ft8_worked_today.py`
- `tests/test_real_ft891_integration.py`

## Repeaters

- `tests/test_fm_repeater.py`
- `tests/test_repeater_active_override_controller.py`
- `tests/test_repeater_active_panel_commands.py`
- `tests/test_repeater_configuration.py`
- `tests/test_repeater_csv.py`
- `tests/test_repeater_domain.py`
- `tests/test_repeater_nearby.py`
- `tests/test_repeater_panel.py`
- `tests/test_repeater_panel_runtime.py`
- `tests/test_repeater_repository.py`
- `tests/test_repeater_single_press_commands.py`
- `tests/test_repeater_ui.py`

## DMR

- `tests/test_dmr_active_panel_commands.py`
- `tests/test_dmr_activity.py`
- `tests/test_dmr_commit.py`
- `tests/test_dmr_contact.py`
- `tests/test_dmr_contact_storage.py`
- `tests/test_dmr_dashboard_wiring.py`
- `tests/test_dmr_monitor.py`
- `tests/test_dmr_panel_commands.py`
- `tests/test_dmr_panel_runtime.py`
- `tests/test_dmr_selection.py`
- `tests/test_dmr_ui.py`
- `tests/test_dmr_widgets.py`
- `tests/test_dmr_wpsd.py`
- `tests/test_wavelog_dmr.py`

## Map and radar

- `tests/test_active_panel_map_zoom.py`
- `tests/test_live_map.py`
- `tests/test_live_map_config.py`
- `tests/test_live_map_info.py`
- `tests/test_live_map_info_ui.py`
- `tests/test_live_map_runtime.py`
- `tests/test_live_map_service.py`
- `tests/test_live_map_ui.py`
- `tests/test_live_map_zoom.py`
- `tests/test_live_radar_service.py`
- `tests/test_forge_map_route.py`
- `tests/test_map_solar.py`
- `tests/test_map_sources.py`
- `tests/test_map_tiles.py`
- `tests/test_map_zoom.py`
- `tests/test_radar_config_runtime.py`
- `tests/test_radar_coverage.py`
- `tests/test_radar_render_plan.py`
- `tests/test_weather_map_integration.py`

## Weather and alerts

- `tests/test_application_runtime_weather_alerts.py`
- `tests/test_pi_weather_alert_location_guard.py`
- `tests/test_weather_alert_audio.py`
- `tests/test_weather_alert_notification_policy.py`
- `tests/test_weather_alert_notification_repository.py`
- `tests/test_weather_alert_panel.py`
- `tests/test_weather_alert_storage_schema.py`
- `tests/test_weather_alert_viewport.py`
- `tests/test_weather_panel.py`
- `tests/test_weather_ui.py`

## Forge and Pi/Forge contracts

- `tests/test_application_runtime_forge.py`
- `tests/test_forge_callsign_info.py`
- `tests/test_forge_checkpoint5_integration.py`
- `tests/test_forge_client.py`
- `tests/test_forge_client_provider_shapes.py`
- `tests/test_forge_config.py`
- `tests/test_forge_contact_sync.py`
- `tests/test_forge_contact_sync_api.py`
- `tests/test_forge_contact_sync_config.py`
- `tests/test_forge_deployment_assets.py` — static production path, privilege,
  disabled-default, rollout-confirmation, exact-SHA component-hook parameter and
  path constraints, real pip-generated launcher final-path execution, broken-release
  fail-closed activation, successful isolated stage preparation/cleanup, artifact
  replacement refusal, and cross-service isolation checks.
- `tests/test_forge_dx_spot_parser.py`
- `tests/test_forge_dxspider_provider.py`
- `tests/test_forge_dxsummit_irc_parser.py`
- `tests/test_forge_dxsummit_provider.py`
- `tests/test_forge_location_client.py`
- `tests/test_forge_mobile_location.py`
- `tests/test_forge_mobile_location_api.py`
- `tests/test_forge_mobile_location_repository.py`
- `tests/test_forge_noaa_radar.py`
- `tests/test_forge_nws_weather_alerts.py`
- `tests/test_forge_open_meteo_weather.py`
- `tests/test_forge_pota_provider.py`
- `tests/test_forge_propagation_history.py` — offline collector/runtime behavior,
  provider bounds, durable health, and database/provider-free config preflight.
- `tests/test_forge_propagation_qso_ingestion.py` — immutable UUID replay,
  schema coexistence/migration boundary, identified bounded leases, final-attempt
  recovery, queue observation, retry/dead-letter isolation, and VOACAP provenance.
- `tests/test_forge_propagation_qso_worker.py` — disabled startup, independent
  configuration bounds, deterministic fake cycles, and atomic versioned status.
- `tests/test_forge_propagation_repository.py`
- `tests/test_forge_qrz_enrichment.py`
- `tests/test_forge_qrz_provider.py`
- `tests/test_forge_radar.py`
- `tests/test_forge_radar_client.py`
- `tests/test_forge_radar_polling.py`
- `tests/test_forge_radar_runtime.py`
- `tests/test_forge_snapshot_repository.py`
- `tests/test_forge_spot_aggregation.py`
- `tests/test_forge_spot_api.py`
- `tests/test_forge_spot_cache_repository.py`
- `tests/test_forge_spot_composition.py`
- `tests/test_forge_spot_main.py`
- `tests/test_forge_spot_polling.py`
- `tests/test_forge_spot_provider.py`
- `tests/test_forge_weather.py`
- `tests/test_forge_weather_alert_api.py`
- `tests/test_forge_weather_alert_cache_repository.py`
- `tests/test_forge_weather_alert_client.py`
- `tests/test_forge_weather_alert_config.py`
- `tests/test_forge_weather_alert_polling.py`
- `tests/test_forge_weather_alert_repository.py`
- `tests/test_forge_weather_alert_runtime.py`
- `tests/test_forge_weather_alerts.py`
- `tests/test_forge_weather_api.py`
- `tests/test_forge_weather_cache_repository.py`
- `tests/test_forge_weather_client.py`
- `tests/test_forge_weather_config.py`
- `tests/test_forge_weather_polling.py`
- `tests/test_forge_weather_repository.py`
- `tests/test_forge_weather_restart_health.py`
- `tests/test_forge_weather_runtime.py`
- `tests/test_pi_forge_location_publisher.py`
- `tests/test_pi_forge_location_publishing.py`
- `tests/test_pi_forge_runtime.py`
- `tests/test_pi_forge_spot_polling.py`
- `tests/test_pi_forge_spot_service.py`
- `tests/test_pi_forge_weather_alert_config.py`
- `tests/test_pi_forge_weather_alert_polling.py`
- `tests/test_pi_forge_weather_alert_service.py`
- `tests/test_pi_forge_weather_config.py`
- `tests/test_pi_forge_weather_polling.py`
- `tests/test_pi_forge_weather_service.py`
- `tests/test_pi_forge_weather_storage.py`

## Status/connectivity

- `tests/test_connectivity_status.py`
- `tests/test_runtime_connectivity.py`
- `tests/test_status_bar_ui.py`
- `tests/test_status_messages.py`
- `tests/test_status_monitor.py`
- `tests/test_status_strip.py`

## Other shared/infrastructure

- `tests/test_active_panel_commands.py`
- `tests/test_census_state_outline.py`
- `tests/test_cli.py`
- `tests/test_domain.py`
- `tests/test_home_platform.py`
- `tests/test_home_platform_health.py`
- `tests/test_http_home_platform.py`
- `tests/test_main.py`
- `tests/test_mock_home_platform.py`
- `tests/test_network_keepalive.py`
- `tests/test_open_meteo.py`
- `tests/test_speech_audio_channels.py`
- `tests/test_station_health.py`
- `tests/test_station_state.py`
- `tests/test_storage.py`
- `tests/test_us_extra_band_advisory.py`
- `tests/test_value_types.py`

## Shared-change regression rule

When a change touches a module listed in
`shared-component-consumers.md`, identify and run the tests for every affected
consumer before the full suite. Do not rely only on the test file whose name most
closely matches the requested screen.

## Test maintenance

Add or update regression tests in the same branch as behavior changes. Keep
tests hardware/network-independent by default using fakes, fixtures, temporary
storage, and injected transports. Deployment-only acceptance tests must be
clearly distinguished from CI-safe tests.


## Known/friend callsigns

- `tests/test_forge_known_callsigns.py` — SQLite persistence/schema/limits, admin CRUD/escaping/CSRF/delete confirmation, snapshot/batch privacy, real local HTTP handler.
- `tests/test_known_callsign_client.py` — bounded transport validation, batch identity, cache refresh/failure/staleness, background polling and typed configuration.
- `tests/test_friend_widgets.py` — headless gold-star FT8 and LOG adapters preserving outcome/selection/sync colors.
- Existing shared-spot, FT8, callsign-info, DMR and runtime tests include decoration-only regression checks.

Owner service-package, state backup, private-network admin, restart persistence,
and installed screen acceptance remains required; see `../KNOWN_CALLSIGNS.md`.

### Immutable contact location

`tests/test_contact_location.py` covers coordinate bounds/pairs/frozen models, all
repository paths, retry/enrichment preservation, schema-15 migration integrity,
complete-contact export/backup/import, legacy formats, and the historical
coordinate-independent ADIF baseline. Current Forge hash coverage additionally
binds the exact selected station ID and Wavelog-bound ADIF. Existing
contact-controller, logging, FT8 authorization/logging and HTTP/Forge API tests
cover capture boundaries, movement and receiver compatibility.

### Dynamic mobile Wavelog routing

`tests/test_forge_contact_sync.py` owns ledger binding, uncertain duplicate replay,
and changed-payload/changed-station conflict behavior after exact target selection.
`tests/test_contact_weather.py` proves synchronization has no weather-enricher
dependency, uploads the exact immutable payload, preserves weather already present,
and formats absent requested weather as `N/A`. `tests/test_forge_contact_sync_config.py`
rejects the removed contact-sync weather-provider configuration.
`tests/test_wavelog.py` owns provider-adapter station creation and configured-logbook
membership semantics. `tests/test_forge_contact_sync_api.py`,
`tests/test_ft8_contact_sync.py`, and DMR/ADIF tests protect the one shared
presentation-neutral sync boundary used by ordinary, POTA/DX, FT8, and DMR
contacts. All provider writes are scripted fakes; installed Wavelog acceptance is
still required.
