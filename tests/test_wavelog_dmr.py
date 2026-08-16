"""DMR-specific Wavelog ADIF serialization regression tests."""

from datetime import UTC, datetime

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.wavelog import contact_to_adif


def test_dmr_contact_uses_adif_digitalvoice_mode_and_dmr_submode() -> None:
    contact = Contact(
        callsign="KC9KPJ",
        frequency_hz=439_537_500,
        mode=RadioMode.DMR,
        started_at=datetime(2026, 8, 16, 0, 7, 7, tzinfo=UTC),
        rst_sent="59",
        rst_received="59",
        my_grid="EM79xm",
        notes="DMR TS1 TG3100 RX 434.537500 MHz SOURCE NETWORK",
    )

    adif = contact_to_adif(contact)

    assert "<MODE:12>DIGITALVOICE" in adif
    assert "<SUBMODE:3>DMR" in adif
    assert "<FREQ:8>439.5375" in adif
    assert "<MY_GRIDSQUARE:6>EM79xm" in adif
    assert "<MODE:3>DMR" not in adif
