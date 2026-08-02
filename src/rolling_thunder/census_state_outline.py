"""U.S. Census adapter for generalized state outlines used by the POTA overlay."""

from collections.abc import Mapping, Sequence
from json import JSONDecodeError, loads
from urllib.error import URLError
from urllib.parse import urlencode

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.pota_enrichment import StateOutline

_DEFAULT_ENDPOINT = (
    "https://tigerweb.geo.census.gov/arcgis/rest/services/"
    "Generalized_ACS2025/State_County/MapServer/4/query"
)
_JSON_ACCEPT = "application/geo+json,application/json"
_USER_AGENT = "RollingThunder/4.1 POTA mobile client"


class CensusStateOutlineError(OSError):
    """Raised when a Census state outline cannot be retrieved or validated."""


class CensusStateOutlineProvider:
    """Fetch one generalized U.S. state polygon for background rendering."""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        endpoint: str = _DEFAULT_ENDPOINT,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("Census state-outline timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._endpoint = endpoint

    def fetch_outline(self, location_code: str | None) -> StateOutline | None:
        """Return a generalized outline for a POTA location such as ``US-OH``."""
        state_code = self._state_code(location_code)
        if state_code is None:
            return None

        query = urlencode(
            {
                "where": f"STUSAB='{state_code}'",
                "outFields": "STUSAB,NAME,BASENAME",
                "returnGeometry": "true",
                "outSR": 4326,
                "geometryPrecision": 3,
                "f": "geojson",
            }
        )
        payload = self._request_json(f"{self._endpoint}?{query}")
        return self._parse_outline(payload, state_code)

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
            raise CensusStateOutlineError(
                "U.S. Census state map could not be reached."
            ) from error

        if not 200 <= response.status_code < 300:
            raise CensusStateOutlineError(
                f"U.S. Census state map returned HTTP {response.status_code}."
            )
        try:
            return loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise CensusStateOutlineError(
                "U.S. Census state map returned invalid JSON."
            ) from error

    @classmethod
    def _parse_outline(cls, payload: object, state_code: str) -> StateOutline:
        if not isinstance(payload, Mapping):
            raise CensusStateOutlineError(
                "U.S. Census state map response must be a JSON object."
            )
        features = payload.get("features")
        if not isinstance(features, list) or not features:
            raise CensusStateOutlineError(
                f"U.S. Census returned no outline for {state_code}."
            )
        feature = features[0]
        if not isinstance(feature, Mapping):
            raise CensusStateOutlineError("U.S. Census returned an invalid feature.")

        properties = feature.get("properties")
        state_name = state_code
        if isinstance(properties, Mapping):
            for key in ("NAME", "BASENAME"):
                candidate = properties.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    state_name = candidate.strip()
                    break

        geometry = feature.get("geometry")
        if not isinstance(geometry, Mapping):
            raise CensusStateOutlineError("U.S. Census returned no state geometry.")
        geometry_type = geometry.get("type")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, list):
            raise CensusStateOutlineError(
                "U.S. Census returned invalid state coordinates."
            )

        rings: list[tuple[tuple[float, float], ...]] = []
        if geometry_type == "Polygon":
            cls._append_polygon_rings(rings, coordinates)
        elif geometry_type == "MultiPolygon":
            for polygon in coordinates:
                if isinstance(polygon, list):
                    cls._append_polygon_rings(rings, polygon)
        else:
            raise CensusStateOutlineError(
                f"U.S. Census returned unsupported geometry {geometry_type!r}."
            )

        if not rings:
            raise CensusStateOutlineError(
                f"U.S. Census returned an empty outline for {state_code}."
            )
        return StateOutline(
            state_code=state_code,
            state_name=state_name,
            rings=tuple(rings),
        )

    @classmethod
    def _append_polygon_rings(
        cls,
        output: list[tuple[tuple[float, float], ...]],
        polygon: Sequence[object],
    ) -> None:
        if not polygon:
            return
        outer_ring = polygon[0]
        if not isinstance(outer_ring, list):
            return
        points: list[tuple[float, float]] = []
        for coordinate in outer_ring:
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
    def _state_code(location_code: str | None) -> str | None:
        if location_code is None:
            return None
        parts = location_code.strip().upper().split("-")
        if len(parts) != 2 or parts[0] != "US" or len(parts[1]) != 2:
            return None
        return parts[1]
