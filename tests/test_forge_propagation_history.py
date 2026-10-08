"""Offline fixtures for the independent Forge propagation-history component."""

import sqlite3
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from json import dumps, loads
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any

import pytest

from rolling_thunder.domain import Contact, ContactSource, RadioMode
from rolling_thunder.forge_propagation_collectors import (
    HAMQSL_SOLAR_URL,
    ForgePropagationHistoryService,
    HamQslSolarCollector,
    Kc2gContourEstimator,
    VoacapSummaryClient,
    estimate_kc2g_contours,
    sample_great_circle_path,
)
from rolling_thunder.forge_propagation_config import (
    ForgePropagationHistoryConfig,
    load_forge_propagation_config,
)
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    IonosphereMetric,
    Kc2gSnapshot,
    PropagationCollectionProvider,
    PropagationHistoryStorageError,
    SolarObservation,
    VoacapPrediction,
)
from rolling_thunder.forge_propagation_main import main as propagation_main
from rolling_thunder.forge_propagation_runtime import ForgePropagationCollectionRuntime
from rolling_thunder.forge_pskreporter import PskReporterConfig
from rolling_thunder.forge_weather import (
    WeatherConditionToken,
    WeatherCurrent,
    WeatherHourlyPoint,
    WeatherIconToken,
    WeatherSnapshot,
    WeatherSolar,
    WeatherSourceMetadata,
)
from rolling_thunder.http_home_platform import UrllibHttpResponse

ROOT = Path(__file__).resolve().parents[1]
PROPAGATION_EXAMPLE = ROOT / "config/forge-propagation.example.yaml"


class Transport:
    def __init__(self, responses: list[UrllibHttpResponse]) -> None:
        self.responses = responses
        self.requests: list[tuple[str, str, bytes | None]] = []

    def request(self, method, url, *, headers, body, timeout_s):  # type: ignore[no-untyped-def]
        del headers, timeout_s
        self.requests.append((method, url, body))
        return self.responses.pop(0)


