# Rolling Thunder v4.1.0 Architecture Specification

**Product Version:** 4.1.0  
**Document Version:** 4.1.0  
**Status:** Approved Architecture Baseline through Platform Services and Ring 1, aligned through checkpoint 8 shared POTA/DX acceptance  
**Milestone:** M1 — Mobile Logging MVP  
**Target:** Functional end-to-end MVP by Sunday morning  
**Build Numbering:** Independent from product and document versioning

---

# 1. Purpose of This Document

This document is the single source of truth for the Rolling Thunder v4 project.

It consolidates all prior design documents, addenda, architectural discussions, and Ring 1 decisions into one authoritative specification. Nothing from earlier specifications has been intentionally removed unless this document explicitly supersedes it.

This document serves as:

- The architecture specification
- The product design baseline
- The implementation guide for Codex
- The source of truth for ChatGPT-assisted design work
- The current sprint definition
- The design decision log
- The future contributor reference
- The acceptance-test baseline

Code must follow this document. When code and this document disagree, the disagreement must be resolved explicitly rather than silently.

---

# 2. Revision History

## 4.1.0 — Comprehensive Architecture Baseline

This revision replaces the earlier fragmented specification and addendum documents with one complete architecture specification.

### Added or significantly expanded

- Comprehensive Platform Services architecture
- Ring 1 service definitions
- Pending-callsign logging workflow
- Voice Input as a required MVP capability
- Station State Service
- FT-891 radio-control requirements
- ATAS-120 operator-warning behavior
- Explicit prohibition against PTT and unattended transmit control
- Basic dashboard and hardware-control model
- MVP milestone scope
- Definition of Done
- End-to-end acceptance tests
- Data ownership and service boundaries
- Failure and graceful-degradation behavior
- Event and state-flow guidance
- Checkpoint-8 shared POTA/DX two-press receive-tuning contract
- Final FT-891 best-effort band-context and manual band/ATAS handoff decision
- Forge private-network trust-boundary decision
- Installed hardware and offline-continuity acceptance evidence

### Preserved from earlier specifications

- Product vision
- Guiding principles
- Home Station Platform terminology
- Overall architecture
- Functional rings
- Basic user-interface layout
- Data-access rules
- Security requirements
- Versioning model
- Documentation philosophy
- Future rings
- Open questions
- Decision-log intent

## 4.0.1 — Platform Services Architecture Review

- Renamed Core Services to Platform Services.
- Added Configuration Service.
- Added Local Data Service.
- Added Status & Notification Service.
- Adopted an in-process asynchronous Event Bus.
- Defined GPS stationary behavior.
- Defined configuration-driven ESP32 input mappings.
- Clarified that feature-specific business logic must not reside in Platform Services.

## 4.0.0 — Initial Consolidated Design

- Defined the initial product vision.
- Defined local-first and graceful-degradation principles.
- Defined the Home Station Platform role.
- Defined the initial functional-ring model.
- Defined the persistent dashboard concept.
- Defined initial security, MVP, versioning, and documentation principles.

---

# 3. Product Vision

Rolling Thunder is a mobile amateur-radio operating console designed for use while traveling.

Its purpose is not to be a collection of interesting technologies. Every feature must help the operator safely and efficiently:

- Discover stations
- Tune the radio
- Capture callsigns
- Attempt contacts
- Log successful contacts
- Maintain situational awareness

The operator should spend time operating the radio, not operating the software.

Rolling Thunder must support the actual mobile operating style of its primary operator:

1. Listen for a station.
2. Capture the callsign.
3. Attempt to complete the QSO.
4. Commit the contact only after success.
5. Discard the pending callsign if the contact is not completed.

The product must remain useful when disconnected from the internet or the Home Station Platform.

---

# 4. Guiding Principles

1. **Everything serves logging.** Logging is the heart of the product.
2. **Driver safety takes precedence over every feature.**
3. **Local first.** The Raspberry Pi must remain operational without network connectivity.
4. **Graceful degradation.** Losing a subsystem removes related features rather than crashing the application.
5. **Muscle memory over menus.** Dedicated physical controls are preferred over page cycling.
6. **One dashboard.** The major information areas remain visible in a persistent layout.
7. **One button equals one action.**
8. **The UI never waits on the network.**
9. **Services own complexity.** The UI asks for capabilities and state, not raw data sources.
10. **The Home Station Platform enhances operation but is never required for local logging.**
11. **Security is designed in, not added later.**
12. **Architecture before code.**
13. **Every new feature must reduce operator workload or increase situational awareness.**
14. **Platform Services remain few, stable, and free of feature-specific business logic.**
15. **Higher rings consume lower-level services; they do not bypass them.**
16. **Design decisions are documented with their reasons.**
17. **Nothing is written to the log until the operator explicitly commits the QSO.**
18. **No software component may initiate transmission.**
19. **Voice is an input mechanism, not a radio-control authority.**
20. **The system must fail visibly and safely.**
21. **The driver always has priority over the software.**

---

# 5. Terminology

## 5.1 Home Station Platform

The Home Station Platform is a role, not a specific computer.

The current implementation may run on the machine named Forge, but Rolling Thunder must not depend on that hostname or on a particular physical server.

The Home Station Platform may provide:

- QSO synchronization
- Wavelog integration
- Historical operating data
- Callsign history
- POTA and DX aggregation
- Intelligence and advisory services
- API aggregation
- Heavy processing
- Metrics and monitoring

The Pi must continue local logging if the Home Station Platform is unavailable.

## 5.2 Platform Services

Platform Services are local infrastructure capabilities required by feature rings.

They are not user-facing feature modules.

## 5.3 Functional Rings

Functional Rings are groups of user-facing capabilities arranged by dependency and importance.

- Platform Services provide the foundation.
- Ring 1 provides essential mobile operation.
- Ring 2 helps find contacts.
- Ring 3 provides situational awareness.
- Ring 4 provides intelligence.

## 5.4 Pending Callsign

A pending callsign is a recognized or selected callsign held temporarily while the operator attempts a QSO.

A pending callsign is not a logged contact.

## 5.5 Commit

Commit is an explicit physical-button action that records a successful QSO in the local database.

## 5.6 Discard

Discard is an explicit physical-button action that clears the pending callsign without writing a QSO.

## 5.7 Station State

