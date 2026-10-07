"""Bounded provider adapters for Forge propagation-history collection."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from json import JSONDecodeError, dumps, loads
from math import acos, asin, atan2, ceil, cos, isfinite, radians, sin, sqrt
from typing import Any, Literal, Protocol
from urllib.error import URLError
from urllib.parse import urlparse
from xml.etree import ElementTree

from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_propagation_history import (
    ForgePropagationHistoryRepository,
    IonosphereCorrelation,
    IonosphereMetric,
    Kc2gSnapshot,
    SolarObservation,
    VoacapPrediction,
    WeatherObservation,
    WeatherObservationRole,
)
from rolling_thunder.forge_weather import WeatherProvider
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.maidenhead import maidenhead_grid_center
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band

HAMQSL_SOLAR_URL = "https://www.hamqsl.com/solarxml.php"
KC2G_MUFD_URL = "https://prop.kc2g.com/renders/current/mufd-normal-now.geojson"
KC2G_FOF2_URL = "https://prop.kc2g.com/renders/current/fof2-normal-now.geojson"
_HAMQSL_MAX_RESPONSE_BYTES = 262_144
_KC2G_MAX_RESPONSE_BYTES = 2_097_152
_VOACAP_MAX_RESPONSE_BYTES = 1_048_576
_EARTH_RADIUS_KM = 6_371.0088
_ON_CONTOUR_TOLERANCE_KM = 1e-6
_MAX_PATH_SAMPLES = 512
_SOLAR_FIELDS = (
    "solarflux", "aindex", "kindex", "xray", "sunspots", "protonflux",
    "aurora", "normalization", "latdegree", "solarwind", "magneticfield",
    "geomagfield", "signalnoise",
)


class PropagationProviderError(OSError):
    """A propagation provider was unavailable or returned invalid data."""


class VersionedVoacapClient(Protocol):
    def predict(self, contact: Contact) -> VoacapPrediction | None: ...


@dataclass(frozen=True, slots=True)
class Kc2gContourEstimate:
    """One auditable value derived from KC2G contour geometry."""

    value_mhz: float
    method: Literal["contour_idw_v1"] = "contour_idw_v1"
    nearest_contour_km: float = 0.0
    levels_used: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class PropagationCorrelationResult:
    qso: str
    voacap: str
    ionosphere: str
    local_weather: str
    contact_weather: str


@dataclass(frozen=True, slots=True)
class _Coordinates:
    latitude: float
    longitude: float
    source: str


class Kc2gContourEstimator:
    """Parse KC2G contours once and estimate points by distinct contour level."""

    def __init__(
        self,
        segments_by_level: Mapping[
            float, tuple[tuple[tuple[float, float], tuple[float, float]], ...]
        ],
    ) -> None:
        self._segments_by_level = dict(segments_by_level)

    @classmethod
    def from_geojson(cls, geojson: Mapping[str, Any]) -> Kc2gContourEstimator | None:
        features = geojson.get("features")
        if geojson.get("type") != "FeatureCollection" or not isinstance(features, list):
            return None
        collected: dict[
            float, list[tuple[tuple[float, float], tuple[float, float]]]
        ] = {}
        for feature in features:
            parsed = _parse_contour_feature(feature)
            if parsed is None:
                continue
            level, segments = parsed
            collected.setdefault(level, []).extend(segments)
        if not collected:
            return None
        return cls({level: tuple(segments) for level, segments in collected.items()})

    def estimate(self, *, latitude: float, longitude: float) -> Kc2gContourEstimate:
        _validate_coordinates(latitude, longitude)
        distances = sorted(
            (
                min(
                    _point_to_geodesic_segment_km(
                        (latitude, longitude), start, end
                    )
                    for start, end in segments
                ),
                level,
            )
            for level, segments in self._segments_by_level.items()
        )
        nearest_distance, nearest_level = distances[0]
        if nearest_distance <= _ON_CONTOUR_TOLERANCE_KM:
            return Kc2gContourEstimate(
                value_mhz=nearest_level,
                nearest_contour_km=nearest_distance,
                levels_used=(nearest_level,),
            )
        selected = distances[:4]
        if len(selected) == 1:
            return Kc2gContourEstimate(
                value_mhz=nearest_level,
                nearest_contour_km=nearest_distance,
                levels_used=(nearest_level,),
            )
        weighted_sum = 0.0
        weight_total = 0.0
        for distance_km, level in selected:
            weight = 1.0 / (distance_km * distance_km)
            weighted_sum += level * weight
            weight_total += weight
        levels = tuple(level for _, level in selected)
        value = weighted_sum / weight_total
        return Kc2gContourEstimate(
            value_mhz=min(max(value, min(levels)), max(levels)),
            nearest_contour_km=nearest_distance,
            levels_used=levels,
        )


def estimate_kc2g_contours(
    geojson: Mapping[str, Any], *, latitude: float, longitude: float
) -> Kc2gContourEstimate | None:
    """Estimate a KC2G value, or report unavailable when no contours are usable."""
    estimator = Kc2gContourEstimator.from_geojson(geojson)
    if estimator is None:
        return None
    return estimator.estimate(latitude=latitude, longitude=longitude)


def sample_great_circle_path(
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    max_spacing_km: float = 100.0,
) -> tuple[tuple[float, float], ...]:
    """Sample the shorter great-circle arc, including both exact endpoints."""
    _validate_coordinates(*start)
    _validate_coordinates(*end)
    if not isfinite(max_spacing_km) or max_spacing_km <= 0.0:
        raise ValueError("max_spacing_km must be finite and positive")
    distance_km = _great_circle_distance_km(start, end)
    if distance_km == 0.0:
        return (start,)
    requested_spacing = min(max_spacing_km, 100.0)
    segment_count = min(ceil(distance_km / requested_spacing), _MAX_PATH_SAMPLES - 1)
    angular_distance = distance_km / _EARTH_RADIUS_KM
    bearing = _initial_bearing_radians(start, end)
    samples = [start]
    for index in range(1, segment_count):
        samples.append(
            _destination_point(start, bearing, angular_distance * index / segment_count)
        )
    samples.append(end)
    return tuple(samples)


class HamQslSolarCollector:
    def __init__(self, *, transport: HttpTransport | None = None, timeout_s: float = 5.0) -> None:
        self._transport = transport or UrllibHttpTransport()
        self._timeout_s = timeout_s

    def fetch(self, collected_at_utc: datetime) -> SolarObservation:
        body = _get(
            self._transport,
            HAMQSL_SOLAR_URL,
            self._timeout_s,
            _HAMQSL_MAX_RESPONSE_BYTES,
        )
        try:
            raw_xml = body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise PropagationProviderError("HamQSL returned invalid XML") from error
        try:
            root = ElementTree.fromstring(raw_xml)
        except ElementTree.ParseError as error:
            raise PropagationProviderError("HamQSL returned invalid XML") from error
        values = {name: _required_xml_text(root, name) for name in _SOLAR_FIELDS}
        return SolarObservation(
            source_url=HAMQSL_SOLAR_URL,
            source_updated=_required_xml_text(root, "updated"),
            collected_at_utc=collected_at_utc,
            raw_xml=raw_xml,
            **values,
        )


class Kc2gGeoJsonCollector:
    def __init__(self, *, transport: HttpTransport | None = None, timeout_s: float = 10.0) -> None:
        self._transport = transport or UrllibHttpTransport()
        self._timeout_s = timeout_s

    def fetch(self, metric: IonosphereMetric, collected_at_utc: datetime) -> Kc2gSnapshot:
        source_url = KC2G_MUFD_URL if metric is IonosphereMetric.MUF_3000 else KC2G_FOF2_URL
        body = _get(self._transport, source_url, self._timeout_s, _KC2G_MAX_RESPONSE_BYTES)
        try:
            value = loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise PropagationProviderError("KC2G returned invalid GeoJSON") from error
        if (
            not isinstance(value, dict)
            or value.get("type") != "FeatureCollection"
            or not isinstance(value.get("features"), list)
        ):
            raise PropagationProviderError("KC2G GeoJSON must be a FeatureCollection")
        return Kc2gSnapshot(
            metric=metric,
            source_url=source_url,
            collected_at_utc=collected_at_utc,
            geojson=value,
        )


class VoacapSummaryClient:
    """Client for the existing VOACAP service; it does not implement propagation."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8787",
        *,
        transport: HttpTransport | None = None,
        timeout_s: float = 5.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        normalized = base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("VOACAP base URL must be absolute HTTP(S)")
        self._base_url = normalized
        self._transport = transport or UrllibHttpTransport()
        self._timeout_s = timeout_s
        self._clock = clock

    def predict(self, contact: Contact) -> VoacapPrediction | None:
        if contact.my_grid6 is None or contact.grid is None or contact.tx_power_watts is None:
            return None
        mode = _voacap_mode(contact.mode)
        if mode is None:
            return None
        try:
            band = resolve_radio_band(Frequency(hz=contact.frequency_hz)).value
        except RadioBandResolutionError:
            return None
        band_m = int(band.removesuffix("m"))
        started_at_utc = contact.started_at.astimezone(UTC)
        request_json: dict[str, Any] = {
            "tx_grid": str(contact.my_grid6),
            "rx_grid": str(contact.grid),
            "year": started_at_utc.year,
            "month": started_at_utc.month,
            "bands_m": [band_m],
            "power_watts": contact.tx_power_watts,
            "mode": mode,
            "timezone": "UTC",
        }
        version = self._json_request("GET", "/version", None)
        response = self._json_request("POST", "/api/v1/summary", request_json)
        service_version = _version_text(version)
        entry = _actual_hour_entry(response, hour_utc=started_at_utc.hour, band_m=band_m)
        return VoacapPrediction(
            contact_id=contact.contact_id,
            captured_at_utc=self._clock(),
            request_json=request_json,
            service_version=service_version,
            response_json=response,
            actual_hour_muf_mhz=_optional_number(entry, "muf_mhz"),
            actual_hour_reliability=_optional_number(entry, "reliability"),
            actual_hour_rating=_optional_text(entry, "rating"),
            actual_hour_snr_db=_optional_number(entry, "snr_db"),
        )

    def _json_request(self, method: str, path: str, payload: dict[str, Any] | None) -> dict[str, Any]:
        body = None if payload is None else dumps(payload, separators=(",", ":")).encode()
        try:
            response = self._transport.request(
                method, f"{self._base_url}{path}",
                headers={"Accept": "application/json", "Content-Type": "application/json"},
                body=body, timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise PropagationProviderError("VOACAP service unavailable") from error
        if not 200 <= response.status_code < 300:
            raise PropagationProviderError(f"VOACAP returned HTTP {response.status_code}")
        if len(response.body) > _VOACAP_MAX_RESPONSE_BYTES:
            raise PropagationProviderError("VOACAP response exceeded maximum size")
        try:
            value = loads(response.body.decode())
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise PropagationProviderError("VOACAP returned invalid JSON") from error
        if not isinstance(value, dict):
            raise PropagationProviderError("VOACAP JSON must be an object")
        return value


class ForgePropagationHistoryService:
    """Run bounded collectors/correlation outside contact synchronization."""

    def __init__(
        self,
        repository: ForgePropagationHistoryRepository,
        solar: HamQslSolarCollector,
        kc2g: Kc2gGeoJsonCollector,
        voacap: VersionedVoacapClient,
        *,
        weather_provider: WeatherProvider | None = None,
        minimum_collection_interval: timedelta = timedelta(hours=1),
    ) -> None:
        self._repository = repository
        self._solar = solar
        self._kc2g = kc2g
        self._voacap = voacap
        self._weather_provider = weather_provider
        self._minimum = minimum_collection_interval

    def collect_due(self, now: datetime) -> dict[str, str]:
        """Collect each hourly source independently; one failure never suppresses another."""
        results: dict[str, str] = {}
        jobs = (
            ("solar", None),
            (IonosphereMetric.MUF_3000.value, IonosphereMetric.MUF_3000),
            (IonosphereMetric.FOF2.value, IonosphereMetric.FOF2),
        )
        for name, metric in jobs:
            table = "solar_observation" if metric is None else "kc2g_snapshot"
            latest = self._repository.latest_collection_time(table, metric=metric)
            if latest is not None and now.astimezone(UTC) - latest < self._minimum:
                results[name] = "not_due"
                continue
            try:
                if metric is None:
                    self._repository.add_solar(self._solar.fetch(now))
                else:
                    self._repository.add_kc2g(self._kc2g.fetch(metric, now))
            except Exception as error:  # noqa: BLE001 - provider jobs are failure-isolated
                results[name] = f"failed:{(str(error) or error.__class__.__name__)[:200]}"
            else:
                results[name] = "collected"
        return results

    def correlate_contact(self, contact: Contact) -> PropagationCorrelationResult:
        """Persist a QSO and independently enrich it with propagation analytics."""
        try:
            self._repository.add_qso(contact)
        except Exception as error:  # noqa: BLE001 - correlation jobs are isolated
            qso = f"failed:{_bounded_error(error)}"
        else:
            qso = "stored"

        try:
            prediction = self._voacap.predict(contact)
            if prediction is None:
                voacap = "skipped"
            else:
                self._repository.save_voacap(prediction)
                voacap = "stored"
        except Exception as error:  # noqa: BLE001 - correlation jobs are isolated
            voacap = f"failed:{_bounded_error(error)}"

        try:
            ionosphere = self._store_ionosphere(contact)
        except Exception as error:  # noqa: BLE001 - correlation jobs are isolated
            ionosphere = f"failed:{_bounded_error(error)}"

        if self._weather_provider is None:
            local_weather = "disabled"
            contact_weather = "disabled"
        else:
            local_weather = self._store_weather(
                contact,
                WeatherObservationRole.LOCAL,
                _local_coordinates(contact),
            )
            contact_weather = self._store_weather(
                contact,
                WeatherObservationRole.CONTACT,
                _contact_coordinates(contact),
            )
        return PropagationCorrelationResult(
            qso=qso,
            voacap=voacap,
            ionosphere=ionosphere,
            local_weather=local_weather,
            contact_weather=contact_weather,
        )

    def _store_ionosphere(self, contact: Contact) -> str:
        local = _local_coordinate_details(contact)
        remote = _contact_coordinate_details(contact)
        if local is None or remote is None:
            return "unavailable"

        muf_snapshot = self._repository.nearest_kc2g_snapshot(
            IonosphereMetric.MUF_3000, contact.started_at
        )
        fof2_snapshot = self._repository.nearest_kc2g_snapshot(
            IonosphereMetric.FOF2, contact.started_at
        )
        if muf_snapshot is None and fof2_snapshot is None:
            return "unavailable"

        local_muf: Kc2gContourEstimate | None = None
        remote_muf: Kc2gContourEstimate | None = None
        path_minimum: Kc2gContourEstimate | None = None
        path_samples: tuple[tuple[float, float], ...] = ()
        if muf_snapshot is not None:
            muf_estimator = Kc2gContourEstimator.from_geojson(muf_snapshot.geojson)
            if muf_estimator is not None:
                local_muf = muf_estimator.estimate(
                    latitude=local.latitude, longitude=local.longitude
                )
                remote_muf = muf_estimator.estimate(
                    latitude=remote.latitude, longitude=remote.longitude
                )
                path_samples = sample_great_circle_path(
                    (local.latitude, local.longitude),
                    (remote.latitude, remote.longitude),
                )
                path_estimates = tuple(
                    muf_estimator.estimate(latitude=latitude, longitude=longitude)
                    for latitude, longitude in path_samples
                )
                path_minimum = min(path_estimates, key=lambda estimate: estimate.value_mhz)

        local_fof2: Kc2gContourEstimate | None = None
        remote_fof2: Kc2gContourEstimate | None = None
        if fof2_snapshot is not None:
            fof2_estimator = Kc2gContourEstimator.from_geojson(fof2_snapshot.geojson)
            if fof2_estimator is not None:
                local_fof2 = fof2_estimator.estimate(
                    latitude=local.latitude, longitude=local.longitude
                )
                remote_fof2 = fof2_estimator.estimate(
                    latitude=remote.latitude, longitude=remote.longitude
                )

        payload: dict[str, Any] = {
            "local_muf3000_mhz": _estimate_value(local_muf),
            "remote_muf3000_mhz": _estimate_value(remote_muf),
            "path_min_muf3000_mhz": _estimate_value(path_minimum),
            "local_fof2_mhz": _estimate_value(local_fof2),
            "remote_fof2_mhz": _estimate_value(remote_fof2),
            "path_sample_count": len(path_samples),
            "coordinate_source": {"local": local.source, "remote": remote.source},
            "local_coordinate_source": local.source,
            "remote_coordinate_source": remote.source,
            "estimator_version": "contour_idw_v1",
            "estimator_audit": {
                "local_muf3000": _estimate_audit(local_muf),
                "remote_muf3000": _estimate_audit(remote_muf),
                "path_min_muf3000": _estimate_audit(path_minimum),
                "local_fof2": _estimate_audit(local_fof2),
                "remote_fof2": _estimate_audit(remote_fof2),
            },
        }
        self._repository.save_ionosphere(
            IonosphereCorrelation(
                contact_id=contact.contact_id,
                captured_at_utc=datetime.now(UTC),
                muf_snapshot_at_utc=(
                    None if muf_snapshot is None else muf_snapshot.collected_at_utc
                ),
                fof2_snapshot_at_utc=(
                    None if fof2_snapshot is None else fof2_snapshot.collected_at_utc
                ),
                payload_json=payload,
            )
        )
        return "stored"

    def _store_weather(
        self,
        contact: Contact,
        role: WeatherObservationRole,
        coordinates: tuple[float, float] | None,
    ) -> str:
        if coordinates is None:
            return "unavailable"
        assert self._weather_provider is not None
        latitude, longitude = coordinates
        location = MobileLocationRecord(
            latitude=latitude,
            longitude=longitude,
            fix_at=contact.started_at,
            received_at=contact.started_at,
        )
        try:
            snapshot = self._weather_provider.fetch_weather(location)
            self._repository.save_weather(
                WeatherObservation(
                    contact_id=contact.contact_id,
                    role=role,
                    provider_id=snapshot.source.provider_id,
                    provider_name=snapshot.source.provider_name,
                    attribution_text=snapshot.source.attribution_text,
                    attribution_url=snapshot.source.attribution_url,
                    license_name=snapshot.source.license_name,
                    license_url=snapshot.source.license_url,
                    source_at_utc=snapshot.source_at,
                    fetched_at_utc=snapshot.fetched_at,
                    latitude=snapshot.latitude,
                    longitude=snapshot.longitude,
                    condition=snapshot.current.condition.value,
                    temperature_c=snapshot.current.temperature_c,
                    relative_humidity_percent=snapshot.current.relative_humidity_percent,
                    payload_json=snapshot.model_dump(mode="json"),
                )
            )
        except Exception as error:  # noqa: BLE001 - endpoint jobs are isolated
            return f"failed:{_bounded_error(error)}"
        return "stored"


def _bounded_error(error: BaseException) -> str:
    return (str(error) or error.__class__.__name__)[:200]


def _local_coordinates(contact: Contact) -> tuple[float, float] | None:
    details = _local_coordinate_details(contact)
    return None if details is None else (details.latitude, details.longitude)


def _contact_coordinates(contact: Contact) -> tuple[float, float] | None:
    details = _contact_coordinate_details(contact)
    return None if details is None else (details.latitude, details.longitude)


def _local_coordinate_details(contact: Contact) -> _Coordinates | None:
    if contact.my_latitude is not None and contact.my_longitude is not None:
        return _Coordinates(
            contact.my_latitude,
            contact.my_longitude,
            "my_latitude/my_longitude",
        )
    if contact.my_grid6 is not None:
        latitude, longitude = maidenhead_grid_center(contact.my_grid6)
        return _Coordinates(latitude, longitude, "my_grid6_center")
    return None


def _contact_coordinate_details(contact: Contact) -> _Coordinates | None:
    if contact.contact_latitude is not None and contact.contact_longitude is not None:
        return _Coordinates(
            contact.contact_latitude,
            contact.contact_longitude,
            "contact_latitude/contact_longitude",
        )
    if contact.grid is not None:
        latitude, longitude = maidenhead_grid_center(contact.grid)
        return _Coordinates(latitude, longitude, "contact_grid_center")
    return None


def _estimate_value(estimate: Kc2gContourEstimate | None) -> float | None:
    return None if estimate is None else estimate.value_mhz


def _estimate_audit(estimate: Kc2gContourEstimate | None) -> dict[str, Any] | None:
    if estimate is None:
        return None
    return {
        "method": estimate.method,
        "nearest_contour_km": estimate.nearest_contour_km,
        "levels_used": list(estimate.levels_used),
    }


def _parse_contour_feature(
    feature: object,
) -> tuple[
    float, tuple[tuple[tuple[float, float], tuple[float, float]], ...]
] | None:
    if not isinstance(feature, Mapping) or feature.get("type") != "Feature":
        return None
    properties = feature.get("properties")
    geometry = feature.get("geometry")
    if not isinstance(properties, Mapping) or not isinstance(geometry, Mapping):
        return None
    raw_level = properties.get("level-value")
    if (
        not isinstance(raw_level, (int, float))
        or isinstance(raw_level, bool)
        or not isfinite(raw_level)
    ):
        return None
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if geometry_type == "LineString":
        raw_lines = (coordinates,)
    elif geometry_type == "MultiLineString" and isinstance(coordinates, (list, tuple)):
        raw_lines = tuple(coordinates)
    else:
        return None
    if not raw_lines:
        return None
    segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for raw_line in raw_lines:
        line = _parse_contour_line(raw_line)
        if line is None:
            return None
        segments.extend(pairwise(line))
    if not segments:
        return None
    return float(raw_level), tuple(segments)


def _parse_contour_line(value: object) -> tuple[tuple[float, float], ...] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    points: list[tuple[float, float]] = []
    for coordinate in value:
        if not isinstance(coordinate, (list, tuple)) or len(coordinate) < 2:
            return None
        longitude, latitude = coordinate[:2]
        if (
            not isinstance(latitude, (int, float))
            or isinstance(latitude, bool)
            or not isinstance(longitude, (int, float))
            or isinstance(longitude, bool)
            or not isfinite(latitude)
            or not isfinite(longitude)
            or not -90.0 <= latitude <= 90.0
            or not -180.0 <= longitude <= 180.0
        ):
            return None
        points.append((float(latitude), float(longitude)))
    return tuple(points)


def _validate_coordinates(latitude: float, longitude: float) -> None:
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isfinite(latitude)
        or not isfinite(longitude)
        or not -90.0 <= latitude <= 90.0
        or not -180.0 <= longitude <= 180.0
    ):
        raise ValueError("latitude/longitude must be finite and in range")


