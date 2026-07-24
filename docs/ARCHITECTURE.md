# Rolling Thunder v4 Architecture

## Purpose

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system.
Its primary client runs on the Raspberry Pi 4 named `anvilmobile`.

The system is designed to support radio control, callsign entry, contact logging,
POTA activity, mapping, GPS position, station status, and later synchronization
with services hosted on Forge.

## Design Goals

- Remain useful without internet, WireGuard, or Forge.
- Keep hardware-specific details outside application and UI logic.
- Support mock hardware for development and automated testing.
- Avoid blocking serial, audio, GPS, or network work in the UI thread.
- Store unsynchronized contacts locally and upload them later.
- Keep configuration typed, centralized, and free of secrets.
- Make each subsystem independently testable.

## High-Level Components

```text
+----------------------------------------------------------+
| Raspberry Pi 4: anvilmobile                              |
|                                                          |
|  +-------------------+                                   |
|  | User Interface    |                                   |
|  +---------+---------+                                   |
|            |                                             |
|  +---------v---------+                                   |
|  | Application       |                                   |
|  | Services          |                                   |
|  +----+----------+---+                                   |
|       |          |                                       |
|  +----v----+ +---v------------------+                    |
|  | Domain  | | Ports / Interfaces   |                    |
|  | Models  | | Radio, GPS, Audio,   |                    |
|  +---------+ | Buttons, Storage, API|                    |
|              +---+------------------+                    |
|                  |                                       |
|  +---------------v------------------------------------+  |
|  | Adapters                                            |  |
|  | FT-891 | GPS | Microphone | ESP32 | SQLite | HTTP  |  |
|  +----------------------------------------------------+  |
+-----------------------------+----------------------------+
                              |
                    WireGuard / network when available
                              |
                    +---------v---------+
                    | Forge services    |
                    | APIs and heavier  |
                    | processing        |
                    +-------------------+
```

## Layer Responsibilities

### User Interface

The user interface presents information and accepts operator input.

It must not:

- open serial or audio devices directly
- contain radio protocol commands
- perform blocking network requests
- contain database implementation details
- decide synchronization policy

### Application Services

Application services coordinate use cases such as:

- displaying current radio state
- recording a contact
- selecting or tuning a POTA frequency
- processing callsign input
- synchronizing queued contacts
- handling online and offline transitions

Application services depend on typed interfaces rather than concrete hardware.

### Domain Models

Domain models represent stable project concepts, such as:

- contact
- callsign
- frequency
- radio mode
- radio state
- geographic position
- POTA activation or spot
- synchronization state

Domain models should not depend on GUI, HTTP, serial, database, or Raspberry Pi
libraries.

### Ports and Interfaces

Ports define typed boundaries for external capabilities.

Expected examples include:

- `Radio`
- `GpsReceiver`
- `SpeechRecognizer`
- `ButtonController`
- `ContactRepository`
- `RemoteApiClient`
- `Clock`

Protocols or abstract base classes may be used. Prefer the smallest interface
that supports the required use case.

### Adapters

Adapters implement ports using real or simulated resources.

Examples:

- Yaesu FT-891 CAT adapter
- mock radio adapter
- serial GPS adapter
- mock GPS adapter
- USB audio adapter
- ESP32 button and LED adapter
- SQLite contact repository
- Forge REST client

Operating-system paths such as `/dev/ttyUSB0` belong only in configuration and
adapter code.

## Offline-First Operation

The Pi client must continue to provide useful behavior when Forge is
unavailable.

The intended offline flow is:

1. The operator records a contact.
2. The contact is written immediately to local durable storage.
3. The contact is marked as pending synchronization.
4. The application periodically checks connectivity.
5. Pending contacts are uploaded when the remote service becomes available.
6. Successful uploads are marked synchronized without deleting the local
   record.

A network failure must not lose a contact or crash the application.

## Hardware Development Strategy

Every hardware capability should be implemented in this order:

1. Define the typed interface.
2. Create a deterministic mock or fake.
3. Build application behavior against the interface.
4. Add automated tests using the mock.
5. Implement the physical hardware adapter.
6. Test the adapter on `anvilmobile`.
7. Add graceful device-disconnect handling.

## Configuration

Configuration should eventually include:

- operator callsign
- home grid
- Forge API URL
- mock hardware mode
- radio device preference
- GPS device preference
- audio device preference
- local database path
- synchronization settings

Configuration errors should produce clear, actionable messages.

Secrets, private keys, passwords, and access tokens must not be committed.

## Concurrency

Potentially blocking operations must not execute in the UI thread.

This includes:

- serial reads and writes
- GPS reads
- speech recognition
- audio capture
- HTTP requests
- synchronization
- database maintenance

The exact concurrency model will be selected with the GUI framework, but
cancellation, shutdown, and device loss must be handled explicitly.

## Initial Package Direction

The exact structure may evolve, but new work should preserve these boundaries:

```text
src/rolling_thunder/
    application/
    domain/
    hardware/
    infrastructure/
    ui/
```

Do not reorganize the current repository merely to match this example. Add
structure incrementally as features require it.

## Deployment Model

The application is developed and hardware-tested directly on `anvilmobile`
through VS Code Remote SSH.

Forge is not required for the normal edit, lint, type-check, or test loop.

The normal development loop is:

```text
feature branch
    -> implementation and tests
    -> Ruff, MyPy, pytest
    -> push to GitHub
    -> GitHub Actions
    -> pull request
    -> Raspberry Pi hardware validation
    -> merge
```
