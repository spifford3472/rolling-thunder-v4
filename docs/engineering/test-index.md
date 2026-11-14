# Test Index and Validation Guide

## Purpose

Rolling Thunder has broad automated regression coverage. This index groups the
current Python test modules by engineering ownership so an agent can identify
targeted coverage before running the full suite.

**Cataloged Python test modules: 383.**

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
- `tests/test_stab02_shutdown_failure_modes.py` — STAB-02 hardware-free blocked CAT TX0, held CAT lock, failed release/retry during disconnect, sequential UI/runtime shutdown, GPS cancellation with a blocked in-flight read, repeat shutdown, rollback after interrupted service startup, and strict expected-failure characterization of connected-radio cleanup before completed startup; expected failure is not safety acceptance.
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
- `tests/test_settings_selection.py`
- `tests/test_power_control.py`
- `tests/test_speech_config.py`

## Controls and navigation

- `tests/test_browse_control.py`
- `tests/test_context_navigation.py`
- `tests/test_control_dispatcher.py` — FIFO mapping/gating plus optional accepted
  action-token timing that preserves execution order and excludes rejected events.
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

## Antenna reference and RF exposure

- `tests/test_rf_exposure_calculator.py` — immutable validation, gain conversion,
  incomplete inputs, duty/fraction separation, reflection assumptions, equations,
  and the FCC boundary matrix.
- `tests/test_antenna_reference_repository.py` — schema-21 preservation and
  rollback, no seeded values, UUID aggregate round trips, assignment ownership,
  and pure service evaluation for dormant-storage compatibility.
- `tests/test_antenna_reference_config.py` — empty authoritative example, strict
  YAML parsing, provenance and explicit-6-m preservation, aggregate references,
  measured-distance rules, missing-file failure, and the separate mobile example's
  corrected feed chains, three verified driver distances, unchanged gains, YAML
  round trip, unknown losses, deliberately incomplete/no-verdict evaluations, and
  the physical 1280×720/Tk-scaled nine-row table accessibility budget.
- `tests/test_antenna_reference_panel.py` — empty startup, multi-installation listing,
  HF/VHF/explicit-6-m cards, gain/loss units, deferred YAML worker execution,
  configured six-metre FM results, advisory wording, and view-only controls.
- `tests/test_context_navigation.py` and `tests/test_config.py` — default-off context
  sequence/shortcut plus required, path-resolved authority-file configuration.

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

`tests/test_offline_contact_durability.py` is the integrated local-first acceptance
gate. It holds a network upload future while an ordinary dashboard commit completes,
reconstructs the SQLite repositories after outage, and proves ordinary plus FT8
contacts retain their UUID/payload and retry state. Reconnect is exercised through
the durable Forge UUID ledger so lost responses do not duplicate Wavelog writes.

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
- `tests/test_audio_capture.py`
- `tests/test_speech_config.py`
- `tests/test_speech_recognition.py`
- `tests/test_tron_audio_gate.py`
- `tests/test_tron_capture_coordinator.py`
- `tests/test_tron_control_gesture.py`
- `tests/test_tron_commands.py`
- `tests/test_tron_dispatch.py`
- `tests/test_tron_microphone.py`
- `tests/test_tron_recognition.py`
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

- `tests/test_forge_ft8_performance.py` — structured configured-power/coordinate
  fields, current and legacy replay/conflict behavior, and additive Forge schema-1
  and schema-3 migration to schema 4 with row/integrity preservation.
- `tests/test_forge_ft8_performance_api.py` — authenticated-shape endpoint behavior,
  UUID conflicts, coordinate ingestion, and zero Wavelog calls.
- `tests/test_forge_ft8_attempt_api.py` — authentication-before-ingestion,
  idempotent acceptance, disabled ingestion and read-only diagnostics.
