"""Forge-only optional OHGO credentials from systemd's private credential mount.

No credentials are put in URLs, source, YAML, app logs or on the Pi. A missing
credential disables the provider without changing other Forge services.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_ohgo_credential() -> str | None:
    """Return an optional bounded credential from systemd LoadCredential.

    The credential file is provided by the host supervisor and not copied
    into repository code or cross-host environment variables.
    """

    directory = os.environ.get("CREDENTIALS_DIRECTORY")
    if not directory:
        return None
    path = Path(directory) / "ohgo-api-key"
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 256:
            return None
        key = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError, ValueError):
        return None
    if not key or any(ch.isspace() or not ch.isprintable() for ch in key):
        return None
    return key


def ohgo_enabled_by_operator() -> bool:
    """Default-off feature gate, independent of obtaining a credential."""

    return os.environ.get("ROLLING_THUNDER_OHGO_ENABLED") == "1"
