# Contributing to Rolling Thunder v4

## Development Setup

Work from the repository root on `anvilmobile`.

```bash
source .venv/bin/activate
python -m pip install -e ".[development]"
```

## Branching

Do not develop directly on `main`.

Use a focused branch:

```text
feature/<short-description>
fix/<short-description>
docs/<short-description>
```

Keep each branch limited to one logical change.

## Required Checks

Before committing or opening a pull request, run:

```bash
ruff check src tests
mypy src
pytest
pre-commit run --all-files
```

All checks must pass.

Do not bypass pre-commit with `--no-verify` unless the repository owner
explicitly requests it.

## Tests

New behavior requires tests.

Tests must run without:

- physical radio hardware
- GPS hardware
- Forge
- internet access

Use mocks, fakes, and temporary directories or databases as appropriate.

Bug fixes should include a regression test when practical.

## Architecture

Follow the boundaries documented in `docs/ARCHITECTURE.md`.

In particular:

- UI code must not open hardware devices directly.
- Business logic must depend on interfaces, not concrete adapters.
- Blocking I/O must not run in the UI thread.
- Local logging must remain available during network outages.
- Machine-specific paths and settings belong in configuration.

## Commits

Use clear imperative commit messages.

Examples:

```text
Add typed configuration loader
Implement mock radio adapter
Handle offline contact synchronization
```

Avoid mixing unrelated refactoring with feature work.

## Pull Requests

A pull request should include:

- a concise description of the change
- the reason for the change
- testing performed
- hardware testing performed, when applicable
- assumptions or known limitations
- documentation updates, when applicable

GitHub Actions must pass before merge.

Hardware-dependent changes should be tested on `anvilmobile` before merge.

## Secrets

Never commit:

- passwords
- API keys
- access tokens
- private keys
- personal credentials
- production secrets

Use example values and documented local configuration instead.
