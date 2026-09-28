"""Formatting helpers for optional POTA callsign enrichment."""


def format_enriched_callsign(callsign: str, name: str | None) -> str:
    """Return the large POTA-card heading with an optional QRZ name."""
    normalized_name = " ".join(name.split()) if name else ""
    return f"{callsign} - {normalized_name}" if normalized_name else callsign
