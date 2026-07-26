"""HTTP adapter for the public Parks on the Air spot feed."""

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from json import JSONDecodeError, loads
from urllib.error import URLError
from urllib.parse import urlparse

from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.pota_spot_source import (
    PotaSpotFetchResult,
    PotaSpotSourceAvailability,
    PotaSpotSourceConnectionError,
    PotaSpotSourceResponseError,
)
from rolling_thunder.pota_spots import ParkReference, PotaSpot

_JSON_CONTENT_TYPE = "application/json"
_DEFAULT_BASE_URL = "https://api.pota.app"
_DEFAULT_SPOTS_PATH = "/spot/activator"
_DATA_MODES = frozenset(
    {
        "DATA",
        "DIGITAL",
        "FT4",
        "FT8",
        "HELL",
        "JS8",
        "JT65",
        "JT9",
        "MFSK",
        "OLIVIA",
        "PACKET",
        "PSK",
        "PSK31",
        "RTTY",
        "SSTV",
    }
)


class HttpPotaSpotSource:
    """Synchronous typed adapter for the public POTA activator spot feed."""

    def __init__(
        self,
        base_url: str = _DEFAULT_BASE_URL,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._base_url = self._validate_base_url(base_url)
        if timeout_s <= 0:
            raise ValueError("POTA spot HTTP timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._now = now or (lambda: datetime.now(UTC))

    def fetch_spots(self) -> PotaSpotFetchResult:
        """Fetch and parse one immutable snapshot from the public POTA feed."""
        try:
            response = self._transport.request(
                "GET",
                f"{self._base_url}{_DEFAULT_SPOTS_PATH}",
                headers={"Accept": _JSON_CONTENT_TYPE},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise PotaSpotSourceConnectionError(
                f"POTA spot source could not be reached: {error}"
            ) from error

        if not 200 <= response.status_code < 300:
            raise PotaSpotSourceConnectionError(
                f"POTA spot source returned HTTP {response.status_code}."
            )

        payload = self._decode_json(response.body)
        if not isinstance(payload, list):
            raise PotaSpotSourceResponseError(
                "POTA spot source response must be a JSON array."
            )

        spots = tuple(
            spot
            for item in payload
            if (spot := self._parse_spot(item)) is not None
        )
        if payload and not spots:
            raise PotaSpotSourceResponseError(
                "POTA spot source returned no usable spot records."
            )

        fetched_at = self._now()
        if fetched_at.tzinfo is None or fetched_at.utcoffset() is None:
            raise ValueError("POTA spot source clock must return an aware datetime.")

        return PotaSpotFetchResult(
            availability=PotaSpotSourceAvailability.AVAILABLE,
            spots=spots,
            fetched_at=fetched_at,
        )

    @staticmethod
    def _decode_json(body: bytes) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise PotaSpotSourceResponseError(
                "POTA spot source returned invalid JSON."
            ) from error

    @classmethod
    def _parse_spot(cls, item: object) -> PotaSpot | None:
        if not isinstance(item, Mapping):
            return None
        try:
            frequency = cls._parse_frequency(item.get("frequency"))
            mode = cls._parse_mode(item.get("mode"), frequency)
            spotted_at = cls._parse_timestamp(item.get("spotTime"))
            park_name = item.get("parkName") or item.get("name")
            return PotaSpot(
                activator=item.get("activator"),
                park=ParkReference(
                    reference=item.get("reference"),
                    name=park_name,
                ),
                frequency=frequency,
                mode=mode,
                spotted_at=spotted_at,
                comments=item.get("comments"),
            )
        except (InvalidOperation, TypeError, ValueError, ValidationError):
            return None

    @staticmethod
    def _parse_frequency(value: object) -> Frequency:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise TypeError("frequency must be numeric")
        kilohertz = Decimal(str(value).strip())
        hertz = kilohertz * 1000
        if hertz != hertz.to_integral_value():
            raise ValueError("frequency must resolve to whole hertz")
        return Frequency(hz=int(hertz))

    @staticmethod
    def _parse_mode(value: object, frequency: Frequency) -> RadioMode:
        if not isinstance(value, str):
            raise TypeError("mode must be text")
        normalized = value.strip().upper()
        if normalized in RadioMode._value2member_map_:
            return RadioMode(normalized)
        if normalized == "SSB":
            return RadioMode.LSB if frequency.hz < 10_000_000 else RadioMode.USB
        if normalized in _DATA_MODES:
            return RadioMode.DATA
        raise ValueError("unsupported POTA mode")

    @staticmethod
    def _parse_timestamp(value: object) -> datetime:
        if not isinstance(value, str):
            raise TypeError("spot timestamp must be text")
        normalized = value.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("POTA base URL must be an absolute http or https URL.")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                "POTA base URL must not contain parameters, a query, or a fragment."
            )
        return normalized
