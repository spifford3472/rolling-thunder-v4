"""geoBoundaries adapter for DX country and first-level subdivision outlines."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from json import JSONDecodeError, loads
from urllib.error import URLError

import pycountry  # type: ignore[import-untyped]

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.pota_enrichment import StateOutline
from rolling_thunder.pota_spots import ParkReference

_API_ROOT = "https://www.geoboundaries.org/api/current/gbOpen"
_JSON_ACCEPT = "application/geo+json,application/json"
_USER_AGENT = "RollingThunder/4.1 POTA mobile client"
_ATTRIBUTION = "geoBoundaries · CC BY 4.0"


class GeoBoundariesOutlineError(OSError):
    """Raised when a global administrative outline cannot be retrieved."""


class GeoBoundariesOutlineProvider:
    """Fetch a DX ADM1 outline, falling back to the containing country."""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        api_root: str = _API_ROOT,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("geoBoundaries outline timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._api_root = api_root.rstrip("/")

    def fetch_outline(self, park: ParkReference) -> StateOutline | None:
        """Return the containing ADM1 boundary or a country-level fallback."""
        country_alpha_2 = self._country_alpha_2(park)
        if country_alpha_2 is None or country_alpha_2 == "US":
            return None
        country = pycountry.countries.get(alpha_2=country_alpha_2)
        if country is None:
            return None
        country_alpha_3 = str(country.alpha_3)

        if park.latitude is not None and park.longitude is not None:
            try:
                outline = self._fetch_level(
                    country_alpha_3,
                    "ADM1",
                    park=park,
                    select_containing=True,
                )
            except GeoBoundariesOutlineError:
                outline = None
            if outline is not None:
                return outline

        return self._fetch_level(
            country_alpha_3,
            "ADM0",
            park=park,
            select_containing=False,
        )

    def _fetch_level(
        self,
        country_alpha_3: str,
        level: str,
        *,
        park: ParkReference,
        select_containing: bool,
    ) -> StateOutline | None:
        metadata_url = f"{self._api_root}/{country_alpha_3}/{level}/"
        metadata = self._request_json(metadata_url)
        if not isinstance(metadata, Mapping):
            raise GeoBoundariesOutlineError(
                "geoBoundaries metadata must be a JSON object."
            )
        geojson_url = metadata.get("simplifiedGeometryGeoJSON")
        if not isinstance(geojson_url, str) or not geojson_url.startswith("https://"):
            raise GeoBoundariesOutlineError(
                "geoBoundaries metadata did not provide simplified GeoJSON."
            )
        payload = self._request_json(geojson_url)
        return self._parse_feature_collection(
            payload,
            park=park,
            fallback_name=self._text(metadata.get("boundaryName")) or country_alpha_3,
            fallback_code=(park.location_code or country_alpha_3),
            select_containing=select_containing,
        )

    def _request_json(self, url: str) -> object:
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": _JSON_ACCEPT, "User-Agent": _USER_AGENT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise GeoBoundariesOutlineError(
                "geoBoundaries map data could not be reached."
            ) from error
        if not 200 <= response.status_code < 300:
            raise GeoBoundariesOutlineError(
                f"geoBoundaries map data returned HTTP {response.status_code}."
            )
        try:
            return loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise GeoBoundariesOutlineError(
                "geoBoundaries map data returned invalid JSON."
            ) from error

    @classmethod
    def _parse_feature_collection(
        cls,
        payload: object,
        *,
        park: ParkReference,
        fallback_name: str,
        fallback_code: str,
        select_containing: bool,
    ) -> StateOutline | None:
        if not isinstance(payload, Mapping):
            raise GeoBoundariesOutlineError(
                "geoBoundaries GeoJSON must be a JSON object."
            )
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            return None

        parsed: list[
            tuple[str, str, tuple[tuple[tuple[float, float], ...], ...]]
        ] = []
        for feature in features:
            if not isinstance(feature, Mapping):
                continue
            rings = cls._feature_rings(feature)
            if not rings:
                continue
            properties = feature.get("properties")
            name = fallback_name
            code = fallback_code
            if isinstance(properties, Mapping):
                name = (
                    cls._text(properties.get("shapeName"))
                    or cls._text(properties.get("name"))
                    or fallback_name
                )
                code = (
                    cls._text(properties.get("shapeISO"))
                    or cls._text(properties.get("shapeID"))
                    or fallback_code
                )
            parsed.append((name, code, rings))

        if not parsed:
            return None

        chosen = parsed[0]
        if select_containing:
            if park.latitude is None or park.longitude is None:
                return None
            containing = next(
                (
                    item
                    for item in parsed
                    if any(
                        cls._point_in_ring(
                            park.longitude,
                            park.latitude,
                            ring,
                        )
                        for ring in item[2]
                    )
                ),
                None,
            )
            if containing is None:
                return None
            chosen = containing

        name, code, rings = chosen
        return StateOutline(
            state_code=code,
            state_name=name,
            rings=rings,
            attribution=_ATTRIBUTION,
        )

    @classmethod
    def _feature_rings(
        cls,
        feature: Mapping[str, object],
    ) -> tuple[tuple[tuple[float, float], ...], ...]:
        geometry = feature.get("geometry")
        if not isinstance(geometry, Mapping):
            return ()
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list):
            return ()

        output: list[tuple[tuple[float, float], ...]] = []
        if geometry_type == "Polygon":
            cls._append_outer_ring(output, coordinates)
        elif geometry_type == "MultiPolygon":
            for polygon in coordinates:
                if isinstance(polygon, list):
                    cls._append_outer_ring(output, polygon)
        return tuple(output)

    @classmethod
    def _append_outer_ring(
        cls,
        output: list[tuple[tuple[float, float], ...]],
        polygon: Sequence[object],
    ) -> None:
        if not polygon or not isinstance(polygon[0], list):
            return
        points: list[tuple[float, float]] = []
        for coordinate in polygon[0]:
            point = cls._point(coordinate)
            if point is not None and (not points or points[-1] != point):
                points.append(point)
        if len(points) >= 3:
            output.append(tuple(points))

    @staticmethod
    def _point(value: object) -> tuple[float, float] | None:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            return None
        if len(value) < 2:
            return None
        longitude, latitude = value[0], value[1]
        if isinstance(longitude, bool) or isinstance(latitude, bool):
            return None
        if not isinstance(longitude, (int, float)) or not isinstance(
            latitude, (int, float)
        ):
            return None
        return float(longitude), float(latitude)

    @staticmethod
    def _point_in_ring(
        longitude: float,
        latitude: float,
        ring: Sequence[tuple[float, float]],
    ) -> bool:
        if len(ring) < 3:
            return False
        adjusted = [
            (GeoBoundariesOutlineProvider._near_longitude(x, longitude), y)
            for x, y in ring
        ]
        inside = False
        previous_x, previous_y = adjusted[-1]
        for current_x, current_y in adjusted:
            crosses = (current_y > latitude) != (previous_y > latitude)
            if crosses:
                denominator = previous_y - current_y
                if denominator != 0:
                    intersection_x = (
                        (previous_x - current_x)
                        * (latitude - current_y)
                        / denominator
                        + current_x
                    )
                    if longitude < intersection_x:
                        inside = not inside
            previous_x, previous_y = current_x, current_y
        return inside

    @staticmethod
    def _near_longitude(value: float, center: float) -> float:
        adjusted = value
        while adjusted - center > 180:
            adjusted -= 360
        while adjusted - center < -180:
            adjusted += 360
        return adjusted

    @staticmethod
    def _country_alpha_2(park: ParkReference) -> str | None:
        source = park.location_code or park.reference
        prefix = source.strip().upper().split("-", 1)[0]
        return prefix if len(prefix) == 2 and prefix.isalpha() else None

    @staticmethod
    def _text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = " ".join(value.split())
        return normalized or None
