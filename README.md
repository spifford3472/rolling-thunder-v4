# Rolling Thunder v4.3.0

Rolling Thunder is a Raspberry Pi-based mobile amateur-radio operating and
logging console.

**v4.3.0 is the current official Rolling Thunder release.** Native FT8 is now
a supported part of the integrated mobile operating system after deterministic,
repository, and installed-hardware acceptance.

The platform includes an end-to-end mobile logging and operating workflow using:

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

## Current Release

**v4.3.0 — native FT8 plus the v4.2 mapping and operating-intelligence platform**

The current Raspberry Pi dashboard combines the shared POTA/DX workflow,
local-first map stack, and a first-class native FT8 operating context. The
installed mobile build provides:

- regional offline DAY and NIGHT MBTiles for Ohio, Indiana, Kentucky, Michigan,
  Pennsylvania, and West Virginia from the external RT_DATA SSD
- automatic solar DAY/NIGHT map selection with manual override support
- persistent operator zoom across the installed zoom range
- retained weather-radar overlay support without blocking the base map
- an offline POTA park catalog stored separately from the contact database
- visible-viewport POTA marker queries on a background worker
- yellow reference/name labels at zoom 14 and above
- 24-pixel yellow/black park dots below zoom 14
- a 60-second last-valid-GPS grace period so brief GPS loss does not flash park
  markers on and off
- safe behavior when a viewport contains no parks or radar is disabled
- local contact logging and radio/physical-control operation independent of map,
  POTA-marker, radar, Forge, or public-network availability
- native FT8 receive/decode and CQ browsing using the installed DigiRig audio path
- explicit single-station FT8 QSO authorization with bounded retries and no auto-next
- verified FT-891 FT8 preparation at 20 W with SSB-BFO USB and restoration to
  100 W / SSB-BFO AUTO when leaving FT8
- successful FT8 contacts through the normal local-first logging/Wavelog sync path
- separate successful/failed/aborted FT8 performance telemetry for future analysis
- color-vision-aware FT8 CQ state presentation with redundant status markers

POTA coordinates are approximate catalog pins. They are useful for operator
awareness but are not navigation destinations or activation-boundary evidence.

The earlier park-boundary polygon/PAD-US plan is not part of the current roadmap.
The lightweight coordinate-marker approach met the operational goal without adding
GIS geometry processing to the mobile platform.

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

## Transmit Safety Boundary

Rolling Thunder v4.3.0 includes a narrowly scoped native FT8 transmit path.
Transmission is allowed only after FT8 is explicitly enabled, the operator
selects one currently eligible CQ station, and the FT-891 passes fail-closed
radio-preparation and timing checks. Each authorization covers one bounded QSO;
Rolling Thunder never automatically selects or calls the next station.

Voice, AI, remote APIs, and unrelated automated processes do not independently
key the radio. General-purpose PTT/MOX/CW/tuner authority remains outside the
normal application boundary.
