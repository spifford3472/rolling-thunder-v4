# CP3.1 VOACAP longitudinal foundation

Existing Forge has `VoacapSummaryClient`, a per-completed-QSO `qso_voacap_prediction` table and provider-disabled-by-default configuration; it does **not** yet prove regular forward-issued, hourly forecasts. The per-QSO upsert is not an append-only model evaluation history and must not be reused as such without a separate migration.

`voacap_forecast_trends.py` is an intentionally provider-independent comparison primitive. It will report a difference only for the same path identity, equipment assumptions, band, model version and America/New_York wall-clock hour on the previous calendar day. It rejects hindcasts for historical forecast comparisons, reports absent data neutrally and flags DST ambiguity. Differences are in dB (predicted SNR) and fractions (modeled reliability, *not* calibrated contact probability).

Next production schema should append `forecast_run` (provider/version, issue time, input/source snapshot and collection state), `forecast_path` (frozen origin six/four grid, target grid uncertainty, band, equipment model), `forecast_prediction` (run/path/valid UTC time, predicted metrics, input hash, unique dedup key) and `forecast_evaluation` (later observational labels kept distinct). Limit paths/hour, retention, deduplication and snapshots; use Forge only, offline-safe cached publication to Pi. External VOACAP endpoints and provider authorization are **not verified**. Do not activate automatic collection or claim statistical probability until they are.

Status: pure logic and tests only. No production schema, cron/provider polling, API/UI, RF or deployment change.

## Implemented opt-in archive contract

`forge_voacap_forecast_archive.py` provides a dedicated SQLite event archive that is **not attached to any production worker or provider**. The archive stores model version, issued and valid UTC time, identity of the path, band and equipment assumptions, source identity, input-hash provenance, collection time, and forecast-versus-hindcast classification. It uses a deterministic event identity and SHA-256 digest, preserves repeated forecasts for a future hour when issuance time changes, and rejects mutated replays. A 16 KiB row limit bounds individual payload size. The repository has no remote API, scheduling, pruning, telemetry delivery or live radio controls yet; future service owners must establish total storage budgets and retention before activating capture. All contents supplied to the archive must be free of credentials.
