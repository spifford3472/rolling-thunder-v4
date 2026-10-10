"""Verify a deployed Python distribution is importable by its service identity.

Invoke with the *deployed* virtualenv Python as the service user, not the
build machine's interpreter. No privilege escalation occurs in this script.
"""

from __future__ import annotations

import importlib
import sys

REQUIRED_MODULES = (
    "rolling_thunder.forge_contact_sync_main",
    "rolling_thunder.forge_contact_sync_api",
    "rolling_thunder.forge_ft8_periods",
)


def verify() -> None:
    for module in REQUIRED_MODULES:
        importlib.import_module(module)
    print("PASS: Forge contact-sync service-user module imports")


if __name__ == "__main__":
    try:
        verify()
    except (ImportError, PermissionError) as exc:
        print(f"FAIL: Forge service-user module access: {type(exc).__name__}", file=sys.stderr)
        sys.exit(1)