Station State is the current unified operational picture assembled from radio, GPS, voice, logging, connectivity, and input services.

It is live state, not historical storage.

---

# 6. High-Level Architecture

```text
                    External Services
        POTA • DX • Weather • Space Weather • APIs
                           |
                           v
                  Home Station Platform
          Sync • Wavelog • History • Intelligence
                           |
                    Secure VPN / HTTPS
                           |
                           v
                    Raspberry Pi 4
+--------------------------------------------------------------+
| Basic Persistent UI                                          |
|--------------------------------------------------------------|
| Platform Services                                            |
| Configuration • Event Bus • Status • Connectivity            |
| Local Data • Logging • GPS • Device Input                    |
|--------------------------------------------------------------|
| Ring 1                                                       |
| Radio Control • Station State • Voice Input                  |
| Log Synchronization Interface                                |
|--------------------------------------------------------------|
| Local SQLite • CAT • GPS • Bluetooth • Audio                 |
+--------------------------------------------------------------+
                           |
          +----------------+----------------+
          |                |                |
          v                v                v
      Yaesu FT-891       GPS Receiver      ESP32 Controls
                                           Buttons • LEDs
                                           Rotary Encoder
```

---

# 7. Architectural Layers

```text
User Interface
      |
      v
Application and Feature Services
      |
      v
Platform Services
      |
      v
Hardware and Local Storage
      |
      v
Home Station Platform and External Services
```

The UI must not communicate directly with hardware, SQLite, remote APIs, or external services.

---

# 8. Platform Services

Platform Services run locally on the Raspberry Pi and provide common capabilities to all functional rings.

```text
Platform Services
------------------------------------------------
Configuration Service
Event Bus
Status & Notification Service
Backend Connectivity Manager
Local Data Service
Logging Service
GPS Service
Device Input Service
```

---

## 8.1 Configuration Service

### Purpose

Provide a single authoritative source for application configuration.

### Responsibilities

- Application paths
- CAT serial device and baud rate
- GPS device
- Microphone device
- Bluetooth device identity
- ESP32 button mappings
- LED mappings
- Rotary-encoder mappings
- Home Station Platform endpoint
- Certificate and authentication settings
- Retry intervals
- GPS stationary thresholds
- Feature flags
- Logging defaults
- UI preferences
- Local database path

### Rules

- No other service reads configuration files directly.
- Services request validated configuration from the Configuration Service.
- Invalid configuration must produce a visible status message.
- Secrets must not be logged.
- Configuration changes requiring restart must be identified clearly.

---

## 8.2 Event Bus

### Purpose

Provide low-coupling, in-process communication among services.

### Technology Direction

Use an asynchronous in-process event bus, likely based on Python `asyncio`.

### Reasons

- Expected event traffic is low.
- Deployment remains simple.
- No external broker is required.
- Services remain loosely coupled.
- The architecture can evolve later if requirements justify an external broker.

### Event Priorities

1. Operator input
2. Logging actions
3. Radio state
4. GPS state
5. Connectivity state
6. Feature refreshes
7. Metrics and diagnostics

### Example Events

```text
BUTTON_PRESSED
ENCODER_TURNED
VOICE_LISTENING_STARTED
VOICE_CALLSIGN_RECOGNIZED
PENDING_CALLSIGN_CHANGED
QSO_COMMIT_REQUESTED
QSO_COMMITTED
QSO_DISCARDED
RADIO_CONNECTED
RADIO_DISCONNECTED
RADIO_STATE_CHANGED
BAND_CHANGED
ATAS_RETUNE_REQUIRED
GPS_FIX_CHANGED
GPS_POSITION_CHANGED
STATIONARY_STATE_CHANGED
BACKEND_AVAILABLE
BACKEND_UNAVAILABLE
STATION_STATE_CHANGED
STATUS_MESSAGE_PUBLISHED
```

### Rules

- Events describe facts or requests.
- Services must not use the UI as an event relay.
- Slow handlers must not block operator-input processing.
- Event failures must be isolated and logged.

---

## 8.3 Status & Notification Service

### Purpose

Own all user-visible operational notifications.

### Responsibilities

- Bottom scrolling ticker
- Temporary toast notifications
- Service-health indicators
- Logging confirmations
- Radio connection alerts
- GPS alerts
- Backend connectivity alerts
- Pending synchronization count
- Manual band/ATAS-120 warnings

### Rules

- Other services publish notifications.
- Other services do not write directly to the ticker or UI.
- Safety-critical persistent warnings must remain visible until acknowledged or resolved.
- Timed operational reminders, including the checkpoint-8 cross-band band/ATAS handoff, may expire automatically when explicitly designed that way.
- Routine confirmations may expire automatically.
- Notifications must be concise enough to read while driving.

### Example Messages

```text
RADIO CONNECTED
RADIO UNAVAILABLE — LOGGING DISABLED
GPS FIX ACQUIRED
GPS FIX LOST
CALLSIGN READY
QSO COMMITTED
PENDING CALLSIGN CLEARED
HOME STATION PLATFORM UNAVAILABLE
3 QSOS WAITING TO SYNC
SET BAND TO 20 METERS — TUNE ATAS-120
```

---

## 8.4 Backend Connectivity Manager

### Purpose

Maintain the current availability state of the Home Station Platform.

### Behavior

- Assume unknown or tentatively available at startup.
- The first failed communication marks the backend unavailable.
- Publish the availability change.
- Begin adaptive health checks.
- The first successful communication marks the backend available.
- Publish restoration immediately.

### Rules

- No other service owns backend retry logic.
- Local logging must continue while the backend is unavailable.
- The UI must never block waiting for backend recovery.
- Reconnection must not create duplicate QSO submissions.

---

## 8.5 Local Data Service

### Purpose

Own all access to local persistent storage.

### Initial Storage

SQLite.

### Responsibilities

- QSO records
- Pending synchronization metadata
- Unique IDs
- Local settings that belong in storage
- Future POTA cache
- Future DX cache
- Callsign history cache
- Future map or repeater metadata
- Schema migration
- Transaction integrity

### Rules

- No feature or UI code accesses SQLite directly.
- All writes are transactional.
- Local QSO storage is authoritative while mobile.
- A successful local database write completes the local logging action.
- Database errors must visibly disable Commit.
- Schema changes require documented migrations.

---

## 8.6 Logging Service

