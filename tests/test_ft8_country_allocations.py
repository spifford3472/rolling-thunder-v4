"""Selected offline country-prefix coverage sourced from ARRL/ITU allocations."""
from rolling_thunder.callsign_country import callsign_country_abbreviation


def test_selected_itu_series():
    assert callsign_country_abbreviation("A71AA") == "QAT"
    assert callsign_country_abbreviation("8P6AA") == "BRB"
    assert callsign_country_abbreviation("9H1AA") == "MLT"
    assert callsign_country_abbreviation("4X1AA") == "ISR"
    assert callsign_country_abbreviation("5B4AA") == "CYP"
    assert callsign_country_abbreviation("KI5VNB") == "USA"
    assert callsign_country_abbreviation("VE4ZIM") == "CAN"
    assert callsign_country_abbreviation("T1SR") == "—"
