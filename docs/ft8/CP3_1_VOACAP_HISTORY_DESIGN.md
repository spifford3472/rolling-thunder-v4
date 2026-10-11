# CP3.1 VOACAP longitudinal foundation

Existing Forge has `VoacapSummaryClient`, a per-completed-QSO `qso_voacap_prediction` table and provider-disabled-by-default configuration; it does **not** yet prove regular forward-issued, hourly forecasts. The per-QSO upsert is not an append-only model evaluation history and must not be reused as such without a separate migration.

`voacap_forecast_trends.py` is an intentionally provider-independent comparison primitive. It will report a difference only for the same path identity, equipment assumptions, band, model version and America/New_York wall-clock hour on the previous calendar day. It rejects hindcasts for historical forecast comparisons, reports absent data neutrally and flags DST ambiguity. Differences are in dB (predicted SNR) and fractions (modeled reliability, *not* calibrated contact probability).

Next production schema should append `forecast_run` (provider/version, issue time, input/source snapshot and collection state), `forecast_path` (frozen origin six/four grid, target grid uncertainty, band, equipment model), `forecast_prediction` (run/path/valid UTC time, predicted metrics, input hash, unique dedup key) and `forecast_evaluation` (later observational labels kept distinct). Limit paths/hour, retention, deduplication and snapshots; use Forge only, offline-safe cached publication to Pi. External VOACAP endpoints and provider authorization are **not verified**. Do not activate automatic collection or claim statistical probability until they are.

Status: pure logic and tests only. No production schema, cron/provider polling, API/UI, RF or deployment change.