### Purpose

Manage the pending-callsign workflow and write successful QSOs locally.

### Core Philosophy

The mobile logger is not a conventional logbook editor.

The operator does not edit reports, timestamps, frequency, mode, or other details while driving.

The logger maintains one pending callsign at a time.

### State Model

```text
IDLE
  |
  | Voice button
  v
LISTENING
  |
  | Callsign recognized
  v
CALLSIGN_PENDING
  |                    |
  | Commit             | Discard
  v                    v
COMMITTING            IDLE
  |
  | Successful write
  v
IDLE
```

### Pending Callsign Workflow

1. The operator hears a station.
2. The operator presses the Voice button.
3. The operator speaks the callsign.
4. Voice Input returns a normalized candidate.
5. The callsign is displayed as pending.
6. The operator attempts the contact.
7. If successful, the operator presses Commit.
8. If unsuccessful, the operator presses Discard.
9. No record is written before Commit.

### Commit Captures

At the moment Commit is pressed:

- Pending callsign
- Current frequency
- Current band
- Current mode
- GPS UTC time
- System-clock time if GPS time is unavailable
- GPS latitude and longitude if available
- Mobile/operator Maidenhead locator as `my_grid` if a current GPS fix exists
- Contacted station or contacted park Maidenhead locator as `grid` if available
- Contacted-grid source (`pota_park` or `qrz`) when `grid` is populated
- Unique contacted POTA reference and `POTA <reference>` note when matched
- Active operating context if applicable
- Unique immutable QSO ID
- Local synchronization state

### Contact Location Semantics

`my_grid` and `grid` are separate facts:

- `my_grid` follows `MY_GRIDSQUARE` semantics and describes the mobile station.
- `grid` follows `GRIDSQUARE` semantics and describes the contacted station or
  contacted park.
- The current vehicle GPS grid must never be written into `grid`.
- `pota_reference` follows `POTA_REF` semantics for the uniquely matched
  contacted park.

POTA matching is permitted only in the active POTA context and requires an
exact normalized activator callsign, frequency within plus or minus 250 Hz,
compatible mode, and exactly one distinct park. Park coordinates take
precedence and are converted locally to a six-character locator.

When no contacted grid is available and QRZ credentials exist, the QSO is
written locally first and a bounded background lookup may supply `grid`.
QRZ failure, timeout, invalid data, missing credentials, or no result must not
prevent or undo the local QSO.

### Timestamp Rule

The official QSO time is the Commit time.

The initial voice-capture time may be retained for diagnostics but is not the official QSO time.

### Discard Behavior

Discard:

- Clears the pending callsign
- Clears pending-QSO state
- Writes no QSO
- Requires no confirmation dialog
- Publishes a brief status message

### Callsign Replacement

If a callsign is already pending:

- Pressing Voice starts a replacement attempt.
- The existing callsign remains until a new recognition succeeds.
- Successful recognition replaces the previous candidate.
- Failed recognition leaves the existing candidate unchanged.

### Logging Availability

Commit is enabled only when:

- A pending callsign exists.
- Radio Control reports valid frequency, band, and mode.
- Local Data Service is writable.
- GPS time or system time is available.

Voice capture may still be possible while Radio Control is unavailable, but Commit remains disabled until valid radio state returns.

### No RST During Mobile Operation

RST reports are not entered while driving.

Detailed corrections and log maintenance belong in Wavelog or a future non-driving maintenance interface.

---

## 8.7 GPS Service

### Purpose

Provide current location, movement state, grid, and trusted UTC time.

### Responsibilities

- Latitude
- Longitude
- Speed
- Heading
- Maidenhead grid
- GPS UTC
- Fix quality
- Last update
- Stationary/moving state

### Stationary Behavior

GPS remains active while stopped.

Movement-driven updates are suppressed below a configurable threshold using hysteresis.

Example defaults:

- Enter stationary state below approximately 1.5 mph.
- Resume movement updates above approximately 2.5 mph.

### Reasons

- Preserve accurate UTC.
- Prevent map jitter.
- Prevent repeated repeater or location recalculations.
- Reduce unnecessary UI redraws and processing.

### Failure Behavior

- Loss of position does not disable logging.
- Loss of GPS time causes system-clock fallback.
- The UI and Station State must identify degraded GPS status.

---

## 8.8 Device Input Service

### Purpose

Abstract physical ESP32 controls from application functions.

### Hardware Model

The ESP32 reports numeric events.

Examples:

```text
BUTTON_1_DOWN
BUTTON_1_UP
BUTTON_7_DOWN
ENCODER_LEFT
ENCODER_RIGHT
ENCODER_PRESS
```

The Pi configuration maps those numbers to functions.

### Responsibilities

- Bluetooth connection
- Button events
- Rotary-encoder events
- LED commands
- Reconnection
- Device-health state

### Bidirectional Bluetooth

The ESP32 sends input events to the Pi.

The Pi sends LED-state commands to the ESP32.

### Reasons

- Button functions can be remapped without reflashing.
- LED behavior remains controlled by application state.
- Hardware firmware remains simple.
- Future control panels can be supported through configuration.

---

# 9. Ring 1 — Essential Mobile Operation

Ring 1 contains the minimum user-facing capabilities required for a functional mobile logger.

```text
Ring 1
------------------------------------------------
Radio Control Service
Station State Service
Voice Input Service
Log Synchronization Interface
```

---

## 9.1 Radio Control Service

### Initial Supported Radio

Yaesu FT-891.

### Transport

CAT serial control.

### Required Read Capabilities

- Connection state
- Frequency
- Band
- Mode
- Last successful update
- State validity

### Required Write Capabilities

- Prepare/set band context within the radio adapter's approved capability
- Set exact receive frequency
- Set receive mode
- Refresh state
- Reconnect after failure

### Explicitly Forbidden Capabilities

- PTT
- Transmit initiation
- Voice-triggered radio control
- Remote transmitter activation
- Power control
- Unattended operation
- Antenna control that could imply the station is safe to transmit

### FT-891 Cross-Band Receive Requirement

The FT-891 must be handled conservatively when a requested receive frequency is
on a different amateur band.

Physical checkpoint-8 testing established that CAT regular-memory recall can
move VFO-A to a programmed band memory, but the radio's operator-visible band
context is not reliable enough to treat that recall as authoritative automatic
band selection.

