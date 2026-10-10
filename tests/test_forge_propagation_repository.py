"""Offline repository tests for Forge propagation-history persistence."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID

import pytest

from rolling_thunder.domain import Contact, ContactGridSource, ContactSource, RadioMode
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    IonosphereCorrelation,
    IonosphereMetric,
    Kc2gSnapshot,
    PropagationCollectionProvider,
    PropagationCollectionResult,
    PropagationHistoryStorageError,
    SolarObservation,
    VoacapPrediction,
    WeatherObservation,
    WeatherObservationRole,
)

CONTACT_ID = UUID("11111111-2222-4333-8444-555555555555")
STARTED_AT = datetime(2026, 10, 7, 1, 2, 3, tzinfo=UTC)
CAPTURED_AT = datetime(2026, 10, 7, 1, 5, tzinfo=UTC)


@pytest.fixture
def database(tmp_path: Path) -> Path:
    return tmp_path / "propagation.sqlite3"


@pytest.fixture
def repository(database: Path) -> ForgePropagationHistoryRepository:
    return ForgePropagationHistoryRepository(database)


@pytest.fixture
def contact() -> Contact:
    return Contact(
        contact_id=CONTACT_ID,
        callsign="KC1OXG",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=STARTED_AT,
        rst_sent="-10",
        rst_received="-12",
        grid="FN31pr",
        my_grid="EM79xp",
        source=ContactSource.FT8,
        tx_power_watts=55,
        grid_source=ContactGridSource.QRZ,
    )


def test_schema_tables_integrity_and_version_are_exact(
    repository: ForgePropagationHistoryRepository, database: Path
) -> None:
    assert repository.table_names() == frozenset(
        {
            "propagation_schema_metadata",
            "propagation_provider_status",
            "solar_observation",
            "kc2g_snapshot",
            "weather_observation",
            "qso_observation",
            "qso_ionosphere",
            "qso_voacap_prediction",
            "pskreporter_query",
            "qso_pskreporter_summary",
            "psk_reception",
            "psk_qso_reception",
            "psk_normalization_audit",
        }
    )

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute(
            "SELECT singleton_id, schema_version FROM propagation_schema_metadata"
        ).fetchall() == [(1, 4)]


def test_v1_schema_migrates_without_losing_existing_psk_summary(database: Path) -> None:
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE propagation_schema_metadata (
                singleton_id INTEGER PRIMARY KEY CHECK(singleton_id=1),
                schema_version INTEGER NOT NULL
            );
            INSERT INTO propagation_schema_metadata VALUES (1, 1);
            CREATE TABLE qso_pskreporter_summary (
                contact_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                queried_at_utc TEXT, raw_response_json TEXT,
                summary_json TEXT, last_error TEXT
            );
            INSERT INTO qso_pskreporter_summary VALUES (
                '11111111-2222-4333-8444-555555555555',
                'queried_zero_reports', '2026-10-07T01:05:00Z',
                '{"legacy":true}', '{"report_count":0}', NULL
            );
            """
        )

    repository = ForgePropagationHistoryRepository(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "SELECT schema_version FROM propagation_schema_metadata"
        ).fetchone() == (4,)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(qso_pskreporter_summary)")
        }
        row = connection.execute(
            "SELECT query_id, status, raw_response_json "
            "FROM qso_pskreporter_summary WHERE contact_id = ?",
            (str(CONTACT_ID),),
        ).fetchone()
    assert "query_id" in columns
    assert row == (None, "queried_zero_reports", '{"legacy":true}')
    restored = repository.read_pskreporter(CONTACT_ID)
    assert restored is not None
    assert restored.query_id is None


