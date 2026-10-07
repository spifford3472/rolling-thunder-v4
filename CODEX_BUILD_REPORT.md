# Codex Overnight Build Report

## Outcome

Implemented and reviewer-corrected the local QSO contract plus an undeployed Forge
propagation-history foundation. No production host, service, database,
configuration, systemd unit, runtime tree, Wavelog instance, secret, or main branch
was changed. The reviewer-directed pass did not modify the KC2G interpolation or
PSK Reporter adapter files reserved for specialist follow-up.

## Diagnoses

### Six-character `MY_GRIDSQUARE`

The baseline path already preserves the full frozen grid through `Contact`, SQLite,
Pi JSON, Forge validation, and Wavelog ADIF. Dynamic station routing alone truncates
to four characters. The adapter regression proves a dynamic profile of `EM79` is
submitted with `<MY_GRIDSQUARE:6>EM79xm`. The observed Wavelog value of `EM79`
therefore occurs after the correct import payload crosses the Wavelog provider
boundary. This build does not invent an undocumented post-import Wavelog mutation.

### FT8 performance uploads stopping independently

`ThreadScheduledPoll` terminates when its callback raises. The FT8 performance
worker caught only `HomePlatformError`; SQLite/decode/state failures escaped and
silently killed only that worker thread. Contact sync has a separate scheduler and
therefore continued posting `/contacts`.

The worker now contains scheduled-run failures, preserves retryability, and exposes
running state, last attempt/success/error, and consecutive failed-run count. A
regression test invokes repeated repository failure and proves the scheduled worker
remains active and observable.

## QSO contract changes

- `ContactSource`: `pota`, `dx`, `browse`, `ft8`, `dmr`, and legacy `unknown`.
- Nullable `tx_power_watts`; ADIF emits `TX_PWR` only when known.
- One authoritative six-character local grid with explicit `my_grid6`/`my_grid4`
  and `local_grid6`/`local_grid4` accessors. Four-character station identity is
  derived and cannot drift; Wavelog QSO ADIF and analytics retain grid6.
- Nullable structured contact/local weather observations include provider identity,
  observation/fetch time, coordinates, normalized condition, temperature, and
  humidity when lookup succeeds.
- Immutable `weather_notes_enabled`; Forge reuses the existing typed Open-Meteo
  provider, prefers frozen POTA coordinates over remote-grid center, uses frozen
  local coordinates, freezes the first result for deterministic retry, and falls
  back independently to `N/A` without preventing Wavelog sync.
- FT8 reads configured power in the coordinator terminal callback before the later
  100 W context-exit restore and shares that snapshot with performance telemetry.
- Ordinary POTA/DX/Browse power reads occur on the existing background commit worker.
- Central application controls: `contact_logging.capture_tx_power` and
  `contact_logging.append_weather_notes`.
- Local schema 19 adds source, power, weather JSON, and weather-note flag columns;
  schema 20 adds frozen contacted-station coordinates for exact POTA weather lookup.
- Contact export format 5 preserves the expanded immutable payload while formats
  1–4 remain accepted with safe defaults.

Weather data remains nullable. Local commit never performs network work. The
existing Pi contact-sync worker invokes bounded Forge enrichment, and provider or
location failure proceeds to Wavelog with the required explicit `N/A` lines.

## Propagation-history component

Added a dedicated SQLite repository and disabled example configuration. Tables are:

- `solar_observation`
- `kc2g_snapshot`
- `weather_observation`
- `qso_observation`
- `qso_ionosphere`
- `qso_voacap_prediction`
- `qso_pskreporter_summary`

HamQSL collection preserves complete XML, every requested raw text field, source
updated text, source URL, and independent UTC collection time. KC2G collection
archives complete gzip-compressed MUF(3000)/foF2 GeoJSON plus URL and SHA-256. The
offline interpolation helper performs deterministic inverse-distance interpolation
for Point-grid features.

The VOACAP client reuses `/version` and `/api/v1/summary`, passes full frozen grids,
actual band/power, UTC year/month/timezone, and `mode=FT8` for FT8. It stores exact
request/response provenance and derives actual hour/band MUF, reliability, rating,
and SNR when present.

## Safe limitations

- The new Forge component is not deployed or wired to production QSO ingestion.
  `correlate_contact` is ready for an independently supervised background boundary;
  no analytics call was added to contact sync.
- Exact live KC2G contour geometry was not inspected offline. Complete snapshots are
  archived, Point-grid fixtures are supported, and unsupported shapes return no
  value. Great-circle path-minimum MUF remains documented follow-up work.
- PSK Reporter has schema, explicit status, batch interface, latency/window controls,
  and a five-minute minimum. The network adapter is intentionally disabled because
  authoritative official retrieval semantics were not established; configuration
  fails closed if enabled.
- No live radio/full-screen/Forge/Wavelog acceptance was performed.

## Validation

- Reviewer-focused core tests: **219 passed**.
- Full `pytest` with no ignores: **2,812 passed, 7 skipped** out of **2,819
  collected** on Python 3.12.3. The skips are the suite's existing declared skips.
- `ruff check src tests`: **passed**.
- `mypy src/rolling_thunder`: **passed**, 273 source files.
- `git diff --check`: **passed**.
- The three protocol tests now import `typing_extensions.get_protocol_members`, and
  `typing-extensions>=4.15` is an explicit development dependency for Python <3.13.
- Pre-commit with the repaired canonical shared venv on `PATH`: **Ruff passed,
  MyPy passed, Pytest passed**. An initial direct launcher invocation found the
  pre-commit package but reported `ruff`, `mypy`, and `pytest` missing because the
  local `language: system` hooks do not prepend the launcher's venv automatically;
  no hook or check was bypassed or weakened.

## Commits

- `8375a56 Correct QSO contracts and enrichment reliability`
- Documentation and this report are committed separately in the follow-up
  documentation commit.
