"""Immutable local QSO coordinates across persistence and recovery contracts."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder import storage
from rolling_thunder.contact_backup import create_contact_backup
from rolling_thunder.contact_export import export_contacts_to_json
from rolling_thunder.contact_import import import_contacts_from_json
from rolling_thunder.contact_repository import ContactConflictError, ContactRepository
from rolling_thunder.contact_retry import ContactRetryRepository
from rolling_thunder.domain import (
    Contact,
    ContactEnrichmentState,
    ContactGridSource,
    SynchronizationState,
)
from rolling_thunder.forge_contact_sync import _remote_payload_sha256
from rolling_thunder.wavelog import contact_to_adif

NOW = datetime(2026, 10, 4, tzinfo=UTC)


def contact(**overrides: object) -> Contact:
    return Contact.model_validate(
        {
            "callsign": "K1ABC",
            "frequency_hz": 14_074_000,
            "mode": "FT8",
            "started_at": NOW,
            "rst_sent": "+14",
            "rst_received": "-10",
            "my_grid": "EM79xm",
            "my_latitude": 39.5309,
            "my_longitude": -84.0866,
            **overrides,
        }
    )


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (None, None),
        (0, 0),
        (-90, -180),
        (90, 180),
        (39.5309, -84.0866),
        (-39.0, 84.0),
    ],
)
def test_valid_coordinates_are_frozen(latitude: float | None, longitude: float | None) -> None:
    qso = contact(my_latitude=latitude, my_longitude=longitude)
    assert (qso.my_latitude, qso.my_longitude) == (latitude, longitude)
    with pytest.raises(ValidationError, match="frozen"):
        qso.my_latitude = 1.0


def test_local_grid_accessors_have_one_six_character_source_of_truth() -> None:
    qso = contact(my_grid="em79XM")

    assert qso.my_grid == "EM79xm"
    assert qso.my_grid6 == "EM79xm"
    assert qso.my_grid4 == qso.my_grid6[:4] == "EM79"

    for invalid in ("EM79", "EM79xm12"):
        with pytest.raises(ValidationError, match="six-character"):
            contact(my_grid=invalid)


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [
        (39, None),
        (None, -84),
        (91, -84),
        (-91, -84),
        (39, 181),
        (39, -181),
        (True, -84),
        (39, False),
        (float("nan"), -84),
        (39, float("inf")),
        ("39", -84),
    ],
)
def test_invalid_coordinate_pairs_are_rejected(latitude: object, longitude: object) -> None:
    with pytest.raises(ValidationError):
        contact(my_latitude=latitude, my_longitude=longitude)


def test_all_repository_paths_preserve_coordinates(tmp_path: Path) -> None:
    repository = ContactRepository(tmp_path / "contacts.db")
    qso = contact(
        enrichment_state=ContactEnrichmentState.PENDING_QRZ,
        my_state="OH",
        my_cq_zone=4,
        my_itu_zone=8,
    )
    repository.add(qso)
    assert repository.get(qso.contact_id) == qso
    retries = ContactRetryRepository(tmp_path / "contacts.db")
    retries.record_failure(
        qso.contact_id, failed_at=NOW, error_message="offline", initial_delay_s=1, max_delay_s=60
    )
    assert repository.get(qso.contact_id) == qso
    retries.clear(qso.contact_id)
    assert repository.list_all() == [qso]
    assert repository.list_recent() == [qso]
    assert repository.list_since(NOW) == [qso]
    assert repository.list_by_synchronization_state(SynchronizationState.PENDING) == [qso]
    assert repository.list_by_enrichment_state(ContactEnrichmentState.PENDING_QRZ) == [qso]
    enriched = repository.complete_enrichment(
        qso.contact_id, grid="FN31pr", grid_source=ContactGridSource.QRZ
    )
    assert (enriched.my_latitude, enriched.my_longitude) == (39.5309, -84.0866)
    assert (enriched.my_state, enriched.my_cq_zone, enriched.my_itu_zone) == ("OH", 4, 8)
    assert repository.list_synchronization_eligible(SynchronizationState.PENDING) == [enriched]
    repository.update_synchronization_state(qso.contact_id, SynchronizationState.SYNCHRONIZED)
    replay = repository.add_idempotent(qso)
    assert replay.my_latitude == qso.my_latitude
    assert replay.my_longitude == qso.my_longitude
    assert replay.synchronization_state is SynchronizationState.SYNCHRONIZED
    changed = contact(**{**replay.model_dump(), "my_latitude": 40.0, "my_longitude": -83.0})
    with pytest.raises(ContactConflictError):
        repository.add_idempotent(changed)
    assert repository.update(changed) == changed
    assert repository.get(qso.contact_id) == changed
    restored = ContactRepository(tmp_path / "restored.db")
    restored.recover_contacts([changed])
    assert restored.get(qso.contact_id) == changed
    cleared = contact(
        **{
            **changed.model_dump(),
            "my_latitude": None,
            "my_longitude": None,
            "my_state": None,
            "my_cq_zone": None,
            "my_itu_zone": None,
        }
    )
    repository.update(cleared)
    assert repository.delete(qso.contact_id) == cleared


def test_schema_16_migration_preserves_all_existing_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "legacy.db"
    with monkeypatch.context() as patch:
        patch.setattr(storage, "CURRENT_SCHEMA_VERSION", 16)
        storage.initialize_database(path)
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO contacts (contact_id, callsign, frequency_hz, mode, started_at, rst_sent, rst_received, synchronization_state) VALUES ('11111111-2222-3333-4444-555555555555', 'K1ABC', 14074000, 'FT8', '2026-10-04T00:00:00Z', '+14', '-10', 'failed')"
        )
        db.execute(
            "INSERT INTO contact_sync_retries (contact_id, attempt_count, next_attempt_at, last_error) VALUES ('11111111-2222-3333-4444-555555555555', 2, '2026-10-05T00:00:00Z', 'offline')"
        )
        db.execute(
            "INSERT INTO ft8_performance_outbox (attempt_id, payload_json) VALUES ('attempt', '{}')"
        )
        old_columns = [row[1] for row in db.execute("PRAGMA table_info(contacts)")]
        before = db.execute("SELECT * FROM contacts").fetchall()
        retry = db.execute("SELECT * FROM contact_sync_retries").fetchall()
        telemetry = db.execute("SELECT * FROM ft8_performance_outbox").fetchall()
    assert storage.initialize_database(path) == 21
    assert storage.initialize_database(path) == 21
    historical = ContactRepository(path).list_all()[0]
    assert historical.my_latitude is None and historical.my_longitude is None
    assert historical.my_state is None
    assert historical.my_cq_zone is None
    assert historical.my_itu_zone is None
    assert historical.tx_power_watts is None
    assert historical.weather_notes_enabled is False
    with sqlite3.connect(path) as db:
        assert db.execute(f"SELECT {', '.join(old_columns)} FROM contacts").fetchall() == before
        assert db.execute(
            "SELECT my_state, my_cq_zone, my_itu_zone FROM contacts"
        ).fetchall() == [(None, None, None)]
        assert db.execute("SELECT * FROM contact_sync_retries").fetchall() == retry
        assert db.execute("SELECT * FROM ft8_performance_outbox").fetchall() == telemetry
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert (
            db.execute("PRAGMA foreign_key_list(contact_sync_retries)").fetchone()[2] == "contacts"
        )


def test_export_and_verified_backup_round_trip_coordinates(tmp_path: Path) -> None:
    repository = ContactRepository(tmp_path / "source.db")
    qso = contact(my_state="OH", my_cq_zone=4, my_itu_zone=8)
    repository.add(qso)
    export = tmp_path / "contacts.json"
    export_contacts_to_json(repository, export, exported_at=NOW)
    assert json.loads(export.read_text())["format_version"] == 5
    backup = create_contact_backup(
        repository, tmp_path / "backups", retention_count=2, created_at=NOW
    )
    for number, source in enumerate([export, backup.path]):
        target = ContactRepository(tmp_path / f"target-{number}.db")
        import_contacts_from_json(target, source)
        assert target.get(qso.contact_id) == qso


@pytest.mark.parametrize("version", [1, 2, 3])
def test_legacy_exports_have_no_fabricated_coordinates(tmp_path: Path, version: int) -> None:
    qso = contact().model_dump(mode="json")
    del qso["my_state"]
    del qso["my_cq_zone"]
    del qso["my_itu_zone"]
    if version in (1, 2):
        del qso["my_latitude"]
        del qso["my_longitude"]
    source = tmp_path / "legacy.json"
    source.write_text(
        json.dumps({"format_version": version, "exported_at": NOW.isoformat(), "contacts": [qso]})
    )
    target = ContactRepository(tmp_path / "target.db")
    import_contacts_from_json(target, source)
    restored = target.list_all()[0]
    assert restored.my_state is None
    assert restored.my_cq_zone is None
    assert restored.my_itu_zone is None


def test_coordinates_do_not_change_wavelog_payload_or_ledger_hash() -> None:
    qso = contact(my_state="OH", my_cq_zone=4, my_itu_zone=8)
    legacy = contact(
        **{
            **qso.model_dump(),
            "my_state": None,
            "my_cq_zone": None,
            "my_itu_zone": None,
        }
    )
    assert contact_to_adif(qso) == contact_to_adif(legacy)
    assert _remote_payload_sha256(qso, station_profile_id=42) == _remote_payload_sha256(
        legacy, station_profile_id=42
    )



def test_jurisdiction_fields_are_normalized_frozen_and_validated() -> None:
    qso = contact(my_state=" oh ", my_cq_zone=4, my_itu_zone=8)
    assert (qso.my_state, qso.my_cq_zone, qso.my_itu_zone) == ("OH", 4, 8)
    with pytest.raises(ValidationError, match="frozen"):
        qso.my_state = "IN"


@pytest.mark.parametrize(
    ("state", "cq_zone", "itu_zone"),
    [
        ("", 4, 8),
        ("OHIO", 4, 8),
        ("OH", True, 8),
        ("OH", 0, 8),
        ("OH", 41, 8),
        ("OH", 4, True),
        ("OH", 4, 0),
        ("OH", 4, 91),
        ("OH", None, 8),
        (None, 4, 8),
    ],
)
def test_invalid_jurisdiction_is_rejected(
    state: object,
    cq_zone: object,
    itu_zone: object,
) -> None:
    with pytest.raises(ValidationError):
        contact(my_state=state, my_cq_zone=cq_zone, my_itu_zone=itu_zone)