The approved logical sequence is therefore:

```text
1. Determine the target band from the requested frequency.
2. Compare target band with the starting radio frequency.
3. If crossing bands:
   a. Perform best-effort recall of the operator-programmed regular memory for
      the target band.
   b. Verify the selected regular-memory number.
   c. Copy that memory to VFO-A.
   d. Verify the recalled frequency belongs to the target amateur band.
   e. Set and verify the exact target frequency.
   f. Set and verify the required receive mode.
   g. Publish the explicit operator handoff:
      SET BAND TO <BAND> METERS — TUNE ATAS-120
4. If remaining on the same band:
   a. Set and verify the exact frequency.
   b. Set and verify mode if needed.
   c. Publish no band/ATAS warning.
```

### Verified CAT Decision

The checkpoint-8 shared-spot path uses these regular-memory/VFO operations:

- `MCxxx;` selects regular memory `xxx`.
- `MC;` reads the selected regular-memory number.
- `MA;` copies the selected regular memory to VFO-A.
- `FA#########;` sets the exact VFO-A frequency.
- `MD0x;` sets the main receive mode.
- `FA;` and `MD0;` provide exact receive read-back.

The operator-programmed memory mapping is:

```text
001 160 m
002 80 m
003 40 m
004 30 m
005 20 m
006 17 m
007 15 m
008 12 m
009 10 m
010 6 m
```

Rolling Thunder does not write these memories. `MW` and `MT` are outside the
approved path.

The existing `BSxx` encoder is not the authoritative checkpoint-8 band-state
mechanism. Future investigation of a more authoritative FT-891 CAT/front-panel
band-context mechanism is tracked in issue #149.

### ATAS-120 Constraint

Rolling Thunder cannot tune or verify the ATAS-120 and cannot reliably prove
that the FT-891's operator-visible band state changed solely from the tested CAT
band-context mechanisms.

After a successful cross-band shared receive tune, the system must notify the
operator:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

The operator must manually set or confirm the target band and tune the ATAS-120
before transmitting.

The system must not imply that the band or antenna is safe merely because exact
receive frequency and mode read-back succeeded.

### Failure Behavior

If Radio Control cannot provide valid frequency, band, and mode:

- Commit is disabled.
- The pending callsign may remain.
- The UI displays that logging is unavailable.
- The system attempts reconnection without blocking the UI.
- No incomplete QSO is silently written.

---

## 9.2 Station State Service

### Purpose

Provide one unified, current operational state to the UI and dependent services.

### Architectural Position

Station State is separate from Radio Control.

Radio Control owns CAT communication.

Station State owns the combined application read-model.

### Input Side

Station State consumes information from:

- Radio Control
- GPS Service
- Voice Input Service
- Logging Service
- Device Input Service
- Backend Connectivity Manager
- UI context selection
- Focus controller

### Output Side

Station State provides data to:

- User Interface
- Logging Service
- Status & Notification Service
- LED controller
- Future POTA services
- Future DX services
- Future repeater services
- Future mapping services
- Future intelligence services

### Example State Model

```text
StationState
├── radio
│   ├── connected
│   ├── frequency_hz
│   ├── band
│   ├── mode
│   ├── valid
│   └── last_update
├── gps
│   ├── fix
│   ├── stationary
│   ├── latitude
│   ├── longitude
│   ├── grid
│   ├── utc_time
│   └── last_update
├── voice
│   ├── available
│   ├── listening
│   ├── pending_callsign
│   ├── raw_transcript
│   └── confidence
├── logging
│   ├── enabled
│   ├── pending_qso
│   ├── unsynced_count
│   └── last_result
├── user_interface
│   ├── selected_context
│   ├── focused_panel
│   └── active_selection
└── connectivity
    ├── home_station_available
    └── internet_available
```

### Rules

- Station State is not a database.
- The UI should subscribe to state changes or request a current snapshot.
- The UI must not poll several underlying services independently.
- State changes must be published through the Event Bus.
- State must identify validity and staleness.

---

## 9.3 Voice Input Service

### Purpose

Convert an operator-triggered spoken callsign into one pending callsign candidate.

Voice Input is required for the MVP because ordinary non-POTA and non-DX contacts require callsign entry.

### Responsibilities

- Open and manage the configured microphone.
- Begin listening only after an explicit button press.
- Capture a short voice sample.
- Perform speech recognition.
- Normalize amateur-radio callsigns.
- Return a candidate callsign.
- Return recognition confidence.
- Preserve the raw transcript for diagnostics.
- Stop listening automatically.
- Support replacement of an existing pending callsign.

### Example

```text
"Kilo India Five Victor November Bravo"
        |
        v
KI5VNB
```

### Callsign Normalization

The service should understand or normalize:

- NATO or common phonetic words
- Individual spoken letters
- Spoken digits
- Common speech-recognition substitutions
- Standard amateur-radio prefix and suffix patterns
- Future portable or mobile suffix handling

### Safety Boundary

Voice Input may supply data to the logger.

Voice Input may not:

- Change frequency
- Change band
- Change mode
- Tune an antenna
- Trigger PTT
- Initiate transmission
- Turn the radio on or off
- Execute unattended radio commands

### Architectural Requirement

Speech-recognition implementation is hidden behind the Voice Input Service interface.

The logger must not care whether recognition is:

- Local on the Pi
- Performed by the Home Station Platform
- Switched between implementations

However, the intended architecture is local-first and should not require internet connectivity for basic logging.

---

## 9.4 Log Synchronization Interface

### MVP Status

Architectural placeholder only.

A full synchronization worker is not required for the first M1 demonstration.

### MVP Requirements

- Every committed QSO receives a unique immutable ID.
- Every committed QSO includes synchronization metadata.
- New QSOs begin in `LOCAL_ONLY`.
- The UI can display the unsynchronized count.
- Logging remains fully decoupled from network synchronization.

### Planned Post-MVP States

```text
LOCAL_ONLY
QUEUED
SENDING
ACKNOWLEDGED
SYNC_ERROR
```

### Future Flow

```text
1. QSO is committed locally.
2. QSO enters the synchronization queue.
3. Pi sends it to the Home Station Platform.
4. Platform acknowledges durable receipt.
5. Pi marks it acknowledged.
6. Platform independently imports it into Wavelog.
7. Pi never waits for Wavelog.
```

