# Changelog

## v4.3.0 — experimental development

### FT8 Checkpoint 9 — acceptance complete; merge pending owner approval

- completes native FT8 MVP product integration on top of the merged CP2-CP8.1 runtime
- adds a first-class FT8 dashboard context and presentation-owned CQ selection
- routes keyboard/physical controls through the existing FT8PanelController boundary
- exposes bounded per-state retry progress without exposing CAT/PTT/audio internals to the UI
- hardens partial-startup rollback so already-started FT8 resources are stopped after later startup failure
- validates disabled, receive-only, DigiRig reconnect, CAT disconnect fail-closed, ABORT, retry exhaustion, successful-QSO, frozen-grid, shutdown, and Raspberry Pi resource behavior on installed hardware
- completes a real 5 W FT8 QSO with KE5ETC on 7.074 MHz, including directed report exchange, final acknowledgement, final 73, frozen GPS grid EM79xm, and exactly one isolated schema-14 FT8 contact
- confirms an incomplete live QSO with W5XO is not logged
- records five continuous receive periods with 35 decodes, zero dropped periods, about 3.1% average of one CPU core, and about 50 MB Python peak RSS on anvilmobile
- passes the full repository regression suite at CP9 acceptance: 2337 passed, 7 skipped, Ruff clean, and git diff check clean
- keeps production migration, schema-14 installation, release tagging, and PR merge separately owner-approved

### FT8 Checkpoint 8.1 — complete

- replaces UTC-boundary arecord startup with persistent continuous capture
- drains PCM continuously into a bounded absolute-sample rolling buffer
- extracts exact 180000-sample 12 kHz FT8 periods at UTC boundaries
- preserves automatic DigiRig disconnect/reconnect recovery without orphaned arecord processes


### FT8 Checkpoint 8 — complete

- adds first-class `RadioMode.FT8` for successful-contact logging while preserving USB/DATA as the physical FT-891 execution mode
- adds schema v14 support for FT8 contacts without creating a parallel FT8 database or sync path
- gives each authorized FT8 QSO a stable UUID used as the durable contact/idempotency key
- logs only immutable `COMPLETED` results with actual signed dB reports, original QSO start time, frozen frequency, and frozen local Maidenhead grid
- preserves a selected remote CQ grid when available and otherwise reuses existing QRZ enrichment
- reuses the existing local SQLite -> ContactSyncService -> Forge -> Wavelog path
- serializes successful native FT8 contacts as ADIF `MODE=FT8`
- keeps POTA/DX FT8-session launching as a future enhancement rather than expanding Checkpoint 8 scope

### FT8 Checkpoint 7 — complete

- adds a QSO-specific physical authorization path separate from CP6 owner-test authorization
- adds a production `DigitalTransmitSession` bridge using the validated encoder and bounded FT-891/DigiRig executor
- requires exact frozen context, DATA mode, frequency verification, correct parity, and a safe slot-start window before keying
- preserves the validated 15-second encoder reference PCM and derives runtime RF timing from its final non-zero sample plus release margin
- fans normalized receive decodes to one active QSO coordinator while CQ browsing continues independently
- adds immediate ABORT/failure cancellation toward RX, single-active-QSO ownership, and immutable terminal results
- adds separate `ft8.transmit.enabled` gating so receive-only FT8 creates no transmit resources
- adds a presentation-safe CQ browser controller that can select only one currently visible CQ and never auto-selects a second station
- keeps successful-contact persistence/Wavelog writes outside Checkpoint 7
- remains blocked from live automated RF until deterministic acceptance is green and the owner explicitly approves physical testing

### FT8 Checkpoint 6 — complete

- begins the controlled FT-891 / DigiRig hardware-transmit boundary
- keeps physical transmit disconnected from `FT8QsoController` and live CQ activity
- preserves disabled-by-default behavior and the protected v4.2.0 rollback point
- physically validated Enhanced-CAT `TX1;`/`TX0;`, left-only DigiRig playback, bounded key-down, watchdog release, and CAT meter monitoring
- established FT-891 DATA DATA GAIN 20 as the best tested ALC setting at the configured 5 W dummy-load test level

### FT8 Checkpoint 5 — complete

- reconciles the CQ-answer QSO sequence before physical transmit work
- freezes the outbound FT8 signal report in the authorized QSO context
- adds a project-owned offline encoder/waveform boundary
- reuses the pinned `kgoba/ft8_lib` encoder instead of reimplementing CRC/LDPC/Costas logic
- validates deterministic 79-tone, 12 kHz mono S16_LE 15-second slot waveforms
- adds no playback, PTT, CAT TX, runtime transmit worker, logging, or RF

### FT8 Checkpoint 4

- adds typed receive-only DigiRig audio configuration and `FT8AudioInput`
- validates ALSA `plughw:CARD=Device,DEV=0` direct conversion to 12 kHz mono S16_LE
- adds UTC-boundary-aligned persistent `arecord` capture
- adds bounded background capture/decode workers with reconnect and degraded state
- connects live `Ft8LibDecoder` output to the existing `FT8CQActivityManager`
- physically validates clean live audio and 11 real on-air decodes in one direct decoder period
- validates application-composed live receive across two consecutive periods with 19 decodes, 4 CQ activities, zero drops, and clean shutdown
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
