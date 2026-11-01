"""Offline, non-actuating Tron command vocabulary and deterministic intent parsing.

This module performs no microphone access, UI dispatch, logging, or radio control.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

TronAction = Literal["help", "status", "current_screen", "navigate"]

# Names here are intent labels, not UI route identifiers. Integration must map
# each one to an existing approved navigation controller.
_SCREEN_PHRASES: Final[dict[str, str]] = {
    "dashboard": "dashboard",
    "home": "dashboard",
    "ft eight": "ft8",
    "ft8": "ft8",
    "pota": "pota",
    "dx": "dx",
    "map": "map",
    "log": "log",
    "settings": "settings",
}
_NAVIGATION_PREFIXES: Final[tuple[str, ...]] = (
    "open ", "show ", "go to ", "navigate to ",
)
_SIMPLE: Final[dict[str, TronAction]] = {
    "help": "help",
    "what can i say": "help",
    "status": "status",
    "system status": "status",
    "where am i": "current_screen",
    "current screen": "current_screen",
}


@dataclass(frozen=True)
class TronIntent:
    """A recognized read-only operator request; never an authorization to act."""

    action: TronAction
    target: str | None = None


def command_grammar() -> tuple[str, ...]:
    """Return bounded Vosk phrases including the explicit wake prefix."""
    commands = list(_SIMPLE)
    commands.extend(
        f"{prefix}{screen}"
        for prefix in _NAVIGATION_PREFIXES
        for screen in _SCREEN_PHRASES
    )
    return tuple(f"tron {command}" for command in commands) + ("[unk]",)


def parse_tron_command(transcript: str) -> TronIntent | None:
    """Accept only exact, prefixed, allowlisted commands; fail closed."""
    normalized = re.sub(r"\s+", " ", transcript.strip().lower())
    if not normalized.startswith("tron "):
        return None
    command = normalized[5:]
    action = _SIMPLE.get(command)
    if action is not None:
        return TronIntent(action)
    for prefix in _NAVIGATION_PREFIXES:
        if command.startswith(prefix):
            target = _SCREEN_PHRASES.get(command[len(prefix):])
            if target is not None:
                return TronIntent("navigate", target)
    return None
