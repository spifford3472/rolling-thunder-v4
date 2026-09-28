from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO

import pytest
from PIL import Image

from rolling_thunder.qrz_profile_image import (
    QrzProfileImageError,
    QrzProfileImageProvider,
)


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class FakeTransport:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, Mapping[str, str]]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> FakeResponse:
        del method, body, timeout_s
        self.requests.append((url, headers))
        return self.response


def jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (800, 400), "white").save(output, format="JPEG")
    return output.getvalue()


def test_trusted_qrz_image_is_normalized_to_bounded_png() -> None:
    transport = FakeTransport(
        FakeResponse(status_code=200, body=jpeg_bytes())
    )
    provider = QrzProfileImageProvider(transport=transport)

    png_bytes = provider.fetch_photo(
        "https://cdn-xml.qrz.com/ki5vnb/profile.jpg"
    )

    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    with Image.open(BytesIO(png_bytes)) as image:
        assert image.width <= 600
        assert image.height <= 600
    assert len(transport.requests) == 1


def test_non_qrz_host_is_rejected_before_http() -> None:
    transport = FakeTransport(
        FakeResponse(status_code=200, body=jpeg_bytes())
    )
    provider = QrzProfileImageProvider(transport=transport)

    with pytest.raises(QrzProfileImageError, match="not hosted by QRZ"):
        provider.fetch_photo("https://example.com/profile.jpg")

    assert transport.requests == []


def test_invalid_image_payload_is_actionable() -> None:
    provider = QrzProfileImageProvider(
        transport=FakeTransport(
            FakeResponse(status_code=200, body=b"not-an-image")
        )
    )

    with pytest.raises(QrzProfileImageError, match="unsupported profile image"):
        provider.fetch_photo("https://cdn-xml.qrz.com/profile.jpg")
