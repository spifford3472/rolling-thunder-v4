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

**M1 — Mobile Logging MVP**

The M1 goal is to demonstrate:

1. Raspberry Pi dashboard startup
2. FT-891 state acquisition
3. GPS state acquisition
4. Voice callsign capture
5. Pending callsign display
6. Physical Commit or Discard
7. Transactional local QSO storage
8. Continued logging without network connectivity

## Security Boundary

Rolling Thunder does not control PTT and does not initiate transmission.

Voice, AI, remote APIs, and automated processes may not key the radio.
