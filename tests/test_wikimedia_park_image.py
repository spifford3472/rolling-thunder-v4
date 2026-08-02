from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
from json import dumps

from PIL import Image

from rolling_thunder.pota_spots import ParkReference
from rolling_thunder.wikimedia_park_image import WikimediaParkImageProvider


@dataclass(frozen=True)
class FakeResponse:
    status_code: int
    body: bytes


class SequenceTransport:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = responses
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
        return self.responses.pop(0)


def park() -> ParkReference:
    return ParkReference(
        reference="US-1940",
        name="Caesar Creek State Park",
        location_code="US-OH",
    )


def jpeg_bytes() -> bytes:
    output = BytesIO()
    Image.new("RGB", (1600, 900), "white").save(output, format="JPEG")
    return output.getvalue()


def commons_payload(*, license_name: str, non_free: str = "0") -> bytes:
    return dumps(
        {
            "query": {
                "pages": {
                    "1": {
                        "imageinfo": [
                            {
                                "mime": "image/jpeg",
                                "thumburl": "https://upload.example/park.jpg",
                                "descriptionurl": "https://commons.example/file",
                                "extmetadata": {
                                    "LicenseShortName": {"value": license_name},
                                    "Artist": {"value": "<b>Jane Photographer</b>"},
                                    "NonFree": {"value": non_free},
                                    "Restrictions": {"value": ""},
                                },
                            }
                        ]
                    }
                }
            }
        }
    ).encode("utf-8")


def test_fetch_image_accepts_free_license_and_normalizes_png() -> None:
    transport = SequenceTransport(
        [
            FakeResponse(200, commons_payload(license_name="CC BY-SA 4.0")),
            FakeResponse(200, jpeg_bytes()),
        ]
    )
    provider = WikimediaParkImageProvider(transport=transport)

    image = provider.fetch_image(park())

    assert image is not None
    assert image.png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert image.attribution == "Jane Photographer"
    assert image.license_name == "CC BY-SA 4.0"
    assert image.source_url == "https://commons.example/file"
    assert len(transport.requests) == 2
    assert "User-Agent" in transport.requests[0][1]


def test_fetch_image_rejects_nonfree_candidate_without_download() -> None:
    transport = SequenceTransport(
        [
            FakeResponse(
                200,
                commons_payload(license_name="Fair use", non_free="1"),
            )
        ]
    )
    provider = WikimediaParkImageProvider(transport=transport)

    assert provider.fetch_image(park()) is None
    assert len(transport.requests) == 1
