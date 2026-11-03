"""Offline, non-actuating Tron command vocabulary and exact intent parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Literal

TronAction = Literal["help", "status", "current_screen", "navigate"]

_NAVIGATION_TARGETS: Final[tuple[str, ...]] = (
    "pota", "dx", "ft8", "log", "settings",
)
_SIMPLE: Final[dict[str, TronAction]] = {
    "help": "help",
    "status": "status",
    "current screen": "current_screen",
}


@dataclass(frozen=True)
class TronIntent:
    """A recognized read-only operator request; never an authorization to act."""

    action: TronAction
    target: str | None = None


def command_grammar() -> tuple[str, ...]:
    """Return only the explicitly supported, wake-prefixed Vosk phrases."""
    commands = [f"tron {command}" for command in _SIMPLE]
    commands.extend(f"tron show {target}" for target in _NAVIGATION_TARGETS)
    commands.append("tron show ft eight")
    return tuple(commands) + ("[unk]",)


def parse_tron_command(transcript: str) -> TronIntent | None:
    """Accept only exact wake-prefixed commands and approved read-only targets."""
    normalized = re.sub(r"\s+", " ", transcript.strip().lower())
    if not normalized.startswith("tron "):
        return None
    command = normalized[5:]
    action = _SIMPLE.get(command)
    if action is not None:
        return TronIntent(action)
    prefix = "show "
    if command.startswith(prefix):
        target = command[len(prefix):]
        if target == "ft eight":
            target = "ft8"
        if target in _NAVIGATION_TARGETS:
            return TronIntent("navigate", target)
    return None
