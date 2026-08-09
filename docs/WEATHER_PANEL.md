# Weather Panel and Map Temperature

Checkpoint #165 presents the retained Pi weather state implemented by #164. It adds no provider, network, filesystem, SQLite, radar, repeater, or CAT behavior.

## Single presentation path

`ApplicationRuntime.latest_forge_weather_state` remains the application-facing immutable source. `WeatherPanelController` converts that state into one immutable `WeatherPanelPresentation`.

The same presentation is consumed by:

- the dedicated WEATHER context; and
- the live-map information box Local Temp field.

The map does not independently convert temperature, calculate weather age, inspect provider health, or read storage. This prevents the weather panel and map from disagreeing about temperature or freshness.

## Displayed weather

When a usable retained snapshot is present, the WEATHER context shows:

- current Fahrenheit and Celsius temperature;
- relative humidity;
- normalized Rolling Thunder condition and icon semantics;
- local sunrise and sunset;
- the next three future hourly temperature values in Fahrenheit and Celsius;
- precipitation probability for those same three hours; and
- provider attribution.

Past hourly points are skipped. If fewer than three future points remain in the retained snapshot, missing cells use explicit placeholders rather than inventing values.

## Truthful state and color

Weather presentation uses a deliberately small operator vocabulary:

- `LIVE` — light blue;
- `RETAINED` — yellow;
- `STALE` — yellow;
- `DISABLED` — gray;
- `UNAVAILABLE` — gray;
- `ERROR` — red.

The detail line includes the age derived from the provider `source_at` timestamp. Restarting the Pi or refreshing the dashboard does not reset that age.

A local transport, validation, or storage error does not blank a still-valid retained snapshot. The panel changes to red `ERROR`, identifies the failure category, continues to show the retained forecast, and displays the original source age. #165 introduces no independent age-out rule; it presents whatever immutable snapshot #164 still considers available, while marking stale data truthfully.

## Context navigation

WEATHER participates in the normal physical `NEXT_CONTEXT` cycle. Existing direct shortcuts 1 through 5 remain unchanged; keyboard shortcut 6 selects WEATHER for development and installed-display testing. No new physical-control mapping is required.

## UI-thread boundary

`WeatherPanelController`, `WeatherWidgets`, and the map Local Temp projection perform no:

- HTTP or provider calls;
- filesystem access;
- SQLite access;
- sleeps or waits; or
- radio/CAT operations.

The 250 ms Tkinter refresh reads only immutable state already published by the #164 background worker and updates widgets.

## Radio safety

Checkpoint #165 has no PTT, MOX, keying, tuner, transmit-power, receive-tuning, or unattended-transmit authority. Weather availability or failure cannot block local logging, GPS, map base tiles, radar, physical controls, radio polling, or shared POTA/DX operation.

## Acceptance

Before merge, the exact PR head must satisfy:

- pure presentation tests for live, retained, stale, unavailable, disabled, and error states;
- proof that an error preserves still-valid retained weather;
- map-info integration tests proving Local Temp consumes the shared weather presentation;
- status-color tests;
- Ruff, strict MyPy, full pytest, pre-commit, and `git diff --check`;
- GitHub Actions on the exact accepted head;
- full-screen readability acceptance on `anvilmobile`; and
- controlled retained/offline visual acceptance without disrupting Forge for other consumers.

The pull request remains unmerged until explicit repository-owner authorization.
