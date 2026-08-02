"""Wikimedia Commons adapter for licensed park display images."""

from collections.abc import Mapping
from html.parser import HTMLParser
from io import BytesIO
from json import JSONDecodeError, loads
from urllib.error import URLError
from urllib.parse import urlencode

from PIL import Image, UnidentifiedImageError

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.pota_enrichment import ParkImage
from rolling_thunder.pota_spots import ParkReference

_COMMONS_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
_USER_AGENT = "RollingThunder/4.1 POTA mobile client"
_MAXIMUM_IMAGE_BYTES = 8 * 1024 * 1024
_MAXIMUM_IMAGE_SIZE = (1200, 700)
_ALLOWED_LICENSE_PREFIXES = (
    "CC BY",
    "CC-BY",
    "CC0",
    "PUBLIC DOMAIN",
    "PD-",
)


class WikimediaParkImageError(OSError):
    """Raised when a Commons image cannot be safely retrieved or normalized."""


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        normalized = data.strip()
        if normalized:
            self.parts.append(normalized)


class WikimediaParkImageProvider:
    """Find one freely licensed Commons image for a named park."""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        endpoint: str = _COMMONS_ENDPOINT,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("Wikimedia HTTP timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._endpoint = endpoint

    def fetch_image(self, park: ParkReference) -> ParkImage | None:
        """Return the first suitable licensed image normalized to PNG."""
        if park.name is None:
            return None

        search_text = f'"{park.name}" {self._location_search_text(park.location_code)}'
        query = urlencode(
            {
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": search_text,
                "gsrnamespace": 6,
                "gsrlimit": 5,
                "prop": "imageinfo",
                "iiprop": "url|mime|extmetadata",
                "iiurlwidth": 1200,
                "iiextmetadatafilter": (
                    "LicenseShortName|Artist|Credit|AttributionRequired|"
                    "NonFree|Restrictions"
                ),
            }
        )
        payload = self._request_json(f"{self._endpoint}?{query}")
        pages = self._pages(payload)

        for page in pages:
            candidate = self._candidate(page)
            if candidate is None:
                continue
            thumbnail_url, source_url, attribution, license_name = candidate
            image_bytes = self._request_bytes(thumbnail_url)
            png_bytes = self._normalize_png(image_bytes)
            return ParkImage(
                png_bytes=png_bytes,
                attribution=attribution,
                license_name=license_name,
                source_url=source_url,
            )
        return None

    def _request_json(self, url: str) -> object:
        body = self._request_bytes(url, accept="application/json")
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise WikimediaParkImageError(
                "Wikimedia Commons returned invalid JSON."
            ) from error

    def _request_bytes(self, url: str, *, accept: str = "image/*") -> bytes:
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": accept, "User-Agent": _USER_AGENT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise WikimediaParkImageError(
                "Wikimedia Commons could not be reached."
            ) from error

        if not 200 <= response.status_code < 300:
            raise WikimediaParkImageError(
                f"Wikimedia Commons returned HTTP {response.status_code}."
            )
        if len(response.body) > _MAXIMUM_IMAGE_BYTES:
            raise WikimediaParkImageError("Wikimedia image exceeded the size limit.")
        return response.body

    @staticmethod
    def _pages(payload: object) -> list[Mapping[str, object]]:
        if not isinstance(payload, Mapping):
            raise WikimediaParkImageError(
                "Wikimedia Commons response must be a JSON object."
            )
        query = payload.get("query")
        if query is None:
            return []
        if not isinstance(query, Mapping):
            raise WikimediaParkImageError(
                "Wikimedia Commons response contains an invalid query object."
            )
        pages = query.get("pages")
        if not isinstance(pages, Mapping):
            return []
        return [page for page in pages.values() if isinstance(page, Mapping)]

    @classmethod
    def _candidate(
        cls,
        page: Mapping[str, object],
    ) -> tuple[str, str, str, str] | None:
        image_info_items = page.get("imageinfo")
        if not isinstance(image_info_items, list) or not image_info_items:
            return None
        image_info = image_info_items[0]
        if not isinstance(image_info, Mapping):
            return None

        mime = image_info.get("mime")
        if not isinstance(mime, str) or not mime.startswith("image/"):
            return None
        thumbnail_url = image_info.get("thumburl") or image_info.get("url")
        source_url = image_info.get("descriptionurl") or image_info.get("url")
        if not isinstance(thumbnail_url, str) or not isinstance(source_url, str):
            return None

        metadata = image_info.get("extmetadata")
        if not isinstance(metadata, Mapping):
            return None
        if cls._metadata_value(metadata, "NonFree").casefold() in {"1", "true"}:
            return None
        if cls._metadata_value(metadata, "Restrictions"):
            return None

        license_name = cls._metadata_value(metadata, "LicenseShortName")
        if not cls._license_is_allowed(license_name):
            return None

        attribution = cls._plain_text(
            cls._metadata_value(metadata, "Artist")
            or cls._metadata_value(metadata, "Credit")
            or "Wikimedia Commons contributor"
        )
        return thumbnail_url, source_url, attribution, license_name

    @staticmethod
    def _metadata_value(metadata: Mapping[str, object], name: str) -> str:
        item = metadata.get(name)
        if not isinstance(item, Mapping):
            return ""
        value = item.get("value")
        return value.strip() if isinstance(value, str) else ""

    @staticmethod
    def _license_is_allowed(license_name: str) -> bool:
        normalized = license_name.strip().upper()
        return any(
            normalized.startswith(prefix)
            for prefix in _ALLOWED_LICENSE_PREFIXES
        )

    @staticmethod
    def _plain_text(value: str) -> str:
        parser = _PlainTextParser()
        parser.feed(value)
        plain = " ".join(parser.parts)
        return " ".join(plain.split())[:200]

    @staticmethod
    def _location_search_text(location_code: str | None) -> str:
        if location_code is None:
            return ""
        return location_code.replace("-", " ")

    @staticmethod
    def _normalize_png(image_bytes: bytes) -> bytes:
        try:
            with Image.open(BytesIO(image_bytes)) as image:
                image.load()
                image.thumbnail(_MAXIMUM_IMAGE_SIZE, Image.Resampling.LANCZOS)
                normalized = image.convert("RGBA" if "A" in image.getbands() else "RGB")
                output = BytesIO()
                normalized.save(output, format="PNG", optimize=True)
                png_bytes = output.getvalue()
        except (UnidentifiedImageError, OSError, ValueError) as error:
            raise WikimediaParkImageError(
                "Wikimedia returned an unsupported image."
            ) from error

        if not png_bytes or len(png_bytes) > _MAXIMUM_IMAGE_BYTES:
            raise WikimediaParkImageError(
                "Normalized Wikimedia image exceeded the size limit."
            )
        return png_bytes