### Duplicate Prevention

The immutable QSO ID must be used to make retries idempotent.

---

# 10. Functional Rings Beyond Ring 1

These rings remain part of the architecture. Details may evolve as each ring is implemented, but they must continue to consume lower-level services rather than bypass them.

## 10.1 Ring 2 — Finding Contacts

Capabilities include or may include:

- POTA spots
- DX Cluster
- Callsign lookup and history
- Favorites
- GPS-aware repeater discovery

Checkpoint 8 implements the first shared POTA/DX Ring-2 slice:

- provider-neutral immutable POTA/DX snapshots
- Forge-side POTA and DXSpider aggregation
- durable Pi retained-cache behavior
- provider-specific band/mode filters
- stable identity-based selection
- exact two-press receive-tuning staging
- `ReceiveTuningService` as the sole radio authority
- first press stages only and performs no CAT
- second press tunes only the exact same still-valid target
- selection/filter/context/Back/radio invalidation clears staging
- cross-band success presents `SET BAND TO <BAND> METERS — TUNE ATAS-120`
- no PTT, MOX, keying, tuner, power, or transmit authority

Ring 2 must consume Platform Services and Station State rather than directly accessing hardware or storage.

## 10.2 Ring 3 — Situational Awareness

Planned capabilities:

- Offline Ohio map
- GPS tracking
- Parks
- NEXRAD weather
- Basic space weather
- Nearby repeaters
- Future SDR activity monitor

## 10.3 Ring 4 — Intelligence

Planned capabilities:

- AI advice card
- Best-contact suggestions
- Propagation recommendations
- Historical operating intelligence
- Context-aware advisories

Ring 4 may recommend actions but may not directly control transmission or PTT.

---

# 11. Basic User Interface

The first implementation requires a functional dashboard, not visual polish.

## 11.1 Persistent Layout

```text
+--------------------------------------------------------------+
| Logger Panel                |                                |
|-----------------------------|                                |
| Pending Callsign            |                                |
| Frequency                   |                                |
| Band                        |        Situational Area        |
| Mode                        |       Map / Future Cards       |
| Radio State                 |                                |
| Commit / Discard State      |                                |
|-----------------------------|                                |
| Context Panel               |                                |
| POTA / DX / Repeater / etc. |                                |
|--------------------------------------------------------------|
| Status Ticker                                                |
+--------------------------------------------------------------+
```

## 11.2 Top Left — Logger Panel

Always visible.

Displays:

- Pending callsign
- Voice/listening state
- Radio connection state
- Frequency
- Band
- Mode
- Commit availability
- Last logging result

## 11.3 Bottom Left — Context Panel

Dedicated top-row buttons select contexts directly.

Examples:

- POTA
- DX
- Repeaters
- AI
- Settings
- Additional future context

No next-page cycling is required.

## 11.4 Right Side — Situational Area

Normally displays a map.

Future overlays or cards may include:

- Park information
- Callsign history
- AI advice
- Weather
- Repeater details

The map should remain visible whenever practical.

## 11.5 Bottom Ticker

Persistent and owned by the Status & Notification Service.

## 11.6 Focus Model

Only limited focus states should exist.

Initial concept:

- LOGGER
- CONTEXT

The map does not receive focus during normal driving.

When a callsign becomes pending, focus may automatically move to the logger.

After Commit or Discard, focus returns to the previous context.

---

# 12. Physical Controls

## 12.1 Proposed Layout

Top row:

- Six dedicated context buttons

Lower controls:

- Rotary encoder with push
- Focus button
- Voice button
- Commit button
- Discard button
- One context-sensitive Action button if hardware permits

## 12.2 Required Logging Buttons

- **Voice** — capture or replace pending callsign
- **Commit** — record a successful QSO
- **Discard** — clear an unsuccessful pending callsign

These actions must be available through physical controls.

## 12.3 LED Behavior

LEDs may indicate:

- Selected context
- Current focus
- Voice listening
- Pending callsign
- Commit availability
- Warning state
- Radio disconnected
- ATAS retune required

Exact colors and patterns remain a later UI/hardware specification item.

---

# 13. Data Access Rules

The UI must never directly access:

- SQLite
- CAT serial ports
- GPS devices
- Bluetooth devices
- Home Station Platform APIs
- External APIs

Instead:

```text
UI
 |
 v
Service Interface
 |
 v
Local Data / Hardware / Remote Provider
```

A service chooses the appropriate source:

- Local database
- Cache
- Home Station Platform
- External service
- Hardware driver

The UI remains unaware of the underlying provider.

Example future callsign-history behavior:

```text
If backend available:
    Query Home Station Platform.
    Merge unsynchronized local QSOs.
    Return unified history.

If backend unavailable:
    Return local history only.
```

---

# 14. Security Architecture

## 14.1 Principles

- Least privilege
- Encrypted transport or private secure tunneling where appropriate
- Authentication where the trust boundary requires it
- Network segmentation
- Input validation
- No remote-originated PTT
- No unattended transmission
- No AI-originated transmission
- No voice-originated transmission
- Explicit separation between read/control interfaces and transmit control

## 14.2 Radio Safety Boundary

Rolling Thunder may:

- Read radio state
- Prepare best-effort band context within the approved adapter
- Set receive frequency
- Set receive mode

Rolling Thunder may not:

- Trigger PTT
- Initiate transmission
- Send voice-generated radio commands
- Expose a remote PTT API
- Allow an AI system to transmit
- Permit unattended operation
- Claim the FT-891 operator-visible band state changed when that cannot be verified
- Claim the ATAS-120 is tuned without operator action

Hardware PTT remains under direct operator control.

## 14.3 Network Segmentation

Radio LAN remains isolated from Server LAN except through explicitly approved routed paths.

Checkpoint-8 Forge spot access is intentionally supported only on the trusted private RadioLAN/CarLAN-over-WireGuard path. The Forge listener binds to its private RadioLAN address rather than all interfaces.

No public TCP 8766 port forward or UPnP exposure is part of the supported design.

## 14.4 Home Station Platform Security

The security requirement is proportional to the service boundary:

- use a secure VPN/private routed path and/or HTTPS as appropriate
- validate API requests and responses
- keep service scope minimal
- expose no inbound command path for PTT
- make synchronization idempotent
- keep logs audit-friendly without exposing secrets
- store credentials outside repository YAML

