# Forge Propagation History

## Scope and status

The repository contains an independent, presentation-neutral Forge propagation-
history component. It is not deployed by this change. No systemd unit, production
configuration, runtime tree, or production database is changed.

The opt-in entry point is `rolling-thunder-forge-propagation --config PATH --once`.
The example configuration is disabled. The component owns its own SQLite database;
it must not point at the contact-sync or spot/weather databases.

The current entry point wires only the hourly HamQSL and KC2G collection cycle.
It does not ingest QSOs, schedule QSO correlation, or invoke VOACAP, weather
enrichment, or PSK Reporter analytics. Their typed fields and adapters are retained
for a future independently supervised QSO-ingestion worker, and all three controls
default to false.

## Data model

The schema retains raw observations as well as derived QSO features:

- `solar_observation`: complete HamQSL XML, raw required field strings, source
  update text, source URL, and an independent UTC collection timestamp.
- `kc2g_snapshot`: complete gzip-compressed GeoJSON bytes, source URL, SHA-256,
  metric, and UTC collection timestamp.
- `weather_observation`: reserved structured QSO weather observations.
- `qso_observation`: immutable serialized Contact keyed by `contact_id`.
- `qso_ionosphere`: reserved per-QSO ionosphere features.
- `qso_voacap_prediction`: exact request, service version, complete response, and
  actual UTC-hour/band MUF, reliability, rating, and SNR when present.
- `pskreporter_query`: one complete PSK Reporter provider-query payload and its
  parameters, result state, timing, parse count, and error provenance.
- `qso_pskreporter_summary`: explicit per-QSO collection status, eligibility
  audit, provider-query reference, and matched parsed reception facts.

Collectors enforce a minimum one-hour interval per source. Failures are isolated;
one provider cannot suppress the others.

## Providers

HamQSL uses `https://www.hamqsl.com/solarxml.php`. Raw text is preserved because
several values are categorical or decorated strings. `collected_at_utc` is a local
timestamp and is never inferred from the source `<updated>` value.

KC2G archives the complete current interpolated MUF(3000) and foF2 GeoJSON files as
gzip-compressed, SHA-256-verified raw snapshots so estimates can be recomputed.
Estimator `contour_idw_v1` reads `level-value` isolines from both `LineString` and
`MultiLineString` features, measures geodesic distance to contour segments, and
produces endpoint estimates. QSO paths are great-circle sampled at no more than
100 km spacing with a hard cap of 512 samples; the stored path MUF is the minimum
sampled MUF estimate. Correlation uses the nearest snapshot within 90 minutes of
the QSO, preferring the earlier snapshot on an exact tie.

VOACAP calls the existing `/version` and `/api/v1/summary` endpoints. It sends the
full frozen grids, actual QSO band and configured TX power, UTC year/month/timezone,
and maps FT8 to `mode=FT8` even though its hardware setting is FT-891 HF/SSB power.
Correlation is best-effort and belongs on a background worker, never the contact-
sync request path. `voacap_enabled` and `weather_enrichment_enabled` are reserved
for that future worker and are not acted on by the current `--once` collector.

## PSK Reporter FT8 analytics

The disabled-by-default PSK Reporter adapter uses the official
`https://retrieve.pskreporter.info/query` XML endpoint. One adapter instance permits
at most one network attempt per 300 seconds, including after a failed attempt. Due
FT8 QSOs are batched into one recent-window request using `senderCallsign`, `mode=FT8`,
a negative `flowStartSeconds`, `rronly=1`, `noactive=1`, `nolocator=1`, a bounded
`rptlimit`, and a URL-encoded `frange` spanning the due QSO frequencies. Requests have
typed timeout, response-size, 24-hour-window, and report-count limits.

A QSO is not eligible before its FT8 terminal `ended_at_utc` plus
`report_latency_s`, whose safe default and minimum are both 300 seconds. Completion
lookup is keyed by the stable contact UUID, which is the FT8 attempt UUID. When the
terminal time is not yet available, eligibility conservatively falls back to
`Contact.started_at + correlation_window_s + report_latency_s`; malformed, naive,
or pre-start completion timestamps fail closed without a network request. Every
per-QSO summary records the reference source, reference time, and resulting
eligibility time. Successful zero-report results and successful report-bearing
results are terminal only after that boundary and are read from SQLite before
completion lookup or retrieval, so a completed window is not queried again after
process restart. Failures remain explicit and retryable. Persisted states distinguish
`not_queried`, `not_due`, `query_failed`, `queried_zero_reports`, and
`queried_with_reports`; provider, HTTP, size, decode, and document-parse failures
never become zero reports.

Correlation policy `rolling_thunder_ft8_time_frequency_v1` accepts only the configured
sender, FT8 records (with query-filter provenance when the optional record mode is
absent), the same amateur band, frequencies within 10 kHz, and report timestamps from
60 seconds before through the configured post-QSO window. When multiple QSOs overlap,
the closest time/frequency candidate receives the report. The complete raw provider
XML and query provenance are stored once in `pskreporter_query`; every QSO row
references that query and retains only its own matched parsed reception facts,
canonical receiver summaries, report count, unique grids, strongest/weakest SNR,
and furthest receiver when both coordinates are known. One batched response is never
duplicated across the QSO rows it serves.

Receiver coordinates come only from the center of a structurally valid Maidenhead
locator. Missing and malformed locators remain explicit with null coordinates. There
is no authoritative DXCC/continent resolver in this subsystem, so continent is stored
as null (including the explicit unknown group) rather than inferred from longitude or
callsign prefixes.

## Remaining integration

This pass does not wire a production scheduler or contact ingestion API. Before
deployment, add an independently supervised background ingestion boundary that passes
recent immutable QSOs and an FT8 terminal-completion provider to
`PskReporterAnalyticsService`; keep that worker outside contact sync. Live-provider
acceptance for PSK Reporter remains required before deployment.
