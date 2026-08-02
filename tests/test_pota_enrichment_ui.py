import pytest

from rolling_thunder.pota_enrichment_ui import (
    format_enriched_callsign,
    weather_symbol,
)


def test_format_enriched_callsign_includes_available_name() -> None:
    assert (
        format_enriched_callsign("KI5VNB", "  Geoff   Kline ")
        == "KI5VNB - Geoff Kline"
    )


def test_format_enriched_callsign_preserves_callsign_only_fallback() -> None:
    assert format_enriched_callsign("KI5VNB", None) == "KI5VNB"
    assert format_enriched_callsign("KI5VNB", "   ") == "KI5VNB"


@pytest.mark.parametrize(
    ("weather_code", "is_day", "expected"),
    [
        (0, True, "☀"),
        (0, False, "☾"),
        (2, True, "⛅"),
        (2, False, "☁"),
        (3, True, "☁"),
        (45, True, "☁"),
        (51, True, "☂"),
        (61, True, "☂"),
        (80, True, "☂"),
        (71, True, "❄"),
        (85, True, "❄"),
        (95, True, "⚡"),
        (99, False, "⚡"),
        (999, True, "☁"),
    ],
)
def test_weather_symbol_uses_basic_requested_symbols(
    weather_code: int,
    is_day: bool,
    expected: str,
) -> None:
    assert weather_symbol(weather_code, is_day=is_day) == expected