class _CollectionSolar:
    def __init__(self, *, failures: int = 0) -> None:
        self.failures = failures
        self.calls = 0

    def fetch(self, collected_at: datetime) -> SolarObservation:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("fixture failure")
        return SolarObservation(
            source_url=HAMQSL_SOLAR_URL,
            source_updated="07 Oct 2026 0200 GMT",
            collected_at_utc=collected_at,
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


class _CollectionKc2g:
    def __init__(self) -> None:
        self.calls: list[IonosphereMetric] = []

    def fetch(self, metric: IonosphereMetric, collected_at: datetime) -> Kc2gSnapshot:
        self.calls.append(metric)
        return Kc2gSnapshot(
            metric=metric,
            source_url=f"https://prop.kc2g.com/{metric.value}.geojson",
            collected_at_utc=collected_at,
            geojson={"type": "FeatureCollection", "features": []},
        )


def test_hamqsl_preserves_raw_values_and_collection_time() -> None:
    fields = {
        "updated": "06 Oct 2026 2200 GMT",
        "solarflux": "148", "aindex": "7", "kindex": "2", "xray": "B1.2",
        "sunspots": "87", "protonflux": "0.10", "aurora": "1",
        "normalization": "1.00", "latdegree": "67.3", "solarwind": "410.2",
        "magneticfield": "5.1", "geomagfield": "QUIET", "signalnoise": "S1-S2",
    }
    xml = "<solar><solardata>" + "".join(
        f"<{key}>{value}</{key}>" for key, value in fields.items()
    ) + "</solardata></solar>"
    collected = datetime(2026, 10, 6, 22, 5, tzinfo=UTC)
    transport = Transport([UrllibHttpResponse(200, xml.encode())])

    observation = HamQslSolarCollector(transport=transport).fetch(collected)

    assert observation.source_url == HAMQSL_SOLAR_URL
    assert observation.source_updated == fields["updated"]
    assert observation.solarwind == "410.2"
    assert observation.raw_xml == xml
    assert observation.collected_at_utc == collected


def test_kc2g_linestring_exact_on_contour() -> None:
    estimate = estimate_kc2g_contours(
        _contours((10.0, [[0.0, -10.0], [0.0, 10.0]])),
        latitude=0.0,
        longitude=0.0,
    )

    assert estimate is not None
    assert estimate.value_mhz == 10.0
    assert estimate.method == "contour_idw_v1"
    assert estimate.nearest_contour_km == pytest.approx(0.0, abs=1e-6)
    assert estimate.levels_used == (10.0,)


def test_kc2g_interpolates_nearest_distinct_contour_levels() -> None:
    estimate = estimate_kc2g_contours(
        _contours(
            (10.0, [[-1.0, -10.0], [-1.0, 10.0]]),
            (10.0, [[-2.0, -10.0], [-2.0, 10.0]]),
            (20.0, [[1.0, -10.0], [1.0, 10.0]]),
        ),
        latitude=0.0,
        longitude=0.0,
    )

    assert estimate is not None
    assert estimate.value_mhz == pytest.approx(15.0)
    assert set(estimate.levels_used) == {10.0, 20.0}


def test_kc2g_ignores_malformed_features_and_reports_no_contours() -> None:
    malformed = {
        "type": "FeatureCollection",
        "features": [
            _feature(True, "LineString", [[0.0, 0.0], [1.0, 1.0]]),
            _feature(7.0, "LineString", [[0.0, 0.0], [float("nan"), 1.0]]),
            _feature(8.0, "Point", [0.0, 0.0]),
        ],
    }

    assert Kc2gContourEstimator.from_geojson(malformed) is None
    assert estimate_kc2g_contours(malformed, latitude=0.0, longitude=0.0) is None


def test_kc2g_multilinestring_is_supported() -> None:
    geojson = {
        "type": "FeatureCollection",
        "features": [
            _feature(
                7.25,
                "MultiLineString",
                [
                    [[-20.0, -5.0], [-20.0, 5.0]],
                    [[30.0, -5.0], [30.0, 5.0]],
                ],
            )
        ],
    }

    estimate = estimate_kc2g_contours(geojson, latitude=0.0, longitude=30.0)

    assert estimate is not None and estimate.value_mhz == 7.25


def test_kc2g_segment_distance_handles_antimeridian() -> None:
    estimate = estimate_kc2g_contours(
        _contours((11.0, [[179.0, 0.0], [-179.0, 0.0]])),
        latitude=0.0,
        longitude=180.0,
    )

    assert estimate is not None
    assert estimate.value_mhz == 11.0
    assert estimate.nearest_contour_km == pytest.approx(0.0, abs=1e-6)


def test_great_circle_sampling_includes_endpoints_spacing_and_cap() -> None:
    samples = sample_great_circle_path((0.0, 170.0), (0.0, -170.0))

    assert samples[0] == (0.0, 170.0)
    assert samples[-1] == (0.0, -170.0)
    assert max(_distance_km(a, b) for a, b in pairwise(samples)) <= 100.0

    capped = sample_great_circle_path(
        (0.0, 0.0), (0.0, 180.0), max_spacing_km=0.001
    )
    assert len(capped) == 512
    assert capped[0] == (0.0, 0.0)
    assert capped[-1] == (0.0, 180.0)
    assert max(_distance_km(a, b) for a, b in pairwise(capped)) <= 100.0


def test_repository_uses_dedicated_tables_and_compresses_complete_snapshot(tmp_path: Path) -> None:
    database = tmp_path / "propagation.db"
    repository = ForgePropagationHistoryRepository(database)
    snapshot = Kc2gSnapshot(
        metric=IonosphereMetric.FOF2,
        source_url="https://prop.kc2g.com/test.geojson",
        collected_at_utc=datetime(2026, 10, 6, 22, tzinfo=UTC),
        geojson={"type": "FeatureCollection", "features": []},
    )
    repository.add_kc2g(snapshot)

    assert {
        "solar_observation", "kc2g_snapshot", "weather_observation",
        "qso_observation", "qso_ionosphere", "qso_voacap_prediction",
        "pskreporter_query", "qso_pskreporter_summary",
    } <= repository.table_names()
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT compression, length(snapshot_blob) FROM kc2g_snapshot"
        ).fetchone()
    assert row is not None and row[0] == "gzip" and row[1] > 0


def test_voacap_uses_full_grid_actual_power_ft8_mode_and_actual_hour() -> None:
    version = UrllibHttpResponse(200, dumps({"version": "2.4.1"}).encode())
    summary = UrllibHttpResponse(
        200,
        dumps({
            "analysis": {"best_band_by_hour": [{
                "hour_utc": 22, "muf_mhz": 18.2, "band_m": 20,
                "reliability": 0.83, "rating": "good", "snr_db": -7.5,
            }]}
        }).encode(),
    )
    transport = Transport([version, summary])
    contact = Contact(
        callsign="KC1OXG", frequency_hz=14_074_000, mode=RadioMode.FT8,
        started_at=datetime(2026, 10, 6, 22, 1, tzinfo=UTC), rst_sent="-10",
        rst_received="-12", grid="FN31pr", my_grid="EM79xp",
        source=ContactSource.FT8, tx_power_watts=55,
    )

    prediction = VoacapSummaryClient(
        transport=transport,
        clock=lambda: datetime(2026, 10, 6, 22, 10, tzinfo=UTC),
    ).predict(contact)

    assert prediction is not None
    assert prediction.request_json["tx_grid"] == "EM79xp"
    assert prediction.request_json["power_watts"] == 55
    assert prediction.request_json["mode"] == "FT8"
    assert prediction.actual_hour_muf_mhz == 18.2
    assert prediction.actual_hour_reliability == 0.83
    assert prediction.actual_hour_rating == "good"
    assert prediction.actual_hour_snr_db == -7.5