For checkpoint 8 specifically, the Forge POTA/DX read API has no application-layer TLS or authentication. This is an explicit accepted residual risk because the listener is confined to the private routed network and exposes only read-only health/spot data. Anyone who can reach the private listener can read those endpoints.

If Forge is ever exposed outside the trusted private network, TLS and authentication are required before that exposure is supported.

See `docs/FORGE_DEPLOYMENT.md` for the production trust boundary and rollback requirements.

---

# 15. Failure and Graceful-Degradation Matrix

| Failure | Required Behavior |
|---|---|
| Home Station Platform unavailable | Local logging continues |
| Internet unavailable | Local logging continues |
| GPS position unavailable | Log without position; use system time if necessary |
| GPS time unavailable | Use system clock |
| Radio disconnected | Commit disabled; pending callsign may remain; staged shared-spot action is invalidated |
| Voice unavailable | Ordinary manual voice-based logging unavailable |
| Local database unwritable | Commit disabled |
| ESP32 disconnected | UI remains visible; physical controls unavailable |
| Cross-band receive tune completed | Require operator to set/confirm band and tune ATAS-120 before transmit |
| Synchronization unavailable | Store QSO as `LOCAL_ONLY` |
| Forge unavailable | Retain last valid shared POTA/DX snapshot when present; local logging continues |
| UI overlay failure | Logger and status remain available |
| Individual event handler failure | Isolate failure; do not crash event bus |

---

# 16. Milestone M1 — Mobile Logging MVP

## 16.1 Goal

By Sunday morning, the system should provide an end-to-end mobile logging vertical slice.

The purpose is to prove the architecture through a complete real-world workflow, not to finish every planned Ring 1 enhancement.

## 16.2 Required End-to-End Workflow

```text
Start Raspberry Pi
        |
        v
Dashboard appears
        |
        v
FT-891 connects
        |
        v
GPS begins providing state
        |
        v
ESP32 controls connect
        |
        v
Operator presses Voice
        |
        v
Operator speaks callsign
        |
        v
Pending callsign appears
        |
        v
Operator attempts QSO
        |
        +---------------------+
        |                     |
        v                     v
     Commit                Discard
        |                     |
        v                     v
QSO stored locally      Pending state cleared
        |
        v
Status ticker confirms result
```

## 16.3 M1 Required Scope

### Platform Services

- Configuration Service
- Event Bus
- Status & Notification Service
- Backend Connectivity Manager skeleton
- Local Data Service
- Logging Service
- GPS Service
- Device Input Service

### Ring 1

- FT-891 Radio Control
- Station State
- Voice Input
- Log Synchronization data-model placeholder

### Basic UI

- Persistent logger panel
- Basic context area
- Situational placeholder or simple map area
- Status ticker
- Visible service health
- Pending callsign
- Commit and Discard state

## 16.4 M1 Intentionally Deferred

- Full Home Station Platform integration
- Wavelog import
- Active log synchronization worker
- POTA intelligence
- DX Cluster
- Callsign history
- AI
- Advanced weather
- Repeater discovery
- Full offline mapping
- SDR monitor
- UI polish
- Animations
- Final visual theme

---

# 17. Definition of Done

M1 is complete only when the complete workflow works on the intended Raspberry Pi hardware.

Code compilation alone is not sufficient.

## 17.1 Functional Definition

The system must:

- Boot into the dashboard.
- Load validated configuration.
- Initialize the Event Bus.
- Connect to or visibly fail to connect to the FT-891.
- Read valid frequency, band, and mode.
- Receive GPS state.
- Connect to the ESP32 control surface or visibly report failure.
- Start voice capture from a button press.
- Recognize and normalize a spoken callsign.
- Display one pending callsign.
- Allow the operator to attempt the QSO without automatically writing a log entry.
- Commit the QSO with a physical button.
- Discard the pending callsign with a physical button.
- Store committed QSOs transactionally in SQLite.
- Leave the database unchanged after Discard.
- Continue local logging without Home Station Platform connectivity.
- Disable Commit when radio state or local storage is invalid.
- Display the manual band/ATAS warning after successful cross-band shared receive tuning.
- Avoid all PTT or transmit control.

## 17.2 Quality Definition

- UI does not freeze during I/O.
- Operator-input events receive priority.
- No network dependency exists in the Commit path.
- Service failures produce visible status.
- Application logs contain enough diagnostic detail for troubleshooting.
- Secrets are not written to logs.
- The database survives application restart.
- A committed QSO is not duplicated by application restart.
- The pending callsign is never silently committed.

## 17.3 Documentation Definition

- Configuration instructions exist.
- FT-891 CAT setup is documented.
- GPS setup is documented.
- Microphone setup is documented.
- ESP32 pairing is documented.
- Database location and schema are documented.
- Known limitations are documented.
- Acceptance-test results are recorded.

---

# 18. M1 Acceptance Tests

## Acceptance Test 1 — Successful QSO Commit

1. Boot the Pi.
2. Confirm the dashboard appears.
3. Confirm the FT-891 connects.
4. Confirm valid frequency, band, and mode appear.
5. Press Voice.
6. Speak `KI5VNB` or its phonetic equivalent.
7. Confirm `KI5VNB` appears as the pending callsign.
8. Press Commit.
9. Confirm a success message appears.
10. Confirm SQLite contains exactly one new QSO with current radio state and timestamp.

**Pass condition:** One correct QSO is stored locally.

## Acceptance Test 2 — Discard

1. Capture a callsign.
2. Confirm it appears as pending.
3. Press Discard.
4. Confirm pending state clears.
5. Confirm the local database is unchanged.

**Pass condition:** No QSO is stored.

## Acceptance Test 3 — Radio Failure

1. Capture a pending callsign or stage a shared spot.
2. Disconnect, power off, or otherwise make CAT unavailable in a controlled parked test.
3. Confirm the UI displays radio unavailability.
4. Confirm Commit is disabled when required radio state is unavailable.
5. Confirm any staged shared-spot action is cleared.
6. Reconnect or power the radio back on.
7. Confirm valid state returns.
8. Confirm the old staged target is not resurrected or automatically executed.

**Pass condition:** No incomplete QSO or stale staged action is silently executed.

## Acceptance Test 4 — Cross-Band Receive Tune and Operator Handoff

