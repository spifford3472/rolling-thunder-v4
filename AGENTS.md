# Rolling Thunder v4 Development Instructions

## Project Purpose

Rolling Thunder v4 is an in-vehicle amateur-radio operating and logging system.

The primary client runs on a Raspberry Pi 4 named `anvilmobile`. The application assists with radio control, callsign entry, contact logging, POTA activity, mapping, GPS position, and station status.

Forge may provide backend APIs and heavier processing, but the Raspberry Pi client must retain useful offline functionality.

## Development Environment

Primary development and hardware testing occur directly on the Raspberry Pi through VS Code Remote SSH.

Project directory:

```text
~/projects/rolling-thunder-v4
```

Python environment:

```text
.venv
```

Activate it with:

```bash
source .venv/bin/activate
```

Install the project and development dependencies with:

```bash
python -m pip install -e ".[development]"
```

## Required Quality Checks

Before considering any change complete, run:

```bash
ruff check src tests
mypy src
pytest
```

All checks must pass.

Pre-commit hooks are installed and should not be bypassed.

Do not use `--no-verify` unless the repository owner explicitly instructs you to do so.

## Git Workflow

Do not develop directly on `main`.

Create a focused feature branch for each change:

```text
feature/<short-description>
fix/<short-description>
docs/<short-description>
```

Keep commits focused and use clear imperative commit messages.

Examples:

```text
Add typed application configuration
Implement mock radio interface
Document offline logging behavior
```

Do not merge branches or push directly to `main`.

## Architecture Principles

Use clear separation between:

1. User interface
2. Application services
3. Domain models
4. Hardware interfaces
5. Network and persistence adapters

Business logic must not depend directly on GUI widgets, serial ports, USB devices, network sockets, or operating-system device paths.

## Hardware Abstraction

All physical hardware must be accessed through typed interfaces or protocols.

Examples include:

- FT-891 radio control
- GPS receiver
- USB microphone
- ESP32 button and LED controller
- audio devices
- future vehicle sensors

Create mock or simulated implementations before requiring physical hardware.

Application and UI code must never directly open paths such as:

```text
/dev/ttyUSB0
/dev/ttyACM0
/dev/snd/*
```

Device discovery and connection details belong in hardware adapter modules.

## Offline-First Behavior

The Raspberry Pi client must remain useful when Forge, WireGuard, or internet access is unavailable.

At minimum, offline mode should eventually support:

- basic contact logging
- local storage of unsynchronized contacts
- radio frequency and mode display when local hardware is available
- GPS position when local hardware is available
- later synchronization when connectivity returns

Network failures must not crash the application.

## Configuration

Configuration must not be hard-coded throughout the source code.

Use a central typed configuration system for items such as:

- callsign
- home grid
- Forge API URL
- mock hardware mode
- serial device preferences
- logging behavior

Do not commit passwords, API keys, private keys, access tokens, or personal credentials.

## Python Standards

Use Python type hints for public functions and methods.

Prefer:

- dataclasses for structured domain data
- protocols or abstract base classes for hardware boundaries
- pathlib instead of manual path manipulation
- explicit exception types
- small focused modules
- dependency injection rather than global hardware instances

Avoid:

- untyped dictionaries passed throughout the application
- broad `except Exception` blocks without a documented reason
- hidden global state
- blocking hardware or network calls in the UI thread
- unnecessary dependencies
- premature distributed-system complexity

## Testing Requirements

New behavior requires tests.

Tests must:

- run without connected radio hardware
- run without Forge
- run without internet access
- avoid depending on timing where possible
- use temporary directories for filesystem tests
- use mocks or fakes at hardware and network boundaries

Bug fixes should include a regression test when practical.

## Scope Control

Make only changes required for the assigned task.

Do not perform unrelated refactoring.

Do not rename modules, restructure directories, or replace dependencies unless the task requires it and the rationale is documented.

When requirements are unclear, choose the smallest implementation consistent with the existing architecture and document assumptions.

## Documentation

Update documentation when a change affects:

- architecture
- configuration
- setup instructions
- hardware support
- development workflow
- user-visible behavior

Keep documentation consistent with the implemented code.

## Current Project Stage

The repository currently contains:

- the Python package structure
- an application bootstrap entry point
- an initial automated test
- Ruff configuration
- MyPy configuration
- pytest configuration
- GitHub Actions continuous integration
- pre-commit development checks

Do not assume radio, GPS, GUI, logging, or Forge integration already exists unless it is present in the repository.

## Definition of Done

A task is complete when:

1. The requested behavior is implemented.
2. Relevant tests are included.
3. Ruff passes.
4. MyPy passes.
5. pytest passes.
6. Documentation is updated where needed.
7. The change is limited to the requested scope.
8. No secrets or machine-specific credentials are committed.