def test_add_solar_exact_replay_does_not_duplicate(
    repository: ForgePropagationHistoryRepository, database: Path
) -> None:
    observation = SolarObservation(
        source_url="https://www.hamqsl.com/solarxml.php",
        source_updated="07 Oct 2026 0100 GMT",
        collected_at_utc=CAPTURED_AT,
        raw_xml="<solar><solardata/></solar>",
        solarflux="150",
        aindex="7",
        kindex="2",
        xray="B1.2",
        sunspots="90",
        protonflux="0.10",
        aurora="1",
        normalization="1.00",
        latdegree="67.3",
        solarwind="410.2",
        magneticfield="5.1",
        geomagfield="QUIET",
        signalnoise="S1-S2",
    )

    repository.add_solar(observation)
    repository.add_solar(observation)

    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM solar_observation").fetchone() == (1,)


def test_provider_attempt_state_is_durable_and_preserves_last_success(
    repository: ForgePropagationHistoryRepository,
) -> None:
    first_attempt = CAPTURED_AT
    failed_attempt = CAPTURED_AT + timedelta(hours=1)

    repository.begin_provider_attempt(PropagationCollectionProvider.SOLAR, first_attempt)
    repository.complete_provider_success(PropagationCollectionProvider.SOLAR, first_attempt)
    repository.begin_provider_attempt(PropagationCollectionProvider.SOLAR, failed_attempt)
    repository.complete_provider_failure(
        PropagationCollectionProvider.SOLAR,
        failed_attempt,
        "provider unavailable",
    )

    record = repository.get_provider_record(PropagationCollectionProvider.SOLAR)
    assert record is not None
    assert record.last_result is PropagationCollectionResult.FAILURE
    assert record.last_attempt_at_utc == failed_attempt
    assert record.last_success_at_utc == first_attempt
    assert record.consecutive_failures == 1
    assert record.last_error == "provider unavailable"


def test_add_kc2g_replay_and_round_trip(
    repository: ForgePropagationHistoryRepository, database: Path
) -> None:
    snapshot = _kc2g_snapshot()

    repository.add_kc2g(snapshot)
    repository.add_kc2g(snapshot)

    assert repository.read_kc2g(snapshot.metric, snapshot.collected_at_utc) == snapshot
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT count(*), compression, length(sha256), length(snapshot_blob) "
            "FROM kc2g_snapshot"
        ).fetchone()
    assert row is not None
    assert row[0:3] == (1, "gzip", 64)
    assert row[3] > 0


def test_nearest_kc2g_snapshot_selects_before_after_tie_and_rejects_old(
    repository: ForgePropagationHistoryRepository,
) -> None:
    qso_time = datetime(2026, 10, 7, 2, 0, tzinfo=UTC)
    before = _kc2g_snapshot_at(IonosphereMetric.MUF_3000, qso_time - timedelta(minutes=20))
    after = _kc2g_snapshot_at(IonosphereMetric.MUF_3000, qso_time + timedelta(minutes=20))
    fof2_after = _kc2g_snapshot_at(IonosphereMetric.FOF2, qso_time + timedelta(minutes=5))
    for snapshot in (after, before, fof2_after):
        repository.add_kc2g(snapshot)

    assert repository.nearest_kc2g_snapshot(IonosphereMetric.MUF_3000, qso_time) == before
    assert (
        repository.nearest_kc2g_snapshot(
            IonosphereMetric.MUF_3000, qso_time - timedelta(minutes=19)
        )
        == before
    )
    assert (
        repository.nearest_kc2g_snapshot(
            IonosphereMetric.MUF_3000, qso_time + timedelta(minutes=19)
        )
        == after
    )
    assert (
        repository.nearest_kc2g_snapshot(IonosphereMetric.FOF2, qso_time)
        == fof2_after
    )
    assert (
        repository.nearest_kc2g_snapshot(
            IonosphereMetric.MUF_3000,
            qso_time + timedelta(minutes=111),
        )
        is None
    )


@pytest.mark.parametrize(
    ("assignment", "value", "message"),
    [
        ("snapshot_blob = ?", b"not gzip", "decompression"),
        ("sha256 = ?", "0" * 64, "checksum"),
    ],
)
def test_read_kc2g_rejects_blob_and_hash_corruption(
    repository: ForgePropagationHistoryRepository,
    database: Path,
    assignment: str,
    value: bytes | str,
    message: str,
) -> None:
    snapshot = _kc2g_snapshot()
    repository.add_kc2g(snapshot)
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE kc2g_snapshot SET {assignment}", (value,))

    with pytest.raises(PropagationHistoryStorageError, match=message):
        repository.read_kc2g(snapshot.metric, snapshot.collected_at_utc)