- `tests/test_forge_ft8_attempt_correlation.py` — replay conflicts,
  direction/grid/power/missing semantics, provider retry, leases/dead letters and
  immutable retrospective diagnostics, including retry-exhaustion reverse skips,
  zero-egress terminal replay, distinct declared model-version identities, safe
  legacy fallback, grid normalization, unavailable status, as-of bounds, provenance
  and ready-result training eligibility.
- `tests/test_forge_ft8_attempt_coverage.py` — read-only scoped C2 denominators,
  privacy-minimized partitions, logical non-mutation and fail-closed UUID/hash/
  training-invariant reconciliation.
- `tests/test_forge_ft8_historical_replay.py` — C3 exact UUID/SHA and existing
  field-provenance gates, immutable synthetic exclusions, grid4/grid6 and dial/audio
  frequency semantics, UTC rollover, twelve-period power/report interpretation,
  bounded fake success/malformed/timeout/unavailable/unsupported behavior, zero-call
  deduplication, append-only model-version forks, C2 coverage, lease preservation,
  source non-mutation, and fixed-audit CLI refusal.
- `tests/test_forge_voacap_baseline.py` — C4 immutable plan/lineage and target-grid
  identity, four UTC slots, monthly response dedup, disabled/unsupported behavior,
  provider failure bounds, call/concurrency/lease/restart protection, additive legacy
  preservation, deterministic read-only diagnostics, audit UUIDs and no network path.
- `tests/test_forge_ft8_power_advisor.py` — C5 UTC/as-of/provenance/hash invariants,
  grouped forward holdouts and independent-input deduplication, scientific
  missingness/censoring, immutable advisory safety, YAML reload, readiness
  transitions and additive artifact persistence.
- `tests/test_forge_pskreporter.py` — bounded provider parsing, concurrency etiquette, terminal eligibility, correlation, restart-safe zero/failure distinctions, and raw-query archival.
- `tests/test_forge_pskreporter_orchestration.py` — confirmed event validation, exact replay, terminal latency, durable global pacing, bounded batching, restart reconciliation, disabled behavior, and provider-free health.
- `tests/test_completed_qso_producer.py` — matching post-durability event validation, exact replay/conflict, independent destination progress, retry timing, and restart recovery without provider I/O.
- `tests/test_completed_ft8_ingestion_client.py` — authenticated PSK event transport, full immutable payload, idempotency key, receiver UUID acknowledgement, and retryable failure semantics.
- `tests/test_forge_pskreporter_worker.py` — triple-gated configuration, database-free disabled/preflight behavior, authenticated idempotent event ingestion, latency preservation, disabled-provider scheduling, and atomic diagnostics.
- `tests/test_ft891_cat.py`
- `tests/test_ft891_fm_repeater_cat.py`
- `tests/test_ft891_fm_repeater_radio.py`
- `tests/test_ft891_radio.py`
- `tests/test_ft891_radio_concurrency.py`
- `tests/test_ft8_active_panel_commands.py`
- `tests/test_ft8_activity.py`
- `tests/test_ft8_attempt_history.py`
- `tests/test_ft8_attempt_ledger.py` — terminal classifications, frozen UTC/grid/
  coordinates, report directions, per-period power, replay and offline retry.
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
- `tests/test_ft8_panel.py`
- `tests/test_ft8_terminal_return.py` — CQ selection plus explicit incoming-call answer/ignore/staleness behavior.
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
- `tests/test_issue_345_ui_blocking_reproduction.py` — deterministic,
  hardware-free event/barrier proof that synchronous Tk image materialization
  retains the map-refresh caller until completion, with separate bounded
  base64/PhotoImage/canvas timing tokens; diagnostic only.
- `tests/test_issue345_timing_report.py` — repository-root import and CLI coverage
  for bounded exported-text parsing, fixed provenance labels, same-refresh
  correlation, legacy missing-detail preservation, and rejection without copying
  unknown, malformed, or oversized input.
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
  configuration bounds, provider-free preflight/status, deterministic fake cycles,
  and atomic versioned status.