def test_pskreporter_defaults_enforce_provider_etiquette() -> None:
    assert PskReporterConfig().minimum_query_interval_s == 300
    assert PskReporterConfig().report_latency_s == 300
    assert PskReporterConfig(enabled=True).enabled


def test_qso_enrichment_controls_default_disabled() -> None:
    config = ForgePropagationHistoryConfig()

    assert config.voacap_enabled is False
    assert config.weather_enrichment_enabled is False
    assert config.pskreporter.enabled is False


def test_propagation_example_keeps_qso_enrichment_disabled() -> None:
    config = load_forge_propagation_config(PROPAGATION_EXAMPLE)

    assert config.voacap_enabled is False
    assert config.weather_enrichment_enabled is False
    assert config.pskreporter.enabled is False


def test_check_config_is_database_and_provider_free(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    database = tmp_path / "must-not-be-created.sqlite3"
    config = tmp_path / "propagation.yaml"
    config.write_text(
        f"enabled: false\ndatabase_path: {database}\n",
        encoding="utf-8",
    )

    result = propagation_main(["--config", str(config), "--check-config"])

    assert result == 0
    assert not database.exists()
    payload = loads(capsys.readouterr().out)
    assert payload["enabled"] is False
    assert payload["database_path"] == str(database)
    assert payload["qso_enrichment"] == {
        "pskreporter_enabled": False,
        "voacap_enabled": False,
        "weather_enrichment_enabled": False,
    }
    assert payload["providers"] == [
        "https://www.hamqsl.com/solarxml.php",
        "https://prop.kc2g.com/renders/current/mufd-normal-now.geojson",
        "https://prop.kc2g.com/renders/current/fof2-normal-now.geojson",
    ]


def test_hourly_collection_is_independent_durable_and_backed_off(tmp_path: Path) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "collection.db")
    solar = _CollectionSolar(failures=1)
    kc2g = _CollectionKc2g()
    service = ForgePropagationHistoryService(
        repository,
        solar,  # type: ignore[arg-type]
        kc2g,  # type: ignore[arg-type]
        _NoPredictionClient(),
        retry_initial_backoff=timedelta(hours=1),
        retry_maximum_backoff=timedelta(hours=2),
    )
    first = datetime(2026, 10, 7, 1, tzinfo=UTC)

    assert service.collect_due(first) == {
        "solar": "failed:fixture failure",
        "mufd": "collected",
        "fof2": "collected",
    }
    assert service.collect_due(first + timedelta(minutes=59)) == {
        "solar": "not_due",
        "mufd": "not_due",
        "fof2": "not_due",
    }

    second = first + timedelta(hours=1)
    assert service.collect_due(second) == {
        "solar": "collected",
        "mufd": "collected",
        "fof2": "collected",
    }
    health = service.get_health(second)
    assert health.state == "healthy"
    assert {item.provider for item in health.providers} == {
        PropagationCollectionProvider.SOLAR,
        PropagationCollectionProvider.MUF_3000,
        PropagationCollectionProvider.FOF2,
    }
    assert all(item.state == "healthy" for item in health.providers)
    assert solar.calls == 2
    assert kc2g.calls == [IonosphereMetric.MUF_3000, IonosphereMetric.FOF2] * 2


def test_supervised_runtime_collects_immediately_then_honors_stop_waiter(
    tmp_path: Path,
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "runtime.db")
    solar = _CollectionSolar()
    kc2g = _CollectionKc2g()
    service = ForgePropagationHistoryService(
        repository,
        solar,  # type: ignore[arg-type]
        kc2g,  # type: ignore[arg-type]
        _NoPredictionClient(),
    )
    now = datetime(2026, 10, 7, 1, tzinfo=UTC)
    waits: list[float] = []

    def stop_after_first_cycle(interval_s: float) -> bool:
        waits.append(interval_s)
        return True

    runtime = ForgePropagationCollectionRuntime(
        service,
        check_interval_s=15.0,
        clock=lambda: now,
        waiter=stop_after_first_cycle,
    )

    runtime.run_forever()

    assert waits == [15.0]
    assert solar.calls == 1
    assert kc2g.calls == [IonosphereMetric.MUF_3000, IonosphereMetric.FOF2]
    assert runtime.is_running is False
    assert runtime.get_health().running is False