1. Begin on one supported band.
2. Select a shared POTA or DX target on a different supported band.
3. Confirm the first activation stages only and changes nothing on the radio.
4. Activate the same still-valid target a second time.
5. Confirm best-effort band-context recall occurs before the exact target frequency.
6. Confirm final receive frequency and mode are correct.
7. Confirm the status message displays:

```text
SET BAND TO <BAND> METERS — TUNE ATAS-120
```

8. Confirm the Standard TX-capable FT-891 interface remains closed.
9. Confirm no PTT, MOX, keying, tuner, power, or transmit action occurs.

**Pass condition:** Exact receive frequency/mode are reached, the operator receives the explicit manual band/ATAS handoff, and no claim is made that CAT authoritatively changed the FT-891 band state.

## Acceptance Test 5 — Offline Operation

1. Disconnect the network or make Forge unavailable in a controlled test.
2. Confirm the UI indicates backend/shared-data degradation while retaining the last valid POTA/DX snapshot when available.
3. Capture a callsign or create an isolated test contact through the real local logging path.
4. Commit/write the local QSO.
5. Confirm the QSO is stored locally with synchronization pending/local-only semantics as applicable.
6. Confirm the UI remains responsive.
7. Confirm restored network/Forge access recovers without losing the local contact.

**Pass condition:** Logging completes without the network/Forge dependency and retained shared data remains usable when a prior valid snapshot exists.

## Acceptance Test 6 — GPS Degradation

1. Remove or block the GPS fix.
2. Confirm the UI indicates degraded GPS.
3. Capture and commit a QSO.
4. Confirm the system uses the system clock.
5. Confirm the QSO is stored without false position data.

**Pass condition:** Logging succeeds with documented degraded data.

## Acceptance Test 7 — Database Failure

1. Make the local database unwritable in a test environment.
2. Confirm Commit becomes disabled.
3. Confirm a clear status message appears.
4. Confirm no false success message is shown.

**Pass condition:** Failure is visible and no QSO is lost silently.

## Acceptance Test 8 — Voice Replacement

1. Capture a callsign.
2. Press Voice again.
3. Speak a different callsign.
4. Confirm the new candidate replaces the old one only after successful recognition.
5. Simulate failed recognition.
6. Confirm the existing pending callsign remains.

**Pass condition:** Replacement behavior is safe and predictable.

---

# 19. Versioning

## 19.1 Product Versions

Rolling Thunder uses Semantic Versioning:

```text
MAJOR.MINOR.PATCH
```

Examples:

- 4.0.0
- 4.1.0
- 4.1.1

### Meaning

- **MAJOR:** Incompatible architectural or product changes
- **MINOR:** New backward-compatible capability or major milestone
- **PATCH:** Backward-compatible correction or refinement

## 19.2 Document Versions

The design-document version normally tracks the product version when the document defines that product baseline.

Architecture-only edits that do not change the intended product may use a document revision suffix or patch version, but the document must clearly identify both values.

## 19.3 Build Numbers

Build numbers are independent and increment for every generated software build.

Example:

```text
Product Version: 4.1.0
Build: 127
```

Build numbers do not cause design-document revisions.

## 19.4 Source-Control Tags

When implementation begins, releases should be tagged consistently.

Recommended format:

```text
v4.1.0
v4.1.0-build.127
```

The exact source-control policy can be finalized when the repository is established.

---

# 20. Documentation Maintenance Rules

1. This file is the authoritative design document.
2. New revisions must begin with the previous complete version.
3. Nothing is removed silently.
4. Removed requirements must be identified in Revision History and the Decision Log.
5. New architectural decisions must include their rationale.
6. Open questions must not be presented as settled facts.
7. Codex implementation tasks must cite relevant sections.
8. Acceptance criteria must be updated when scope changes.
9. Ring 2–4 detail may evolve without rewriting stable Platform Services unless a genuine architecture change is required.
10. The specification should be reviewed after each major implementation milestone.

---

# 21. Decision Log

## D-001 — Local SQLite Is Authoritative While Mobile

**Decision:** A successful local write completes the mobile logging action.

**Reason:** Logging must not depend on internet or backend availability.

## D-002 — Platform Services Replace the Earlier Core Services Term

**Decision:** Use Platform Services for infrastructure capabilities.

**Reason:** It separates infrastructure from user-facing feature rings.

## D-003 — Use an In-Process Asynchronous Event Bus

**Decision:** Do not introduce MQTT, Redis, Kafka, or another external broker for the initial architecture.

**Reason:** Event volume is low and deployment simplicity is valuable.

## D-004 — Use a Pending-Callsign Workflow

**Decision:** Voice capture creates a candidate, not a QSO.

**Reason:** The operator normally captures a callsign before knowing whether the contact will be completed.

## D-005 — Require Explicit Commit or Discard

**Decision:** No recognized callsign is automatically logged.

**Reason:** The operator may fail to break a pileup or complete the contact.

## D-006 — Voice Input Is Required for the MVP

**Decision:** Voice Input belongs in Ring 1.

**Reason:** Ordinary non-POTA and non-DX contacts require a practical means to enter callsigns while driving.

## D-007 — Voice Has No Radio-Control Authority

**Decision:** Voice may enter logger data but cannot tune, transmit, control PTT, or operate the antenna.

**Reason:** Prevent unattended or unintended radio operation.

## D-008 — Radio Control and Station State Are Separate

**Decision:** Radio Control owns CAT; Station State owns the unified operational read-model.

**Reason:** This keeps hardware communication separate from application-state consumption.

## D-009 — No PTT or Transmit Control

**Decision:** Rolling Thunder will not expose PTT, automated transmit, AI transmit, or voice transmit control.

**Reason:** Safety, security, operator control, and avoidance of unattended operation.

## D-010 — Cross-Band Receive Tuning Requires Manual Band / ATAS Handoff

**Decision:** After a successful cross-band receive tune, Rolling Thunder displays `SET BAND TO <BAND> METERS — TUNE ATAS-120`.

**Reason:** Exact receive frequency and mode can be verified, but the tested FT-891 CAT mechanisms do not provide sufficiently authoritative operator-visible band-state behavior, and software cannot reliably tune or verify the ATAS-120. The operator therefore retains final responsibility for band confirmation and antenna tuning.