def test_add_qso_accepts_exact_replay_rejects_conflict_and_round_trips(
    repository: ForgePropagationHistoryRepository, database: Path, contact: Contact
) -> None:
    repository.add_qso(contact)
    repository.add_qso(contact)

    assert repository.get_qso(CONTACT_ID) == contact
    restored = repository.get_qso(CONTACT_ID)
    assert restored is not None
    assert restored.my_grid6 == "EM79xp"
    assert restored.grid_source is ContactGridSource.QRZ
    assert restored.source is ContactSource.FT8
    assert restored.tx_power_watts == 55

    conflicting = contact.model_copy(update={"tx_power_watts": 60})
    with pytest.raises(
        PropagationHistoryStorageError,
        match=r"idempotency conflict.*11111111-2222-4333-8444-555555555555",
    ):
        repository.add_qso(conflicting)

    assert repository.get_qso(CONTACT_ID) == contact
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM qso_observation").fetchone() == (1,)


def test_save_weather_keeps_roles_separate_and_upserts_only_same_role(
    repository: ForgePropagationHistoryRepository, database: Path
) -> None:
    local = _weather(WeatherObservationRole.LOCAL, provider_id="local-v1", offset=0)
    contact = _weather(WeatherObservationRole.CONTACT, provider_id="remote", offset=1)
    replacement = _weather(
        WeatherObservationRole.LOCAL, provider_id="local-v2", offset=2
    )

    repository.save_weather(local)
    repository.save_weather(contact)
    repository.save_weather(replacement)

    observations = repository.read_weather(CONTACT_ID)
    by_role = {observation.role: observation for observation in observations}
    assert set(by_role) == {
        WeatherObservationRole.LOCAL,
        WeatherObservationRole.CONTACT,
    }
    assert by_role[WeatherObservationRole.LOCAL] == replacement
    assert by_role[WeatherObservationRole.CONTACT] == contact
    assert by_role[WeatherObservationRole.LOCAL].fetched_at_utc.tzinfo is UTC
    assert by_role[WeatherObservationRole.CONTACT].source_at_utc == datetime(
        2026, 10, 7, 0, 1, tzinfo=UTC
    )
    assert by_role[WeatherObservationRole.CONTACT].attribution_text == "Weather source"
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT count(*) FROM weather_observation").fetchone() == (2,)


def test_save_ionosphere_upserts_documented_columns_and_refs(
    repository: ForgePropagationHistoryRepository, database: Path
) -> None:
    initial = IonosphereCorrelation(
        contact_id=CONTACT_ID,
        captured_at_utc=CAPTURED_AT,
        muf_snapshot_at_utc=datetime(2026, 10, 7, 0, 0, tzinfo=UTC),
        payload_json={"path_minimum_muf_mhz": 12.4},
    )
    replacement = IonosphereCorrelation(
        contact_id=CONTACT_ID,
        captured_at_utc=datetime(2026, 10, 7, 2, 5, tzinfo=UTC),
        muf_snapshot_at_utc=datetime(2026, 10, 7, 1, 0, tzinfo=UTC),
        fof2_snapshot_at_utc=datetime(2026, 10, 7, 1, 30, tzinfo=UTC),
        payload_json={"path_minimum_muf_mhz": 13.1, "method": "fixture"},
    )

    repository.save_ionosphere(initial)
    repository.save_ionosphere(replacement)

    assert repository.read_ionosphere(CONTACT_ID) == replacement

    with sqlite3.connect(database) as connection:
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(qso_ionosphere)")
        }
        row = connection.execute(
            "SELECT captured_at_utc, muf_snapshot_at_utc, fof2_snapshot_at_utc, "
            "payload_json FROM qso_ionosphere WHERE contact_id = ?",
            (str(CONTACT_ID),),
        ).fetchone()
    assert columns == {
        "contact_id",
        "captured_at_utc",
        "muf_snapshot_at_utc",
        "fof2_snapshot_at_utc",
        "payload_json",
    }
    assert row == (
        "2026-10-07T02:05:00Z",
        "2026-10-07T01:00:00Z",
        "2026-10-07T01:30:00Z",
        '{"method":"fixture","path_minimum_muf_mhz":13.1}',
    )


