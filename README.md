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

**Milestone 4 — Radio Abstraction**

Milestones 1 through 3 have been implemented and audited:

- typed YAML configuration with validation and mock-hardware mode
- core contact, radio-state, GPS-position, and synchronization domain models
- durable SQLite contact logging, duplicate protection, export, backup, and recovery

The current milestone establishes the hardware-independent radio boundary:

- a typed radio interface
- a deterministic mock radio
- frequency, mode, and connection-state reporting
- safe band and frequency changes
- an FT-891 CAT adapter
- actionable disconnect and malformed-reply handling

The broader mobile logging workflow remains the product MVP and will be built
incrementally through the milestones documented in `docs/ROADMAP.md`.

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

## Security Boundary

Rolling Thunder does not control PTT and does not initiate transmission.

Voice, AI, remote APIs, and automated processes may not key the radio.
