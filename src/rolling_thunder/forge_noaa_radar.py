"""NOAA/NWS time-enabled MRMS base-reflectivity provider for Forge radar."""

from __future__ import annotations

from datetime import UTC, datetime
from json import JSONDecodeError, dumps, loads
from urllib.error import URLError
from urllib.parse import urlencode

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_radar import (
    ForgeRadarProviderError,
    RadarProductToken,
    RadarProviderFrame,
    RadarSourceMetadata,
)
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from rolling_thunder.map_tiles import MapTileError, MapTileKey, validate_map_tile_png
from rolling_thunder.radar_tiles import web_mercator_tile_bounds

DEFAULT_NOAA_RADAR_ENDPOINT = (
    "https://mapservices.weather.noaa.gov/eventdriven/rest/services/"
    "radar/radar_base_reflectivity_time/ImageServer"
)
DEFAULT_RADAR_USER_AGENT = (
    "RollingThunder-v4/4.1 "
    "(amateur-radio mobile dashboard; "
    "https://github.com/spifford3472/rolling-thunder-v4)"
)
_NOAA_SOURCE = RadarSourceMetadata(
    provider_id="noaa_nws_mrms",
    provider_name="NOAA/NWS",
    product=RadarProductToken.BASE_REFLECTIVITY,
    attribution_text="Radar: NOAA/NWS MRMS",
    attribution_url="https://radar.weather.gov/",
)


class NoaaNwsRadarProvider:
    """Discover and export exact NOAA/NWS MRMS radar frames through ArcGIS REST."""

    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_NOAA_RADAR_ENDPOINT,
        timeout_s: float = 5.0,
        maximum_json_bytes: int = 262_144,
        maximum_tile_bytes: int = 2_000_000,
        transport: HttpTransport | None = None,
        user_agent: str = DEFAULT_RADAR_USER_AGENT,
    ) -> None:
        normalized = endpoint.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("NOAA radar endpoint must be an absolute HTTP(S) URL.")
        if timeout_s <= 0:
            raise ValueError("NOAA radar timeout must be positive.")
        if maximum_json_bytes < 1 or maximum_tile_bytes < 1:
            raise ValueError("NOAA radar response limits must be positive.")
        if not user_agent.strip():
            raise ValueError("NOAA radar user agent must not be blank.")
        self._endpoint = normalized
        self._timeout_s = timeout_s
        self._maximum_json_bytes = maximum_json_bytes
        self._maximum_tile_bytes = maximum_tile_bytes
        self._transport = transport or UrllibHttpTransport()
        self._user_agent = user_agent.strip()

    def discover_latest(self, location: MobileLocationRecord) -> RadarProviderFrame:
        """Return the newest radar raster whose footprint covers the retained location."""
        geometry = dumps(
            {
                "x": location.longitude,
                "y": location.latitude,
                "spatialReference": {"wkid": 4326},
            },
            separators=(",", ":"),
        )
        params = {
            "where": "1=1",
            "geometry": geometry,
            "geometryType": "esriGeometryPoint",
            "inSR": "4326",
            "spatialRel": "esriSpatialRelIntersects",
            "outFields": (
                "objectid,idp_subset,idp_validtime,idp_validendtime,"
                "idp_filedate,idp_ingestdate"
            ),
            "returnGeometry": "false",
            "orderByFields": "idp_validtime DESC",
            "f": "json",
        }
        response = self._request_json("query", params)
        features = response.get("features")
        if not isinstance(features, list) or not features:
            raise ForgeRadarProviderError(
                "NOAA radar query returned no frame covering the retained location."
            )

        candidates: list[tuple[datetime, str, datetime | None]] = []
        for feature in features:
            if not isinstance(feature, dict):
                continue
            attributes = feature.get("attributes")
            if not isinstance(attributes, dict):
                continue
            object_id = attributes.get("objectid")
            valid_time = self._epoch_ms(attributes.get("idp_validtime"))
            if object_id is None or valid_time is None:
                continue
            valid_end = self._epoch_ms(attributes.get("idp_validendtime"))
            candidates.append((valid_time, str(object_id), valid_end))

        if not candidates:
            raise ForgeRadarProviderError(
                "NOAA radar query did not contain a usable observation timestamp."
            )
        observed_at, provider_frame_id, valid_until = max(
            candidates,
            key=lambda item: item[0],
        )
        return RadarProviderFrame(
            provider_frame_id=provider_frame_id,
            observed_at=observed_at,
            valid_until=valid_until,
            source=_NOAA_SOURCE,
        )

    def fetch_tile(self, provider_frame_id: str, key: MapTileKey) -> bytes:
        """Export one 256px Web Mercator PNG locked to one exact NOAA raster."""
        try:
            raster_id = int(provider_frame_id)
        except ValueError as error:
            raise ForgeRadarProviderError("NOAA radar frame identifier was invalid.") from error
        xmin, ymin, xmax, ymax = web_mercator_tile_bounds(key)
        mosaic_rule = dumps(
            {
                "mosaicMethod": "esriMosaicLockRaster",
                "lockRasterIds": [raster_id],
                "mosaicOperation": "MT_FIRST",
            },
            separators=(",", ":"),
        )
        params = {
            "bbox": f"{xmin:.6f},{ymin:.6f},{xmax:.6f},{ymax:.6f}",
            "bboxSR": "3857",
            "size": "256,256",
            "imageSR": "3857",
            "format": "png32",
            "interpolation": "RSP_NearestNeighbor",
            "mosaicRule": mosaic_rule,
            "f": "image",
        }
        response = self._request("exportImage", params, accept="image/png")
        if not 200 <= response.status_code < 300:
            raise ForgeRadarProviderError(
                f"NOAA radar tile request returned HTTP {response.status_code}."
            )
        if len(response.body) > self._maximum_tile_bytes:
            raise ForgeRadarProviderError("NOAA radar tile exceeded the safe size limit.")
        try:
            return validate_map_tile_png(
                response.body,
                maximum_bytes=self._maximum_tile_bytes,
            )
        except MapTileError as error:
            raise ForgeRadarProviderError("NOAA radar returned an invalid PNG tile.") from error

    def _request_json(self, operation: str, params: dict[str, str]) -> dict[str, object]:
        response = self._request(operation, params, accept="application/json")
        if not 200 <= response.status_code < 300:
            raise ForgeRadarProviderError(
                f"NOAA radar metadata request returned HTTP {response.status_code}."
            )
        if len(response.body) > self._maximum_json_bytes:
            raise ForgeRadarProviderError("NOAA radar metadata exceeded the safe size limit.")
        try:
            payload = loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise ForgeRadarProviderError("NOAA radar metadata was not valid JSON.") from error
        if not isinstance(payload, dict):
            raise ForgeRadarProviderError("NOAA radar metadata root was not an object.")
        if payload.get("error") is not None:
            raise ForgeRadarProviderError("NOAA radar metadata returned a provider error.")
        return payload

    def _request(
        self,
        operation: str,
        params: dict[str, str],
        *,
        accept: str,
    ) -> HttpResponse:
        url = f"{self._endpoint}/{operation}?{urlencode(params)}"
        try:
            return self._transport.request(
                "GET",
                url,
                headers={
                    "Accept": accept,
                    "User-Agent": self._user_agent,
                },
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeRadarProviderError(f"NOAA radar request failed: {error}") from error

    @staticmethod
    def _epoch_ms(value: object) -> datetime | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None
