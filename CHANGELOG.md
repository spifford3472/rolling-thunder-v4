# Changelog

## v4.3.0 — experimental development

### FT8 Checkpoint 4 — in progress

- adds typed receive-only DigiRig audio configuration and `FT8AudioInput`
- validates ALSA `plughw:CARD=Device,DEV=0` direct conversion to 12 kHz mono S16_LE
- adds UTC-boundary-aligned persistent `arecord` capture
- adds bounded background capture/decode workers with reconnect and degraded state
- connects live `Ft8LibDecoder` output to the existing `FT8CQActivityManager`
- physically validates clean live audio and 11 real on-air decodes in one FT8 period
- keeps FT8 disabled by default and composes no FT8 resources when disabled
- adds no playback, PTT, CAT TX, waveform generation, automated QSO, logging, or RF

### FT8 Checkpoint 3

- adds a project-owned receive decoder protocol and mono signed-16-bit PCM period input
- adds saved-WAV subprocess adapters for `kgoba/ft8_lib` and `ft8mon`
- normalizes candidate output exclusively into the existing `FT8Decode` model
- adds safe timeout/process-failure handling and common FT8 message normalization tests
- adds a reproducible decoder bake-off ledger with pinned candidate revisions
- validates both native decoder candidates on the Raspberry Pi and compares them
  against an isolated official WSJT-X 3.0.2 saved-WAV oracle
- stores decoder input as compact immutable signed-16-bit little-endian PCM bytes
- selects `kgoba/ft8_lib` as the initial receive backend after the Pi bake-off,
  while retaining `ft8mon` as the higher-sensitivity comparison/fallback candidate
- remains receive-only with no live DigiRig audio, production worker, PTT, CAT TX,
  transmit audio, logging, or RF transmission

### FT8 Checkpoint 2

- adds disabled-by-default typed FT8 configuration
- adds immutable project-owned FT8 period, decode, CQ-activity, and QSO models
- adds UTC/monotonic FT8 clock abstractions with deterministic fake time
- adds in-memory CQ deduplication and four-period/60-second expiry
- adds a bounded fake-only QSO state machine with six attempts per unchanged state
- adds explicit ABORT, retry-exhausted, completion, error, and reset behavior
- adds a narrow logical transmit-session protocol with no physical implementation
- adds no decoder, audio capture/playback, PTT, CAT keying, database migration, or RF transmission

## v4.2.0 — 2026-09-28

Rolling Thunder v4.2.0 expands the mobile operating dashboard with improved startup,
offline mapping, POTA awareness, browsing, and callsign intelligence.

### Highlights

- systemd-managed Raspberry Pi dashboard autostart with an intentional startup delay
- nationwide POTA park catalog ingestion and refresh support
- regional offline DAY/NIGHT map packages with automatic solar style selection
- POTA park markers and labels integrated into the live map
- streamlined single-press shared POTA/DX receive tuning workflow
- Browse operating page for direct band/mode exploration
- Forge-backed callsign information overlay using QRZ identity, Wavelog contact history,
  and Open-Meteo current weather
- first-contact detection plus compact previous-contact summaries
- dedicated worldwide contact mini-map with consistent online tiles and POTA-location priority
- in-vehicle callsign overlay typography, weather, history strip, map marker, and layout refined
  through installed-hardware acceptance testing

### Safety boundary

Rolling Thunder v4.2.0 preserves the existing receive-only software control boundary.
The release does not add PTT, MOX, CW keying, tuner, power-control, automatic-transmit,
or unattended-transmit authority.

## v4.1.0 — 2026-09-25

First official Rolling Thunder v4 release.

### Highlights

- local-first SQLite contact logging with backup, export, retry, and synchronization support
- typed Yaesu FT-891 integration with receive-side state, safe receive tuning, and no software transmit authority
- real GPS integration with position, Maidenhead grid, speed, heading, UTC handling, and recovery behavior
- shared POTA and DX operating panel with filtering, stable selection, two-press receive tuning, and POTA worked-state tracking by callsign, mode, and band
- offline-first live mapping with installed regional map packages, persistent zoom, day/night map styles, map health, and radar/weather integration
- DMR activity and logging support plus repeater discovery/configuration workflows
- physical ESP32 control support and voice callsign capture through the same application command boundaries
- Wavelog/contact synchronization support
- revised Settings presentation with consistent Map Zoom, Map Style, and Radar Image controls
- background workers and typed boundaries that keep network, serial, SQLite, filesystem, map, radar, and speech work out of the Tkinter UI thread

### Safety boundary

Rolling Thunder v4.1.0 does not provide PTT, MOX, CW keying, tuner, power-control,
automatic-transmit, or unattended-transmit authority. Voice, AI, network services,
and physical controls do not independently key the radio.
