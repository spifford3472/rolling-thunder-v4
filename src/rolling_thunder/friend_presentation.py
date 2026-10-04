"""No-I/O friend decoration for remote station presentation only."""

FRIEND_GLYPH = "★"
FRIEND_COLOR = "#ffd24a"


def friend_marker(callsign: str, friends: frozenset[str]) -> str:
    """Exact normalized station match; never changes the underlying callsign."""
    return FRIEND_GLYPH if callsign.strip().upper() in friends else ""
