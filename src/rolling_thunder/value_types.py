"""Reusable validated scalar types for Rolling Thunder."""

import re
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator

_BASE_CALLSIGN_PATTERN = re.compile(r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}$")
_CALLSIGN_PATTERN = re.compile(
    r"^[A-Z0-9]{1,3}[0-9][A-Z0-9]{1,4}(?:/[A-Z0-9]{1,4})?$"
)
_GRID_PATTERN = re.compile(
    r"^[A-R]{2}[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)?$",
    re.IGNORECASE,
)


def _normalize_callsign(value: object) -> object:
    """Normalize string callsigns before structural validation."""
    if isinstance(value, str):
        return value.strip().upper()

    return value


def _validate_base_callsign(value: str) -> str:
    """Validate an operator callsign without a portable suffix."""
    if not _BASE_CALLSIGN_PATTERN.fullmatch(value):
        raise ValueError(
            "must be a valid amateur-radio callsign, such as KI5VNB"
        )

    return value


def _validate_callsign(value: str) -> str:
    """Validate a station callsign with an optional operating suffix."""
    if not _CALLSIGN_PATTERN.fullmatch(value):
        raise ValueError(
            "must be a valid amateur-radio callsign, such as "
            "KI5VNB or KI5VNB/P"
        )

    return value


def _normalize_grid(value: object) -> object:
    """Normalize a Maidenhead locator before structural validation."""
    if not isinstance(value, str):
        return value

    normalized = value.strip()

    if len(normalized) == 4:
        return normalized[:2].upper() + normalized[2:]

    if len(normalized) in {6, 8}:
        return (
            normalized[:2].upper()
            + normalized[2:4]
            + normalized[4:6].lower()
            + normalized[6:]
        )

    return normalized


def _validate_grid(value: str) -> str:
    """Validate a 4-, 6-, or 8-character Maidenhead locator."""
    if not _GRID_PATTERN.fullmatch(value):
        raise ValueError(
            "must be a 4-, 6-, or 8-character Maidenhead grid, "
            "such as EM79xm"
        )

    return value


BaseCallsign = Annotated[
    str,
    BeforeValidator(_normalize_callsign),
    AfterValidator(_validate_base_callsign),
]
"""Normalized operator callsign without an operating suffix."""

Callsign = Annotated[
    str,
    BeforeValidator(_normalize_callsign),
    AfterValidator(_validate_callsign),
]
"""Normalized station callsign with an optional operating suffix."""

MaidenheadGrid = Annotated[
    str,
    BeforeValidator(_normalize_grid),
    AfterValidator(_validate_grid),
]
"""Normalized 4-, 6-, or 8-character Maidenhead grid locator."""