- `tests/test_forge_propagation_qso_api.py` — authentication-before-body,
  UUID/idempotency validation, durable provider-free ingestion, health, disabled
  behavior, and in-memory producer/consumer contract smoke coverage.
- `tests/test_completed_qso_ingestion_client.py` — bearer/idempotency transport,
  complete immutable payload, acknowledgement validation, and failure semantics.
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

- `tests/test_forge_ft8_readiness_main.py` — missing C4, OFF/armed/no-calibration, read-only dedup and fail-closed output.

- `tests/test_forge_ft8_power_experiment.py` — fail-closed randomized trial assignment, repeatability, bounded wattage and no RF authority.

- `tests/test_forge_ft8_qualification.py` — certificate fail-closed controls, provenance and confidence-bound rejection.

- `tests/test_forge_ft8_power_statistics.py` — synthetic fake-only balanced trial and failed-trial confidence bounds, grouping/dedup/provenance/exclusion tests.

- `tests/test_ft8_attempt_ledger.py` — v1 payload/hash invariance and v2 frozen-choice round-trip compatibility.

- `tests/test_forge_ft8_prospective_inventory.py` — isolated v2 event, missing provenance, retrospective link, read-only rejection tests.

- `tests/test_forge_ft8_c4_asof.py` — valid synthetic regional as-of join,
  after-choice and observed-SSN semantic rejection, explicit training ineligibility
  and absent-source fail-closed acceptance.

- `tests/test_forge_ft8_readiness_preflight.py` — read-only source byte preservation, missing source and malformed schema rejection.

- `tests/test_forge_ft8_readiness_installer.py` — candidate root-helper safety scoping and shell syntax; offline wheel staging and CLI installation additionally smoke-tested on Forge.

- `tests/test_forge_voacap_baseline_main.py` — legacy C6 disabled/no-I/O gate, UTC day/month
  scheduling, fail-before-persistence provider preflight, trusted backup metadata and
  durable controlled-pilot failure audit; scheduled-capture runtime selection and
  exactly 105 fake provider calls.

- `tests/test_forge_voacap_scheduled_capture.py` — C6 successor 105-call runs at each
  UTC boundary, immutable request/cell provenance, same-day retries, missed prior-day
  work, storage/status classifications, query-only health and SQLite backup integrity.

- `tests/test_forge_voacap_scheduled_plan_main.py` — dry-run-first capture-plan creation,
  exact 15-site parent identity checks and refusal of duplicate inventory.

- `tests/test_forge_voacap_baseline_deploy.py` — C6.1 installer shell integrity and fail-closed three-gate checks.

- `tests/test_forge_voacap_baseline_provider_contract.py` — fake-HTTP real VOACAP
  summary request body, exact identity/version rejection and one-POST cap preserved
  after an ambiguous timeout.

- `tests/test_forge_solar_ssn.py` — NOAA published wire fixture, exact target-month
  `predicted_ssn`, predicted/observed separation, unknown release, freshness/HTTPS/
  schema failure, raw bytes/headers and append-only revision capture plus query-only
  HamQSL raw-count exclusion.

- `tests/test_forge_voacap_plan_main.py` — fixed-origin exact forecast-month predicted
  SSN plan construction, dry-run no-write default and explicit artifact/plan registration.

- `tests/test_forge_voacap_baseline_local_http.py` — real urllib HTTP framing over an in-memory fake socket; no network egress.

- Antenna mobile YAML tests also verify separate measured-driver versus unverified hypothetical six-foot public scenarios, incomplete assessments with unknown duplexer/coax losses, and both supplied duplexer path specifications.

- Antenna zero-loss screening presentation: tests/test_antenna_reference_config.py and tests/test_antenna_reference_panel.py preserve actual incomplete results and screen only when other inputs permit.

- `tests/test_control_transport_health.py` — Pure controller retry/generation, health expiry, invalid-clock and immutable snapshot regression tests; no hardware.

