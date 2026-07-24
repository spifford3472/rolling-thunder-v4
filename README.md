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

**Milestone 1 — Typed Configuration**

The current milestone establishes the application's centralized configuration
boundary:

- strongly typed configuration models
- YAML input
- validation with actionable errors
- mock-hardware mode
- machine-local settings outside source control
- automated tests that require no connected hardware or network services

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
