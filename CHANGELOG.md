# Changelog

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
