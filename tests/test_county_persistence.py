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


def test_ft8_county_from_frozen_gps_only(tmp_path: Path) -> None:
    from dataclasses import replace
    from datetime import timedelta

    from rolling_thunder.contact_logging import ContactLoggingService
    from rolling_thunder.ft8.coordinator import FT8QsoResult
    from rolling_thunder.ft8.domain import (
        FT8Period,
        FT8PeriodParity,
        FT8QsoContext,
        FT8QsoState,
    )
    from rolling_thunder.ft8.logging import FT8QsoLoggingService
    from rolling_thunder.offline_county_store import IndexedCountyStore

    # Actual independently validated Census artifact; no network or live GPS.
    source = Path(__file__).resolve().parents[1] / "src/rolling_thunder/data/us-counties-2025-500k.sqlite"
    if not source.exists():
        import pytest
        pytest.skip("validated external county fixture is not installed")
    now = datetime(2026, 11, 4, 20, tzinfo=UTC)
    context = FT8QsoContext(
        local_callsign="KI5VNB",
        remote_callsign="K7IOC",
        target_audio_frequency_hz=1500,
        radio_frequency_hz=14_074_000,
        radio_band="20m",
        radio_mode="USB",
        local_grid="EM79xm",
        latitude=39.5298,
        longitude=-84.0866,
        local_state="OH",
        local_cq_zone=4,
        local_itu_zone=8,
        gps_fix_updated_at=now - timedelta(seconds=2),
        gps_accuracy_m=5,
        tx_parity=FT8PeriodParity.ODD,
        authorized_period=FT8Period(int(now.timestamp() // 15)),
        authorized_utc=now,
        signal_report_db=-10,
    )
    repository = ContactRepository(tmp_path / "ft8.sqlite")
    logger = FT8QsoLoggingService(
        ContactLoggingService(repository),
        county_store=IndexedCountyStore(source),
    )

    def completed(ctx: FT8QsoContext) -> FT8QsoResult:
        return FT8QsoResult(
            status=FT8QsoState.COMPLETED,
            context=ctx,
            sent_report_db=-10,
            received_report_db=-12,
            started_utc=now,
            ended_utc=now + timedelta(seconds=75),
            terminal_reason=None,
        )

    first = logger.handle_terminal_result(completed(context))
    assert first is not None
    assert first.my_county == "WARREN"
    assert repository.get(context.qso_id).my_county == "WARREN"
    assert "<MY_CNTY:9>OH,Warren" in contact_to_adif(first)

    for offset, overrides in enumerate((
        {"gps_fix_updated_at": now - timedelta(seconds=11)},
        {"gps_accuracy_m": None},
        {"local_state": "IN"},
        {"gps_fix_updated_at": now + timedelta(seconds=1)},
    ), 1):
        stale_context = replace(
            context,
            qso_id=UUID(f"00000000-0000-0000-0000-{380+offset:012d}"),
            **overrides,
        )
        logged = logger.handle_terminal_result(completed(stale_context))
        assert logged is not None
        assert logged.my_county is None


def test_schema_22_additive_migration_preserves_contact(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    from rolling_thunder import storage

    database = tmp_path / "pre22.sqlite"
    monkeypatch.setattr(storage, "CURRENT_SCHEMA_VERSION", 21)
    storage.initialize_database(database)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """INSERT INTO contacts
               (contact_id, callsign, frequency_hz, mode, started_at,
                rst_sent, rst_received)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            ("00000000-0000-0000-0000-000000000380", "K7IOC", 14074000,
             "USB", "2026-11-04T20:00:00Z", "-10", "-12"),
        )
    monkeypatch.setattr(storage, "CURRENT_SCHEMA_VERSION", 22)
    assert storage.initialize_database(database) == 22
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT callsign, my_county FROM contacts"
        ).fetchone() == ("K7IOC", None)
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_schema_22_failure_rolls_back(tmp_path: Path, monkeypatch) -> None:
    import sqlite3

    import pytest

    from rolling_thunder import storage

    database = tmp_path / "rollback.sqlite"
    monkeypatch.setattr(storage, "CURRENT_SCHEMA_VERSION", 21)
    storage.initialize_database(database)
    monkeypatch.setattr(storage, "CURRENT_SCHEMA_VERSION", 22)
    monkeypatch.setitem(storage._MIGRATIONS, 22, ("ALTER TABLE contacts ADD COLUMN my_county TEXT", "INVALID SQL"))
    with pytest.raises(storage.StorageError):
        storage.initialize_database(database)
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT schema_version FROM schema_metadata").fetchone()[0] == 21
        assert "my_county" not in {row[1] for row in connection.execute("PRAGMA table_info(contacts)")}