- `tests/test_control_session_v2.py` — Strict wire, challenge age, replay and constant-state session tests.
- `tests/test_recovering_control_source.py` — Fake-device lifecycle, owner-thread, queue expiry/overflow and cancellation tests.
- `tests/test_control_firmware_recovery.py` — Native real-firmware GPIO/serial stubs and Python wire interoperability; requires g++.

- `tests/test_control_recovery_gate.py` — Current-session dispatch filtering, obsolete nonce rejection, bounded state over many sessions and inert opt-in factory tests.


Issue246 regressions live in test_wavelog_history.py (full totals, last band,
contradictory data), test_callsign_info.py/test_forge_callsign_info.py (shared
history, legacy response defaults), test_forge_contact_sync.py (old pending and
synchronized claim hashes/changed payload rejection), and existing contact
metadata/logging/commit/weather plus Wavelog tests (blank/explicit notes).

- `tests/test_meshcore_passive.py` — synthetic v1.17.1 metadata payload, full-key collisions, 0x8A layout, unsupported frames, malformed lengths, no path synthesis.
- `tests/test_meshcore_observation_repository.py` — isolated version-1 MeshCore-only SQLite tables, append-only identity summaries, valid/missing/stale/future/low-quality immutable GPS snapshots, invalid timestamp, no serial dependency.

- `tests/test_meshcore_passive_worker.py` — disabled worker, nonblocking bounded queue/overflow evidence, safe unsupported-frame handling, immutable GPS snapshot timing, deterministic shutdown.

- `tests/test_meshcore_inbound_frames.py` — synthetic fragmented, concatenated, oversized and malformed serial frames; ensures inbound-only decoder and 176-byte firmware bound.

- `tests/test_meshcore_serial_service.py` — fake UART read-only boundary, missing-device degradation, physical path selection, V3/V4 USB VID/PID/transport validation, native CDC DTR policy, and no outgoing command.
- `tests/test_meshcore_runtime_integration.py` — default-disabled runtime, invalid USB path rejection, and opt-in isolated database composition with no device access during configuration.

- `tests/test_contact_retry.py` includes durable 1500-failure overflow regression (next due at configured cap), persisted eligibility after repository recreation, and finite pre-cap doubling behavior; verifies repeated remote HTTP 503 cannot overflow the scheduler backoff calculation.


- `tests/test_meshcore_collector_main.py` — local-only HTTP-over-Unix API health/list/query responses, no mutation, no main QSO table.
- `tests/test_meshcore_gps_bridge.py` — asynchronous atomic GPS publication, no second GPS receiver, stale/unavailable fix rejection.
- `tests/test_meshcore_observation_repository.py` — schema v1→v2 migration preservation and anonymous signal metrics storage.
- `tests/test_meshcore_runtime_integration.py` — legacy config flag no longer constructs embedded serial worker; only shared GPS publisher remains.

## MeshCore intelligence classification

- `tests/test_meshcore_incident_classification.py` — hardware-free classification categories, channel allowlisting, invalid input, unknown reports and conservative no-geocoding extraction. This does not prove live RF reception.

- `tests/test_meshcore_traffic_georeferences.py` — bounded references, ambiguity and unknown incident rejection.
- `tests/test_meshcore_traffic_gps_samples.py` — one-Hz snapshot reading and multi-fix validation.
- `tests/test_meshcore_traffic_geocoding.py` — default-disabled provider, cache, throttling and specificity.
- `tests/test_meshcore_traffic_relevance.py` — freshness, motion, site evidence and zero-alert behavior.
- `tests/test_meshcore_traffic_analysis.py` — injected offline provider, fail-closed before lookup.
- `tests/test_meshcore_geographic_relevance.py` — stationary/stale/invalid GPS, jitter, implausible motion, heading and direction, route-confidence distinction and distance limits.

- `tests/test_meshcore_network_analytics.py` — read-only schema-2 SQL, UTC window bounds, missing/wrong database rejection, role/count integrity, receiver-location semantics and cell limits.

