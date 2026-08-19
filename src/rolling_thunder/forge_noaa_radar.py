"""NOAA/NWS time-enabled MRMS base-reflectivity provider for Forge radar."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from io import BytesIO
from json import JSONDecodeError, dumps, loads
from time import monotonic
from urllib.error import URLError
from urllib.parse import urlencode

from PIL import Image, UnidentifiedImageError

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_radar import ForgeRadarProviderError, RadarProviderFrame
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from rolling_thunder.map_tiles import (
    TILE_SIZE_PX,
    MapTileError,
    MapTileKey,
    validate_map_tile_png,
)
from rolling_thunder.radar_domain import RadarProductToken, RadarSourceMetadata
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
# NOAA currently advertises Max Image Width 15000 and Max Image Height 4100.
# Keep exports on whole Web-Mercator tile boundaries and below both limits.
_MAX_EXPORT_COLUMNS = 58
_MAX_EXPORT_ROWS = 16
_DEFAULT_MAXIMUM_EXPORT_BYTES = 96_000_000
_LOGGER = logging.getLogger("rolling_thunder.forge_spots")

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
        coverage_timeout_s: float | None = None,
        maximum_json_bytes: int = 262_144,
        maximum_tile_bytes: int = 2_000_000,
        maximum_export_bytes: int = _DEFAULT_MAXIMUM_EXPORT_BYTES,
        transport: HttpTransport | None = None,
        user_agent: str = DEFAULT_RADAR_USER_AGENT,
    ) -> None:
        normalized = endpoint.strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("NOAA radar endpoint must be an absolute HTTP(S) URL.")
        if timeout_s <= 0:
            raise ValueError("NOAA radar timeout must be positive.")
        resolved_coverage_timeout = (
            max(20.0, timeout_s)
            if coverage_timeout_s is None
            else coverage_timeout_s
        )
        if resolved_coverage_timeout <= 0:
            raise ValueError("NOAA radar coverage timeout must be positive.")
        if maximum_json_bytes < 1 or maximum_tile_bytes < 1 or maximum_export_bytes < 1:
            raise ValueError("NOAA radar response limits must be positive.")
        if not user_agent.strip():
            raise ValueError("NOAA radar user agent must not be blank.")
        self._endpoint = normalized
        self._timeout_s = timeout_s
        self._coverage_timeout_s = resolved_coverage_timeout
        self._maximum_json_bytes = maximum_json_bytes
        self._maximum_tile_bytes = maximum_tile_bytes
        self._maximum_export_bytes = maximum_export_bytes
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
        started = monotonic()
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
        _LOGGER.info(
            "RADAR NOAA DISCOVERY frame=%s duration_ms=%d",
            provider_frame_id,
            round((monotonic() - started) * 1000),
        )
        return RadarProviderFrame(
            provider_frame_id=provider_frame_id,
            observed_at=observed_at,
            valid_until=valid_until,
            source=_NOAA_SOURCE,
        )

    def fetch_tile(self, provider_frame_id: str, key: MapTileKey) -> bytes:
        """Export one transparent 256px Web Mercator PNG locked to one NOAA raster."""
        coverage = self.fetch_coverage(
            provider_frame_id,
            zoom=key.zoom,
            x_start=key.x,
            y_start=key.y,
            columns=1,
            rows=1,
        )
        return coverage[key]

    def fetch_coverage(
        self,
        provider_frame_id: str,
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> dict[MapTileKey, bytes]:
        """Export and slice one exact-frame tile rectangle with few NOAA requests."""
        try:
            raster_id = int(provider_frame_id)
        except ValueError as error:
            raise ForgeRadarProviderError("NOAA radar frame identifier was invalid.") from error
        self._validate_rectangle(
            zoom=zoom,
            x_start=x_start,
            y_start=y_start,
            columns=columns,
            rows=rows,
        )

        started = monotonic()
        output: dict[MapTileKey, bytes] = {}
        export_calls = 0
        y_offset = 0
        while y_offset < rows:
            chunk_rows = min(_MAX_EXPORT_ROWS, rows - y_offset)
            x_offset = 0
            while x_offset < columns:
                chunk_columns = min(_MAX_EXPORT_COLUMNS, columns - x_offset)
                chunk = self._fetch_export_chunk(
                    raster_id,
                    zoom=zoom,
                    x_start=x_start + x_offset,
                    y_start=y_start + y_offset,
                    columns=chunk_columns,
                    rows=chunk_rows,
                )
                output.update(chunk)
                export_calls += 1
                x_offset += chunk_columns
            y_offset += chunk_rows

        _LOGGER.info(
            "RADAR NOAA COVERAGE frame=%s zoom=%d x=%d y=%d cols=%d rows=%d "
            "tiles=%d export_calls=%d duration_ms=%d",
            provider_frame_id,
            zoom,
            x_start,
            y_start,
            columns,
            rows,
            len(output),
            export_calls,
            round((monotonic() - started) * 1000),
        )
        return output

    def _fetch_export_chunk(
        self,
        raster_id: int,
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> dict[MapTileKey, bytes]:
        top_left = MapTileKey(zoom=zoom, x=x_start, y=y_start)
        bottom_right = MapTileKey(
            zoom=zoom,
            x=x_start + columns - 1,
            y=y_start + rows - 1,
        )
        left_xmin, _left_ymin, _left_xmax, top_ymax = web_mercator_tile_bounds(
            top_left
        )
        _right_xmin, bottom_ymin, right_xmax, _right_ymax = web_mercator_tile_bounds(
            bottom_right
        )
        mosaic_rule = dumps(
            {
                "mosaicMethod": "esriMosaicLockRaster",
                "lockRasterIds": [raster_id],
                "mosaicOperation": "MT_FIRST",
            },
            separators=(",", ":"),
        )
        width = columns * TILE_SIZE_PX
        height = rows * TILE_SIZE_PX
        params = {
            "bbox": f"{left_xmin:.6f},{bottom_ymin:.6f},{right_xmax:.6f},{top_ymax:.6f}",
            "bboxSR": "3857",
            "size": f"{width},{height}",
            "imageSR": "3857",
            "format": "png32",
            "transparent": "true",
            "interpolation": "RSP_NearestNeighbor",
            "mosaicRule": mosaic_rule,
            "f": "image",
        }
        response = self._request(
            "exportImage",
            params,
            accept="image/png",
            timeout_s=self._coverage_timeout_s,
        )
        if not 200 <= response.status_code < 300:
            raise ForgeRadarProviderError(
                f"NOAA radar coverage request returned HTTP {response.status_code}."
            )
        if len(response.body) > self._maximum_export_bytes:
            raise ForgeRadarProviderError("NOAA radar coverage image exceeded the safe size limit.")

        image = self._decode_export_png(response.body, width=width, height=height)
        tiles: dict[MapTileKey, bytes] = {}
        for row_offset in range(rows):
            for column_offset in range(columns):
                key = MapTileKey(
                    zoom=zoom,
                    x=x_start + column_offset,
                    y=y_start + row_offset,
                )
                crop = image.crop(
                    (
                        column_offset * TILE_SIZE_PX,
                        row_offset * TILE_SIZE_PX,
                        (column_offset + 1) * TILE_SIZE_PX,
                        (row_offset + 1) * TILE_SIZE_PX,
                    )
                )
                encoded = BytesIO()
                crop.save(encoded, format="PNG")
                try:
                    tiles[key] = validate_map_tile_png(
                        encoded.getvalue(),
                        maximum_bytes=self._maximum_tile_bytes,
                    )
                except MapTileError as error:
                    raise ForgeRadarProviderError(
                        "NOAA radar coverage slicing produced an invalid tile."
                    ) from error
        return tiles

    def _decode_export_png(self, body: bytes, *, width: int, height: int) -> Image.Image:
        try:
            with Image.open(BytesIO(body)) as opened:
                opened.load()
                if opened.format != "PNG":
                    raise ForgeRadarProviderError("NOAA radar coverage was not a PNG image.")
                if opened.size != (width, height):
                    raise ForgeRadarProviderError(
                        "NOAA radar coverage image dimensions did not match the request."
                    )
                return opened.convert("RGBA")
        except ForgeRadarProviderError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError) as error:
            raise ForgeRadarProviderError(
                "NOAA radar returned an invalid coverage PNG."
            ) from error

    @staticmethod
    def _validate_rectangle(
        *,
        zoom: int,
        x_start: int,
        y_start: int,
        columns: int,
        rows: int,
    ) -> None:
        if not 0 <= zoom <= 22:
            raise ForgeRadarProviderError("Radar coverage zoom was invalid.")
        if columns < 1 or rows < 1:
            raise ForgeRadarProviderError("Radar coverage dimensions must be positive.")
        limit = 1 << zoom
        if x_start < 0 or y_start < 0:
            raise ForgeRadarProviderError("Radar coverage origin was invalid.")
        if x_start + columns > limit or y_start + rows > limit:
            raise ForgeRadarProviderError("Radar coverage rectangle exceeded the map world.")

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
        timeout_s: float | None = None,
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
                timeout_s=self._timeout_s if timeout_s is None else timeout_s,
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