def test_save_voacap_stores_exact_request_response_and_fields(
    repository: ForgePropagationHistoryRepository, database: Path
) -> None:
    prediction = VoacapPrediction(
        contact_id=CONTACT_ID,
        captured_at_utc=CAPTURED_AT,
        request_json={"tx_grid": "EM79xp", "rx_grid": "FN31pr", "power_watts": 55},
        service_version="2.4.1",
        response_json={"analysis": {"best_band": 20}, "status": "ok"},
        actual_hour_muf_mhz=18.2,
        actual_hour_reliability=0.83,
        actual_hour_rating="good",
        actual_hour_snr_db=-7.5,
    )

    repository.save_voacap(prediction)

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_json, service_version, response_json, actual_hour_muf_mhz, "
            "actual_hour_reliability, actual_hour_rating, actual_hour_snr_db "
            "FROM qso_voacap_prediction WHERE contact_id = ?",
            (str(CONTACT_ID),),
        ).fetchone()
    assert row == (
        '{"power_watts":55,"rx_grid":"FN31pr","tx_grid":"EM79xp"}',
        "2.4.1",
        '{"analysis":{"best_band":20},"status":"ok"}',
        18.2,
        0.83,
        "good",
        -7.5,
    )


@pytest.mark.parametrize("table", ["weather_observation", "qso_observation"])
def test_malformed_json_reads_are_storage_errors(
    repository: ForgePropagationHistoryRepository,
    database: Path,
    contact: Contact,
    table: str,
) -> None:
    if table == "weather_observation":
        repository.save_weather(_weather(WeatherObservationRole.LOCAL, "local", 0))
    else:
        repository.add_qso(contact)
    with sqlite3.connect(database) as connection:
        connection.execute(f"UPDATE {table} SET payload_json = ?", ("{malformed",))

    with pytest.raises(PropagationHistoryStorageError, match="payload validation failed"):
        if table == "weather_observation":
            repository.read_weather(CONTACT_ID)
        else:
            repository.get_qso(CONTACT_ID)


def _kc2g_snapshot() -> Kc2gSnapshot:
    return _kc2g_snapshot_at(IonosphereMetric.FOF2, CAPTURED_AT)


def _kc2g_snapshot_at(
    metric: IonosphereMetric, collected_at: datetime
) -> Kc2gSnapshot:
    return Kc2gSnapshot(
        metric=metric,
        source_url=f"https://prop.kc2g.com/renders/current/{metric.value}-normal-now.geojson",
        collected_at_utc=collected_at,
        geojson={
            "type": "FeatureCollection",
            "features": [
                {
                    "properties": {"level-value": 7.25},
                    "geometry": {
                        "type": "LineString",
                        "coordinates": [[-85.0, 39.0], [-84.0, 39.0]],
                    },
                    "type": "Feature",
                }
            ],
        },
    )


def _weather(
    role: WeatherObservationRole, provider_id: str, offset: int
) -> WeatherObservation:
    return WeatherObservation(
        contact_id=CONTACT_ID,
        role=role,
        provider_id=provider_id,
        provider_name="Fixture Weather",
        attribution_text="Weather source",
        attribution_url="https://weather.example/attribution",
        license_name="Fixture license",
        license_url="https://weather.example/license",
        source_at_utc=datetime(2026, 10, 7, 0, offset, tzinfo=UTC),
        fetched_at_utc=datetime(2026, 10, 7, 1, offset, tzinfo=UTC),
        latitude=39.1031,
        longitude=-84.5120,
        condition="Clear",
        temperature_c=18.5 + offset,
        relative_humidity_percent=54.0,
        payload_json={"provider_sequence": offset, "raw": {"code": 0}},
    )