- `tests/test_meshcore_collector_main.py` also asserts the private `GET /v1/activity` bounded response, absence of public query controls, and 405 on write methods; no real serial or radio fixture.

- `tests/test_meshcore_public_intake_protocol.py` — exact v1.16 channel identity/fingerprint, malformed reply rejection, private/binary redaction, legacy/V3 message framing, untrusted timestamps and opcode fuzz coverage; no live hardware.

## MeshCore message broker

- `tests/test_meshcore_message_broker.py` — privacy stream separation, independent cursor/restart, file security and backpressure
- `tests/test_meshcore_broker_drain.py` — fake host-local commands, channel mismatch, commit before next dequeue and timeout failures
- `tests/test_meshcore_broker_serial_integration.py` — fake Heltec framing through existing reader into durable public/private streams
- `tests/test_meshcore_broker_config.py` — owner-only config, strict channel/token fields and scope rejection
- `tests/test_meshcore_broker_api.py` — token isolation and independent stream acknowledgement over Unix socket
- `tests/test_meshcore_broker_cli.py` — disabled-by-default startup gates and existing socket ownership protection

- `tests/test_meshcore_channel_audit.py` — fake-response channel audit, key redaction, only permitted local commands, malformed identity and bounds

- `tests/test_meshcore_public_consumer.py` — actual Unix API/SQLite integration for independent preview, explicit ACK, permission failures and private isolation
- `tests/test_meshcore_public_intelligence.py` — exact traffic provenance and no-alert classification for nontraffic/unknown text
- `tests/test_meshcore_public_consumer_main.py` — bounded preview command, unverified labels, and no implicit ACK

- `tests/test_meshcore_traffic_worker.py` — durable ledger, idempotent ACK replay, duplicate suppression, capacity/storage failures and secure file modes
- `tests/test_meshcore_traffic_worker_integration.py` — full local Unix broker public/private separation, independent consumer cursors, commit-before-ACK and repeated public traffic deduplication
- `tests/test_meshcore_traffic_worker_main.py` — standalone one-shot real Unix broker/ledger/ACK path, independent SCOUT cursor, exclusive worker lock and CLI argument validation
- `tests/test_meshcore_traffic_worker_service.py` — staged user-unit isolation, polling, backoff, conservative hardening/resource cap and non-transmitting configuration

### Forge MeshCore geographic evidence and analysis audit tests
- tests/test_forge_meshcore_geo_catalog.py: exact matching, provenance, review age, privacy.
- tests/test_forge_meshcore_geo_import.py: reviewed JSON schema and bounded offline import.
- tests/test_forge_meshcore_geo_main.py: stable read-only CLI and no-match.
- tests/test_forge_meshcore_geo_adapter.py: injected provider interoperability without network.
- tests/test_meshcore_traffic_analysis_repository.py: immutable audit, privacy, read-only bounds.

### OHGO incidents and MeshCore combined context

- `tests/test_forge_ohgo_incidents.py` — safe parsing, no-key, ETag/caching, stale/upstream failures.
- `tests/test_forge_ohgo_credentials.py` — systemd-only key loading and symlink/malformed protection.
- `tests/test_forge_ohgo_api.py` — retained read-only route and existing Forge endpoint delegation.
- `tests/test_meshcore_ohgo_panel.py` — disabled/stale/live-safe presentation and no Tk network I/O.
- `tests/test_context_navigation.py` — new `o` context and full-cycle invariants.

- `tests/test_meshcore_ohgo_ui.py` — context-gated rotary isolation, scroll persistence, new-data top reset and actual-overflow MORE behavior (mock Tk, no radio).
- `tests/test_meshcore_ohgo_panel.py` — all bounded OHGO incidents displayed with separators without four-item truncation.

- tests/test_meshcore_ohgo_ui.py also guards against OHGO widget geometry
  toggling on repeated refreshes and redundant MORE StringVar writes.
