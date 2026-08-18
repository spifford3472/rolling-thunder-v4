# Rolling Thunder v4

Rolling Thunder is a Raspberry Pi-based mobile amateur-radio operating and
logging console.

Its first milestone is an end-to-end mobile logging workflow using:

- Yaesu FT-891 CAT state
- GPS position and UTC
- Voice callsign capture
- ESP32 physical controls
- Explicit Commit or Discard
- Local SQLite storage
- Offline-first operation

## Architecture

The authoritative design is:

`docs/RollingThunder_v4.1.0_Architecture_Specification.md`

## Current Milestone

**Milestone 10 — Hardware-Backed Mapping and Operating Intelligence**

The current checkpoint implements the shared POTA/DX operating-intelligence
panel tracked by GitHub issues #129 and #146.

The running Raspberry Pi dashboard now provides:

- one provider-neutral shared panel for POTA and DX
- durable Forge-derived last-known spot snapshots
- POTA band, mode-group, and age filtering
- DX callsign, frequency, mode, age, optional name/grid, and bounded metadata
- stable identity-based selection across snapshot refreshes
- physical-controller and keyboard navigation through the same command path
- first-action staging with explicit cancellation and invalidation
- truthful live, cached, retained, disabled, and provider-health presentation
- local-first contact logging independent of Forge availability

When Forge is enabled, live POTA and DX ingestion is owned by Forge. The Pi does
not also poll the public POTA API directly. The legacy direct-POTA
implementation and cache remain only as a rollback/compatibility path when
Forge is disabled.

Checkpoint 7 intentionally does not tune the radio from the new shared panel.
Activation stages the selected spot only. Checkpoint 8 will connect the second
explicit operator confirmation to the existing typed `ReceiveTuningService`.

The temporary checkpoint-7 Forge-to-Pi bench has been validated with real POTA
and DXSpider data and the installed physical controls. Permanent Forge systemd,
service-account, firewall, authentication/TLS, and deployment hardening remain
checkpoint-8 work.

## Configuration

Create a machine-local configuration from the safe example:

```bash
cp config/rolling-thunder.example.yaml config/rolling-thunder.yaml
```

Edit `config/rolling-thunder.yaml` for the local machine. The local file is
ignored by Git and must not contain passwords, API keys, private keys, access
tokens, or other credentials.

Mock hardware mode is enabled in the example configuration so development and
tests do not require connected radio or GPS hardware.

Configured radio and GPS device paths must be absolute Linux device paths, such
as `/dev/ttyUSB0` or `/dev/ttyACM0`. Relative database paths are resolved from
the directory containing the YAML configuration file, so the database location
does not change when Rolling Thunder is launched from a different working
directory. Absolute database paths are preserved unchanged.

The typed loader can be used from Python with:

```python
from pathlib import Path

from rolling_thunder.config import load_config

config = load_config(Path("config/rolling-thunder.yaml"))
```

Configuration validation failures identify the affected setting and provide
corrective information.

Optional receive-only MeshCore channel notifications use a USB companion device
and a dedicated typed `meshcore` configuration section. See
`docs/MESHCORE.md` for the stable device-path, channel, timing, and live-only
startup behavior.

## Security Boundary

Rolling Thunder does not control PTT and does not initiate transmission.

Voice, AI, remote APIs, and automated processes may not key the radio.
