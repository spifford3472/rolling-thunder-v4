from rolling_thunder.pota_enrichment_ui import format_enriched_callsign


def test_format_enriched_callsign_includes_available_name() -> None:
    assert (
        format_enriched_callsign("KI5VNB", "  Geoff   Kline ")
        == "KI5VNB - Geoff Kline"
    )


def test_format_enriched_callsign_preserves_callsign_only_fallback() -> None:
    assert format_enriched_callsign("KI5VNB", None) == "KI5VNB"
    assert format_enriched_callsign("KI5VNB", "   ") == "KI5VNB"
