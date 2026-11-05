"""County persistence, idempotency and ADIF regression checks."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from rolling_thunder.contact_repository import ContactRepository
from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.wavelog import contact_to_adif


def test_county_round_trip_and_adif(tmp_path: Path) -> None:
    repository = ContactRepository(tmp_path / "contacts.sqlite")
    contact = Contact(
        contact_id=UUID("00000000-0000-0000-0000-000000000380"),
        callsign="K7IOC",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=datetime(2026, 11, 4, 20, 0, tzinfo=UTC),
        rst_sent="-10",
        rst_received="-12",
        my_latitude=39.5298,
        my_longitude=-84.0866,
        my_state="OH",
        my_cq_zone=4,
        my_itu_zone=8,
        my_county="Warren",
    )
    repository.add(contact)
    restored = repository.get(contact.contact_id)
    assert restored is not None
    assert restored.my_county == "WARREN"
    assert "<MY_CNTY:9>OH,Warren" in contact_to_adif(restored)
    assert "<CNTY:" not in contact_to_adif(restored)