## D-011 — Log Synchronization Is Deferred but Designed In

**Decision:** Include IDs and synchronization state in the MVP schema, but defer the active synchronization worker.

**Reason:** Avoid coupling and schema rework while preserving a small M1 scope.

## D-012 — GPS Remains Active While Stationary

**Decision:** Suppress movement updates rather than stopping GPS processing.

**Reason:** Preserve UTC and fix quality while preventing jitter and unnecessary recalculation.

## D-013 — ESP32 Reports Numeric Events

**Decision:** Hardware events are mapped to functions on the Pi.

**Reason:** Remapping should not require firmware changes.

## D-014 — M1 Is an End-to-End Vertical Slice

**Decision:** The Sunday target is a complete usable logging workflow rather than every planned Ring 1 enhancement.

**Reason:** This validates architecture and operator experience early.

## D-015 — Forge Checkpoint-8 API Uses a Private-Network Trust Boundary

**Decision:** The checkpoint-8 Forge spot API may operate without application-layer TLS/authentication only while confined to the approved private RadioLAN/CarLAN-over-WireGuard path and private bind address.

**Reason:** The service is read-only, exposes no credentials or radio-control commands, and is not publicly reachable. Application-layer TLS/authentication becomes mandatory before any supported exposure outside that trust boundary.

## D-016 — FT-891 Memory Recall Is Best-Effort Band Context Only

**Decision:** Regular-memory selection and memory-to-VFO-A recall may be used before cross-band receive tuning, but successful recall is not treated as authoritative automatic band selection.

**Reason:** Physical testing proved `MC`/`MA` recall changes VFO-A frequency/mode, but the FT-891 operator-visible band context remains insufficiently reliable. Future investigation is parked in issue #149.

---

# 22. Open Questions

## Required Before or During M1

- Initial local speech-recognition engine
- Exact microphone and ALSA/PipeWire device configuration
- Exact GPS hardware and device path
- ESP32 Bluetooth protocol framing
- SQLite schema details
- UI toolkit selection
- Process model: one application process versus supervised service processes
- Logging and diagnostics location
- Systemd startup and recovery behavior

## Resolved or Parked During Later Implementation

- FT-891 shared POTA/DX receive-only hardware acceptance: completed for checkpoint 8
- Authoritative automatic FT-891 band-context behavior: parked in issue #149 pending future firmware/CAT investigation
- Forge checkpoint-8 trust boundary: private RadioLAN/CarLAN-over-WireGuard with no public exposure; TLS/auth required if that boundary expands

## Can Be Deferred

- Full offline map implementation
- Ring 2 cache expiration
- Plugin architecture
- SDR roadmap
- AI roadmap
- Radio abstraction beyond the FT-891
- Final LED patterns
- Final visual theme
- Home Station Platform synchronization protocol
- Wavelog import and reconciliation
- Full telemetry and Grafana integration

---

# 23. Immediate Implementation Sequence

Recommended M1 implementation order:

1. Establish repository and project skeleton.
2. Add configuration loading and validation.
3. Add structured logging and diagnostics.
4. Implement Event Bus.
5. Implement Station State model.
6. Implement Local Data Service and QSO schema.
7. Implement Logging Service state machine.
8. Implement FT-891 read-only CAT state.
9. Implement GPS Service.
10. Implement basic UI shell.
11. Implement Voice Input.
12. Implement Device Input and button mappings.
13. Connect Commit and Discard end-to-end.
14. Add FT-891 receive-only write commands and guarded cross-band handling.
15. Add manual band/ATAS warning after cross-band receive tuning.
16. Add backend-unavailable state and `LOCAL_ONLY` metadata.
17. Run acceptance tests.
18. Document installation and known limitations.

---

# 24. Sunday Morning Demonstration

The milestone demonstration should show:

- Raspberry Pi boots directly into Rolling Thunder.
- FT-891 state appears.
- GPS status appears.
- ESP32 controls respond.
- Voice captures a callsign.
- The callsign remains pending during a simulated QSO attempt.
- Commit writes the QSO.
- Discard writes nothing.
- A cross-band receive tune produces an explicit manual `SET BAND ... — TUNE ATAS-120` warning.
- Disconnecting the network does not interrupt logging.
- Disconnecting the radio disables Commit without crashing.
- No path exists for PTT or unattended transmission.

A successful demonstration establishes that Platform Services and Ring 1 are sufficiently sound to support future rings.

---

# 25. Checkpoint-8 Physical Acceptance Record

The installed checkpoint-8 shared POTA/DX path has been accepted on `anvilmobile` with the real FT-891 and installed physical controls while parked.

Accepted evidence includes:

- POTA first press stages only and causes no radio change
- DX first press stages only and causes no radio change
- same-band POTA second press tunes as expected without a false band/ATAS warning
- same-band DX second press tunes the exact selected DX frequency without a false band/ATAS warning
- cross-band POTA receive frequency/mode tuning succeeds with the manual band/ATAS handoff
- cross-band DX receive frequency/mode tuning succeeds with the manual band/ATAS handoff
- selection change invalidates staging
- band-filter change invalidates staging
- mode-filter change invalidates staging
- Back cancels staging without tuning
- radio power loss invalidates staging
- reconnection does not resurrect or execute an old staged target
- Enhanced CAT remains the approved receive-control interface
- the Standard TX-capable FT-891 USB interface remains closed
- no PTT, MOX, keying, tuner, power, or transmit action occurs
- controlled Forge loss retains the last valid POTA/DX snapshot and keeps the UI responsive
- an isolated temporary SQLite contact can be created and read back while Forge is unavailable
- the production contact count remains unchanged during that isolated offline test
- Forge connectivity recovers after the controlled interruption
- temporary outage/logging artifacts are removed and the repository returns to a clean state

Automatic authoritative FT-891 band-state behavior is deliberately excluded from this acceptance claim and remains tracked in issue #149.

---

# 26. Future Architecture Review Point

After M1 and the implemented checkpoint slices, the next decision is whether to:

1. Begin the next Ring 2/3 implementation slice, or
2. Complete deeper Ring 2–4 architecture before adding more code.

The decision should be based on whether implementation reveals changes needed in Platform Services, Station State, the UI contract, the data model, or the operator-safety boundaries.

The higher rings should not be allowed to bypass the stable architecture established here.

---

# End of Specification