def _unit_vector(point: tuple[float, float]) -> tuple[float, float, float]:
    latitude = radians(point[0])
    longitude = radians(point[1])
    latitude_cosine = cos(latitude)
    return (
        latitude_cosine * cos(longitude),
        latitude_cosine * sin(longitude),
        sin(latitude),
    )


def _dot(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    return sum(a * b for a, b in zip(first, second, strict=True))


def _cross(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> tuple[float, float, float]:
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _norm(vector: tuple[float, float, float]) -> float:
    return sqrt(_dot(vector, vector))


def _angular_distance_vectors(
    first: tuple[float, float, float], second: tuple[float, float, float]
) -> float:
    return acos(min(1.0, max(-1.0, _dot(first, second))))


def _point_to_geodesic_segment_km(
    point: tuple[float, float],
    start: tuple[float, float],
    end: tuple[float, float],
) -> float:
    """Return spherical distance to the bounded shorter great-circle segment."""
    query_vector = _unit_vector(point)
    start_vector = _unit_vector(start)
    end_vector = _unit_vector(end)
    segment_angle = _angular_distance_vectors(start_vector, end_vector)
    endpoint_distance = min(
        _angular_distance_vectors(query_vector, start_vector),
        _angular_distance_vectors(query_vector, end_vector),
    )
    normal = _cross(start_vector, end_vector)
    normal_squared = _dot(normal, normal)
    if segment_angle <= 1e-15 or normal_squared <= 1e-24:
        return endpoint_distance * _EARTH_RADIUS_KM
    projection_scale = _dot(query_vector, normal) / normal_squared
    projected = (
        query_vector[0] - normal[0] * projection_scale,
        query_vector[1] - normal[1] * projection_scale,
        query_vector[2] - normal[2] * projection_scale,
    )
    projected_norm = _norm(projected)
    if projected_norm <= 1e-15:
        return endpoint_distance * _EARTH_RADIUS_KM
    candidate = (
        projected[0] / projected_norm,
        projected[1] / projected_norm,
        projected[2] / projected_norm,
    )
    antipode = (-candidate[0], -candidate[1], -candidate[2])
    best = endpoint_distance
    for possible in (candidate, antipode):
        start_to_candidate = _angular_distance_vectors(start_vector, possible)
        candidate_to_end = _angular_distance_vectors(possible, end_vector)
        if start_to_candidate + candidate_to_end <= segment_angle + 1e-10:
            best = min(best, _angular_distance_vectors(query_vector, possible))
    return best * _EARTH_RADIUS_KM


def _great_circle_distance_km(
    start: tuple[float, float], end: tuple[float, float]
) -> float:
    latitude_delta = radians(end[0] - start[0])
    longitude_delta = radians(end[1] - start[1])
    start_latitude = radians(start[0])
    end_latitude = radians(end[0])
    haversine = (
        sin(latitude_delta / 2.0) ** 2
        + cos(start_latitude)
        * cos(end_latitude)
        * sin(longitude_delta / 2.0) ** 2
    )
    return 2.0 * _EARTH_RADIUS_KM * asin(min(1.0, sqrt(haversine)))


def _initial_bearing_radians(
    start: tuple[float, float], end: tuple[float, float]
) -> float:
    start_latitude = radians(start[0])
    end_latitude = radians(end[0])
    longitude_delta = radians(end[1] - start[1])
    return atan2(
        sin(longitude_delta) * cos(end_latitude),
        cos(start_latitude) * sin(end_latitude)
        - sin(start_latitude) * cos(end_latitude) * cos(longitude_delta),
    )


def _destination_point(
    start: tuple[float, float], bearing: float, angular_distance: float
) -> tuple[float, float]:
    latitude = radians(start[0])
    longitude = radians(start[1])
    destination_latitude = asin(
        min(
            1.0,
            max(
                -1.0,
                sin(latitude) * cos(angular_distance)
                + cos(latitude) * sin(angular_distance) * cos(bearing),
            ),
        )
    )
    destination_longitude = longitude + atan2(
        sin(bearing) * sin(angular_distance) * cos(latitude),
        cos(angular_distance) - sin(latitude) * sin(destination_latitude),
    )
    longitude_degrees = (
        destination_longitude * 180.0 / 3.141592653589793 + 540.0
    ) % 360.0 - 180.0
    return destination_latitude * 180.0 / 3.141592653589793, longitude_degrees


def _required_xml_text(root: ElementTree.Element, tag: str) -> str:
    element = root.find(f".//{tag}")
    if element is None or element.text is None or not element.text.strip():
        raise PropagationProviderError(f"HamQSL XML missing {tag}")
    return element.text.strip()


def _get(
    transport: HttpTransport,
    url: str,
    timeout_s: float,
    max_response_bytes: int,
) -> bytes:
    try:
        response = transport.request("GET", url, headers={"Accept": "*/*"}, body=None, timeout_s=timeout_s)
    except (TimeoutError, URLError, OSError) as error:
        raise PropagationProviderError(f"provider unavailable: {url}") from error
    if not 200 <= response.status_code < 300:
        raise PropagationProviderError(f"provider returned HTTP {response.status_code}: {url}")
    if len(response.body) > max_response_bytes:
        raise PropagationProviderError(f"provider response exceeded maximum size: {url}")
    return response.body


def _voacap_mode(mode: RadioMode) -> str | None:
    if mode is RadioMode.FT8:
        return "FT8"
    if mode in {RadioMode.USB, RadioMode.LSB}:
        return "SSB"
    if mode is RadioMode.CW:
        return "CW"
    return None


def _version_text(payload: Mapping[str, Any]) -> str:
    for key in ("version", "service_version"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown"


def _actual_hour_entry(response: Mapping[str, Any], *, hour_utc: int, band_m: int) -> Mapping[str, Any]:
    analysis = response.get("analysis")
    if not isinstance(analysis, Mapping):
        return {}
    entries = analysis.get("best_band_by_hour")
    if not isinstance(entries, list):
        return {}
    for entry in entries:
        if isinstance(entry, Mapping) and entry.get("hour_utc") == hour_utc and entry.get("band_m") == band_m:
            return entry
    return {}


def _optional_number(value: Mapping[str, Any], key: str) -> float | None:
    item = value.get(key)
    return float(item) if isinstance(item, (int, float)) and not isinstance(item, bool) else None


def _optional_text(value: Mapping[str, Any], key: str) -> str | None:
    item = value.get(key)
    return item.strip() if isinstance(item, str) and item.strip() else None
