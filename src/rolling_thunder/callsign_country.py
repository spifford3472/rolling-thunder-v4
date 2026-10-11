"""Conservative offline callsign-to-country display for the mobile log panel."""

from __future__ import annotations

from typing import Final

# Display-only rules. They deliberately cover common unambiguous amateur prefixes and
# return an em dash when uncertain rather than inventing a country. This module performs
# no network I/O and is not used for synchronization or regulatory decisions.
_PREFIX_COUNTRIES: Final[tuple[tuple[str, str], ...]] = tuple(
    sorted(
        (
            # Additional unambiguous ITU series, per ARRL allocation table.
            # Prefix alone is an advisory allocation, never a verified QTH.
            ("A2", "BWA"), ("A3", "TON"), ("A4", "OMN"),
            ("A5", "BTN"), ("A6", "ARE"), ("A7", "QAT"),
            ("A8", "LBR"), ("A9", "BHR"), ("8P", "BRB"),
            ("9H", "MLT"), ("4X", "ISR"), ("4Z", "ISR"),
            ("5B", "CYP"), ("ZP", "PRY"), ("YV", "VEN"),
            ("AA", "USA"), ("AB", "USA"), ("AC", "USA"), ("AD", "USA"),
            ("AE", "USA"), ("AF", "USA"), ("AG", "USA"), ("AH", "USA"),
            ("AI", "USA"), ("AJ", "USA"), ("AK", "USA"), ("AL", "USA"),
            ("K", "USA"), ("N", "USA"), ("W", "USA"),
            ("CF", "CAN"), ("CG", "CAN"), ("CH", "CAN"), ("CI", "CAN"),
            ("CJ", "CAN"), ("CK", "CAN"), ("CY", "CAN"), ("CZ", "CAN"),
            ("VA", "CAN"), ("VB", "CAN"), ("VC", "CAN"), ("VD", "CAN"),
            ("VE", "CAN"), ("VF", "CAN"), ("VG", "CAN"), ("VO", "CAN"),
            ("VX", "CAN"), ("VY", "CAN"), ("XJ", "CAN"), ("XK", "CAN"),
            ("XL", "CAN"), ("XM", "CAN"), ("XN", "CAN"), ("XO", "CAN"),
            ("G", "GBR"), ("M", "GBR"), ("2E", "GBR"),
            ("DL", "DEU"), ("DJ", "DEU"), ("DK", "DEU"), ("DF", "DEU"),
            ("DG", "DEU"), ("DH", "DEU"), ("DM", "DEU"), ("DN", "DEU"),
            ("DO", "DEU"), ("DP", "DEU"), ("DQ", "DEU"), ("DR", "DEU"),
            ("F", "FRA"), ("I", "ITA"), ("EA", "ESP"), ("EB", "ESP"),
            ("EC", "ESP"), ("ED", "ESP"), ("EE", "ESP"), ("EF", "ESP"),
            ("CT", "PRT"), ("EI", "IRL"), ("EJ", "IRL"),
            ("ON", "BEL"), ("OO", "BEL"), ("OP", "BEL"), ("OQ", "BEL"),
            ("OR", "BEL"), ("OS", "BEL"), ("OT", "BEL"),
            ("PA", "NLD"), ("PB", "NLD"), ("PC", "NLD"), ("PD", "NLD"),
            ("PE", "NLD"), ("PF", "NLD"), ("PG", "NLD"), ("PH", "NLD"),
            ("PI", "NLD"), ("HB", "CHE"), ("OE", "AUT"),
            ("OK", "CZE"), ("OL", "CZE"), ("OM", "SVK"),
            ("HA", "HUN"), ("HG", "HUN"), ("YO", "ROU"), ("YR", "ROU"),
            ("LZ", "BGR"), ("9A", "HRV"), ("S5", "SVN"),
            ("YT", "SRB"), ("YU", "SRB"),
            ("JA", "JPN"), ("JE", "JPN"), ("JF", "JPN"), ("JG", "JPN"),
            ("JH", "JPN"), ("JI", "JPN"), ("JJ", "JPN"), ("JK", "JPN"),
            ("JL", "JPN"), ("JM", "JPN"), ("JN", "JPN"), ("JO", "JPN"),
            ("JP", "JPN"), ("JQ", "JPN"), ("JR", "JPN"), ("JS", "JPN"),
            ("VK", "AUS"), ("ZL", "NZL"),
            ("HL", "KOR"), ("DS", "KOR"), ("DT", "KOR"),
            ("6K", "KOR"), ("6L", "KOR"), ("6M", "KOR"), ("6N", "KOR"),
            ("VU", "IND"), ("B", "CHN"),
            ("PY", "BRA"), ("PP", "BRA"), ("PQ", "BRA"), ("PR", "BRA"),
            ("PS", "BRA"), ("PT", "BRA"), ("PU", "BRA"), ("PV", "BRA"),
            ("PW", "BRA"), ("PX", "BRA"),
            ("XE", "MEX"), ("XF", "MEX"), ("XG", "MEX"), ("XH", "MEX"),
            ("XI", "MEX"), ("ZS", "ZAF"), ("ZR", "ZAF"), ("ZT", "ZAF"),
            ("ZU", "ZAF"),
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


def callsign_country_abbreviation(callsign: str) -> str:
    """Return a short country label only for a confidently recognized prefix."""
    normalized = callsign.strip().upper().split("/", 1)[0]
    for prefix, country in _PREFIX_COUNTRIES:
        if normalized.startswith(prefix):
            return country
    return "—"