def test_service_stores_path_minimum_and_prefers_frozen_coordinates(
    tmp_path: Path,
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "history.db")
    qso_time = datetime(2026, 10, 7, 1, tzinfo=UTC)
    repository.add_kc2g(
        _snapshot(
            IonosphereMetric.MUF_3000,
            qso_time,
            _contours(
                (10.0, [[0.0, -10.0], [0.0, 10.0]]),
                (5.0, [[5.0, -10.0], [5.0, 10.0]]),
                (20.0, [[10.0, -10.0], [10.0, 10.0]]),
            ),
        )
    )
    repository.add_kc2g(
        _snapshot(
            IonosphereMetric.FOF2,
            qso_time,
            _contours(
                (3.0, [[0.0, -10.0], [0.0, 10.0]]),
                (7.0, [[10.0, -10.0], [10.0, 10.0]]),
            ),
        )
    )
    contact = _contact(
        qso_time,
        my_latitude=0.0,
        my_longitude=0.0,
        contact_latitude=0.0,
        contact_longitude=10.0,
    )

    result = _service(repository).correlate_contact(contact)
    stored = repository.read_ionosphere(contact.contact_id)

    assert result.ionosphere == "stored"
    assert stored is not None
    assert stored.muf_snapshot_at_utc == qso_time
    assert stored.fof2_snapshot_at_utc == qso_time
    assert stored.payload_json["local_muf3000_mhz"] == 10.0
    assert stored.payload_json["remote_muf3000_mhz"] == 20.0
    assert stored.payload_json["path_min_muf3000_mhz"] == 5.0
    assert stored.payload_json["local_fof2_mhz"] == 3.0
    assert stored.payload_json["remote_fof2_mhz"] == 7.0
    assert stored.payload_json["path_sample_count"] > 2
    assert stored.payload_json["coordinate_source"] == {
        "local": "my_latitude/my_longitude",
        "remote": "contact_latitude/contact_longitude",
    }
    assert stored.payload_json["estimator_version"] == "contour_idw_v1"
    assert stored.payload_json["estimator_audit"]["path_min_muf3000"][
        "levels_used"
    ] == [5.0]


def test_service_uses_grid_centers_and_stores_partial_metric(tmp_path: Path) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "partial.db")
    qso_time = datetime(2026, 10, 7, 1, tzinfo=UTC)
    repository.add_kc2g(
        _snapshot(
            IonosphereMetric.MUF_3000,
            qso_time,
            _contours((12.0, [[-180.0, 0.0], [180.0, 0.0]])),
        )
    )
    contact = _contact(qso_time)

    result = _service(repository).correlate_contact(contact)
    stored = repository.read_ionosphere(contact.contact_id)

    assert result.ionosphere == "stored"
    assert stored is not None
    assert stored.fof2_snapshot_at_utc is None
    assert stored.payload_json["local_fof2_mhz"] is None
    assert stored.payload_json["remote_fof2_mhz"] is None
    assert stored.payload_json["coordinate_source"] == {
        "local": "my_grid6_center",
        "remote": "contact_grid_center",
    }


def test_service_reports_ionosphere_unavailable_for_missing_endpoint(
    tmp_path: Path,
) -> None:
    repository = ForgePropagationHistoryRepository(tmp_path / "missing.db")
    contact = Contact(
        callsign="KC1OXG",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=datetime(2026, 10, 7, 1, tzinfo=UTC),
        rst_sent="-10",
        rst_received="-12",
        my_grid="EM79xp",
        source=ContactSource.FT8,
    )

    result = _service(repository).correlate_contact(contact)

    assert result.qso == "stored"
    assert result.ionosphere == "unavailable"
    assert repository.read_ionosphere(contact.contact_id) is None


def test_service_correlation_steps_and_weather_endpoints_are_failure_isolated() -> None:
    repository = _FailingRepository()
    contact = _contact(datetime(2026, 10, 7, 1, tzinfo=UTC))
    service = ForgePropagationHistoryService(
        repository,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        _PredictionClient(contact),
        weather_provider=_WeatherProvider(),
    )

    result = service.correlate_contact(contact)

    assert result.qso.startswith("failed:")
    assert result.voacap == "stored"
    assert result.ionosphere == "unavailable"
    assert result.local_weather.startswith("failed:")
    assert result.contact_weather == "stored"
    assert repository.voacap_saved
    assert repository.weather_roles == ["contact"]


