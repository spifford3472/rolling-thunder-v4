"""Validated QRZ profile-image downloader for background use."""

from io import BytesIO
from urllib.error import URLError
from urllib.parse import urlparse

from PIL import Image, UnidentifiedImageError

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport

_USER_AGENT = "RollingThunder/4.1 POTA mobile client"
_MAXIMUM_IMAGE_BYTES = 6 * 1024 * 1024
_MAXIMUM_IMAGE_SIZE = (600, 600)


class QrzProfileImageError(OSError):
    """Raised when a QRZ profile image cannot be safely retrieved."""


class QrzProfileImageProvider:
    """Download and normalize an image URL returned by the QRZ XML service."""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("QRZ profile-image timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()

    def fetch_photo(self, image_url: str) -> bytes:
        """Return a bounded PNG for one trusted QRZ-hosted image URL."""
        self._validate_url(image_url)
        try:
            response = self._transport.request(
                "GET",
                image_url,
                headers={"Accept": "image/*", "User-Agent": _USER_AGENT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise QrzProfileImageError("QRZ profile image could not be reached.") from error

        if not 200 <= response.status_code < 300:
            raise QrzProfileImageError(
                f"QRZ profile image returned HTTP {response.status_code}."
            )
        if not response.body or len(response.body) > _MAXIMUM_IMAGE_BYTES:
            raise QrzProfileImageError("QRZ profile image exceeded the size limit.")
        return self._normalize_png(response.body)

    @staticmethod
    def _validate_url(image_url: str) -> None:
        parsed = urlparse(image_url)
        hostname = (parsed.hostname or "").casefold()
        if parsed.scheme not in {"https", "http"}:
            raise QrzProfileImageError("QRZ profile image URL is not HTTP(S).")
        if hostname != "qrz.com" and not hostname.endswith(".qrz.com"):
            raise QrzProfileImageError("QRZ profile image URL is not hosted by QRZ.")

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
            raise QrzProfileImageError(
                "QRZ returned an unsupported profile image."
            ) from error

        if not png_bytes or len(png_bytes) > _MAXIMUM_IMAGE_BYTES:
            raise QrzProfileImageError(
                "Normalized QRZ profile image exceeded the size limit."
            )
        return png_bytes
