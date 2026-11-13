# USB and FT8 audio incident: 12–13 November 2026

## Status and evidence scope

**Incident documented; root cause unresolved.** This is an as-observed operational record, not proof of a particular failed cable, powered hub, microphone, or application defect. No production application deployment, restart, USB reset, or radio command is authorized by this document.

Read-only evidence inspected on `anvilmobile` on 13 November:
- `journalctl -k` for USB errors and enumeration.
- `lsusb -t`, `/proc/asound/cards`, `aplay -l`.
- `/home/geoff/.local/state/rolling-thunder-diagnostics/usb-events.jsonl`.
- Operator's FT8 failure screenshot at approximately 03:33 EST.

Some historical application log paths are empty or stale; complete FT8 application-state correlation is **not established**. Kernel journal boot metadata showed an anomalous July boot origin despite November timestamps; correlate using local wall-clock and device events, not boot ID alone.

## Observed topology (13 November afternoon)

The Pi's USB2 tree (`Bus 001`) contains an upstream four-port hub, with:
- port 1: Silicon Labs CP210x serial adapter (controller-related; confirm actual assignment).
- port 2: Microchip `0424:2412` two-port hub containing CP2105 `10c4:ea70` dual serial and C-Media `0d8c:0012` audio (Digirig).
- port 3: SanDisk mass storage SSD.
- port 4: four-port hub, with CP210x GPS and (during test) Seeed Studio reSpeaker XVF3800 USB microphone `2886:001a`.
- MeshCore USB receiver was intentionally disconnected for isolation.

The externally powered hub was on a separate LiFePO4 battery during testing. A Raspberry Pi `vcgencmd get_throttled` result of `0x0` does **not** establish the powered hub's voltage integrity. Exact hub model/port and upstream path mapping must be verified against physical wiring before hardware recommendations.

## Timeline (EST)

| Time | Evidence | Interpretation |
| --- | --- | --- |
| Nov 12 ~21:59 | Plugging in reSpeaker coincided with USB `-71` errors, hub disconnect/re-enumeration, and GPS loss/reappearance; operator saw Connected LED drop | Real USB disruption; hot-plug transient vs cable/power/hub fault not isolated |
| Nov 13 03:23 | reSpeaker disconnected and reappeared as full-speed (12 Mbps), then `Not enough bandwidth for new device state` and `can't set config #1, error -28` | USB periodic bandwidth reservation failure; 12 Mbps is normal for many audio devices, not by itself proof of a speed downgrade |
| Nov 13 03:31, 03:33 | Digirig path `1-1.2.2`: `Not enough bandwidth for altsetting 1`, `usb_set_interface failed (-28)`; operator FT8 panel showed `aplay set_params:1456: Unable to install hw params` for 12000 Hz, 16-bit stereo | ALSA playback could not obtain requested hardware parameters; USB bandwidth errors are strongly correlated, but the complete causal chain needs an application trace |
| Nov 13 04:45:03 | Microchip hub path `1-1.2`: 51 `clear tt ... error -71` messages, hub and Digirig audio/serial disconnect, 878 `cannot submit urb ... -19: no device` messages | A second, distinct hub/USB transport failure, on the Digirig branch |
| Nov 13 04:45:03–04 | Microchip hub, CP2105, and C-Media audio re-enumerated | Kernel-level recovery observed; application recovery unverified |

The standalone observer recorded topology transitions, but did **not** independently capture kernel messages, audio device negotiation, GPS freshness, or FT8 application transitions. Its JSONL records include unexpected clock timestamps around restarts; timestamps need a clock-quality/boot-ID indicator before precise cross-log correlation.

## Temporary diagnostic observer: actual installed state

An out-of-repository read-only script was installed at:
`/home/geoff/.local/bin/rt-usb-observer.py`

User service:
`/home/geoff/.config/systemd/user/rt-usb-observer.service`

Log:
`/home/geoff/.local/state/rolling-thunder-diagnostics/usb-events.jsonl`

The observer polls `lsusb -t`, `/dev/serial/by-id`, `vcgencmd`, `/proc/loadavg`, and `/proc/meminfo` every five seconds. It emits topology changes and roughly one-minute heartbeats. Rotating file policy is 10,000,000 bytes with five backups (up to approximately 60 MB total). It does not open serial/audio devices or command radio hardware. On Nov 13 it was observed `active`. This is **temporary host-local instrumentation**, not a repository-managed or fully tested production diagnostic feature. Do not assume it is installed through the exact-SHA deployment wrapper.

### Read-only validation

```bash
systemctl --user status rt-usb-observer.service --no-pager
lsusb -t
cat /proc/asound/cards
aplay -l
journalctl -k --since '2026-11-13 03:00:00' --no-pager | grep -Ei 'bandwidth|error -28|error -71|error -19|USB disconnect'
ls -lh ~/.local/state/rolling-thunder-diagnostics/
```

Do not run playback tests, CAT/PTT, or USB resets during an active QSO. For timestamped event analysis, ignore malformed/incomplete JSONL lines and do not treat observer restart as an application restart.

### Rollback of temporary observer (separately authorized host change)

```bash
systemctl --user disable --now rt-usb-observer.service
```

Retain the JSONL evidence until archived. Only after explicit authorization, remove the standalone service file and script and reload user systemd. These commands are **instructions**, not actions performed by this documentation change.

## Proposed fixes and acceptance gates (not deployed)

1. Add a repository-owned, bounded, read-only USB observer with unit tests, structured device identity, kernel-event summaries, clock/boot identity, per-device transitions, rotation, and permission-safe deployment; never open hardware endpoints.
2. Add audio initialization diagnostics (ALSA device identity, supported rates/formats, selected device, `-28`/device-loss errors) without exposing secrets or issuing transmit.
3. Reproduce isolated FT8 playback configuration in an offline fake adapter; verify transmit fails closed on audio-device loss, with no PTT stuck active.
4. Conduct parked, receive-only USB isolation tests: Digirig baseline; GPS; reSpeaker; then optional MeshCore. Record USB2 bandwidth allocation and physical cabling; change one variable at a time.
5. Reconcile Issue #410 startup/supervision separately before modifying restart semantics; do not introduce a second dashboard process.
6. Preserve exact-SHA rollback and add hardware acceptance evidence before production rollout.

## Change history

- 2026-11-13: Initial evidence-based incident record and temporary observer inventory. Documentation-only repository change; no production change or hardware action.