def _feature(level: object, geometry_type: str, coordinates: object) -> dict[str, Any]:
    return {
        "type": "Feature",
        "properties": {"level-value": level},
        "geometry": {"type": geometry_type, "coordinates": coordinates},
    }


def _contours(*items: tuple[float, object]) -> dict[str, Any]:
    return {
        "type": "FeatureCollection",
        "features": [_feature(level, "LineString", coordinates) for level, coordinates in items],
    }


def _snapshot(
    metric: IonosphereMetric, collected_at: datetime, geojson: dict[str, Any]
) -> Kc2gSnapshot:
    return Kc2gSnapshot(
        metric=metric,
        source_url=f"https://prop.kc2g.com/{metric.value}.geojson",
        collected_at_utc=collected_at,
        geojson=geojson,
    )


def _contact(qso_time: datetime, **coordinates: float) -> Contact:
    return Contact(
        callsign="KC1OXG",
        frequency_hz=14_074_000,
        mode=RadioMode.FT8,
        started_at=qso_time,
        rst_sent="-10",
        rst_received="-12",
        grid="JJ00aa",
        my_grid="JJ00aa",
        source=ContactSource.FT8,
        **coordinates,
    )


class _NoPredictionClient:
    def predict(self, contact: Contact) -> None:
        del contact


def _service(repository: ForgePropagationHistoryRepository) -> ForgePropagationHistoryService:
    return ForgePropagationHistoryService(
        repository,
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        _NoPredictionClient(),
    )


def _distance_km(start: tuple[float, float], end: tuple[float, float]) -> float:
    latitude_delta = radians(end[0] - start[0])
    longitude_delta = radians(end[1] - start[1])
    value = (
        sin(latitude_delta / 2.0) ** 2
        + cos(radians(start[0]))
        * cos(radians(end[0]))
        * sin(longitude_delta / 2.0) ** 2
    )
    return 2.0 * 6_371.0088 * asin(min(1.0, sqrt(value)))


class _PredictionClient:
    def __init__(self, contact: Contact) -> None:
        self._contact = contact

    def predict(self, contact: Contact) -> VoacapPrediction:
        assert contact is self._contact
        return VoacapPrediction(
            contact_id=contact.contact_id,
            captured_at_utc=contact.started_at,
            request_json={"fixture": True},
            service_version="test",
            response_json={"status": "ok"},
        )


class _WeatherProvider:
    def fetch_weather(self, location) -> WeatherSnapshot:  # type: ignore[no-untyped-def]
        observed = location.fix_at.astimezone(UTC)
        return WeatherSnapshot(
            latitude=location.latitude,
            longitude=location.longitude,
            source_at=observed,
            fetched_at=observed,
            current=WeatherCurrent(
                temperature_c=20.0,
                relative_humidity_percent=50.0,
                condition=WeatherConditionToken.CLEAR,
                icon=WeatherIconToken.CLEAR_DAY,
                is_day=True,
            ),
            hourly=tuple(
                WeatherHourlyPoint(
                    forecast_at=observed + timedelta(hours=index),
                    temperature_c=20.0,
                    precipitation_probability_percent=0.0,
                )
                for index in range(1, 4)
            ),
            solar=WeatherSolar(
                sunrise_at=observed - timedelta(hours=1),
                sunset_at=observed + timedelta(hours=1),
            ),
            source=WeatherSourceMetadata(
                provider_id="fixture",
                provider_name="Fixture",
                attribution_text="Fixture weather",
                attribution_url="https://example.test/weather",
                license_name="Fixture",
                license_url="https://example.test/license",
            ),
        )


class _FailingRepository:
    def __init__(self) -> None:
        self.voacap_saved = False
        self.weather_roles: list[str] = []

    def add_qso(self, contact: Contact) -> None:
        del contact
        raise PropagationHistoryStorageError("qso unavailable")

    def save_voacap(self, prediction: VoacapPrediction) -> None:
        del prediction
        self.voacap_saved = True

    def nearest_kc2g_snapshot(
        self, metric: IonosphereMetric, qso_time: datetime
    ) -> None:
        del metric, qso_time

    def save_weather(self, observation) -> None:  # type: ignore[no-untyped-def]
        if observation.role.value == "local":
            raise PropagationHistoryStorageError("local weather unavailable")
        self.weather_roles.append(observation.role.value)
