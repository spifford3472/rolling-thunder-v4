"""National Weather Service active-alert point provider for Forge."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from json import JSONDecodeError, loads
from typing import Final, cast
from urllib.error import URLError
from urllib.parse import urlencode, urlparse

from pydantic import ValidationError

from rolling_thunder.forge_mobile_location import MobileLocationRecord
from rolling_thunder.forge_weather_alerts import (
    ForgeWeatherAlertProviderError,
    WeatherAlertCertainty,
    WeatherAlertRecord,
    WeatherAlertSeverity,
    WeatherAlertSnapshot,
    WeatherAlertSourceMetadata,
    WeatherAlertUrgency,
)
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport

_DEFAULT_ENDPOINT = "https://api.weather.gov/alerts/active"
_ACCEPT = "application/geo+json"
_MAX_RESPONSE_BYTES: Final = 4_194_304
_SOURCE = WeatherAlertSourceMetadata(
    provider_id="nws",
    provider_name="National Weather Service",
    attribution_text="National Weather Service alerts",
    attribution_url="https://www.weather.gov/",
)


class NwsWeatherAlertProvider:
    """Fetch and normalize NWS active alerts for one exact trusted point."""

    def __init__(
        self,
        *,
        user_agent: str,
        endpoint: str = _DEFAULT_ENDPOINT,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        now: callable[[], datetime] | None = None,
    ) -> None:
        normalized_agent = user_agent.strip()
        if not normalized_agent:
            raise ValueError("NWS weather alert User-Agent must not be blank.")
        if timeout_s <= 0:
            raise ValueError("NWS weather alert timeout must be positive.")
        self._endpoint = self._validate_endpoint(endpoint)
        self._user_agent = normalized_agent
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._now = now or (lambda: datetime.now(UTC))

    def fetch_alerts(self, location: MobileLocationRecord) -> WeatherAlertSnapshot:
        """Return the complete NWS active-alert set for the requested point."""
        latitude = round(location.latitude, 4)
        longitude = round(location.longitude, 4)
        query = urlencode({"point": f"{latitude:.4f},{longitude:.4f}"})
        url = f"{self._endpoint}?{query}"

        try:
            response = self._transport.request(
                "GET",
                url,
                headers={
                    "Accept": _ACCEPT,
                    "User-Agent": self._user_agent,
                },
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise ForgeWeatherAlertProviderError(
                f"NWS weather alert request failed: {error}"
            ) from error

        if not 200 <= response.status_code < 300:
            raise ForgeWeatherAlertProviderError(
                f"NWS weather alert request returned HTTP {response.status_code}."
            )
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise ForgeWeatherAlertProviderError(
                "NWS weather alert response exceeded 4194304 bytes."
            )

        payload = self._decode_json(response.body)
        alerts = self._parse_feature_collection(payload)
        fetched_at = self._aware_now()
        return WeatherAlertSnapshot(
            latitude=latitude,
            longitude=longitude,
            fetched_at=fetched_at,
            alerts=alerts,
            source=_SOURCE,
        )

    def _parse_feature_collection(
        self,
        payload: object,
    ) -> tuple[WeatherAlertRecord, ...]:
        root = self._require_mapping(payload, "response root")
        features = root.get("features")
        if not isinstance(features, list):
            raise ForgeWeatherAlertProviderError(
                "NWS weather alert response features must be an array."
            )

        parsed: list[WeatherAlertRecord] = []
        seen_ids: set[str] = set()
        for index, raw_feature in enumerate(features):
            feature = self._require_mapping(raw_feature, f"feature {index}")
            properties = self._require_mapping(
                feature.get("properties"),
                f"feature {index} properties",
            )

            status = self._optional_text(properties.get("status"))
            if status is None or status.casefold() != "actual":
                continue
            message_type = self._optional_text(properties.get("messageType"))
            if message_type is not None and message_type.casefold() == "cancel":
                continue

            alert_id = self._required_text(feature.get("id"), "alert id")
            if alert_id in seen_ids:
                raise ForgeWeatherAlertProviderError(
                    f"NWS weather alert response repeated alert id {alert_id!r}."
                )
            seen_ids.add(alert_id)

            event = self._required_text(properties.get("event"), "event")
            headline = self._optional_text(properties.get("headline")) or event
            area_description = self._optional_text(properties.get("areaDesc"))

            raw_record: dict[str, object] = {
                "alert_id": alert_id,
                "event": event,
                "severity": self._severity(properties.get("severity")),
                "urgency": self._urgency(properties.get("urgency")),
                "certainty": self._certainty(properties.get("certainty")),
                "headline": headline,
                "area_description": area_description,
                "sent_at": self._required_text(properties.get("sent"), "sent"),
                "effective_at": self._required_text(
                    properties.get("effective"),
                    "effective",
                ),
                "onset_at": self._optional_text(properties.get("onset")),
                "ends_at": self._optional_text(properties.get("ends")),
                "expires_at": self._required_text(
                    properties.get("expires"),
                    "expires",
                ),
            }
            try:
                parsed.append(WeatherAlertRecord.model_validate(raw_record))
            except ValidationError as error:
                raise ForgeWeatherAlertProviderError(
                    f"NWS weather alert {alert_id!r} failed schema validation."
                ) from error

        return tuple(sorted(parsed, key=self._sort_key))

    @staticmethod
    def _sort_key(alert: WeatherAlertRecord) -> tuple[int, str, str]:
        severity_order = {
            WeatherAlertSeverity.EXTREME: 0,
            WeatherAlertSeverity.SEVERE: 1,
            WeatherAlertSeverity.MODERATE: 2,
            WeatherAlertSeverity.MINOR: 3,
            WeatherAlertSeverity.UNKNOWN: 4,
        }
        return (
            severity_order[alert.severity],
            alert.event.casefold(),
            alert.alert_id,
        )

    @staticmethod
    def _severity(value: object) -> WeatherAlertSeverity:
        text = NwsWeatherAlertProvider._optional_text(value)
        if text is None:
            return WeatherAlertSeverity.UNKNOWN
        try:
            return WeatherAlertSeverity(text.casefold())
        except ValueError:
            return WeatherAlertSeverity.UNKNOWN

    @staticmethod
    def _urgency(value: object) -> WeatherAlertUrgency:
        text = NwsWeatherAlertProvider._optional_text(value)
        if text is None:
            return WeatherAlertUrgency.UNKNOWN
        try:
            return WeatherAlertUrgency(text.casefold())
        except ValueError:
            return WeatherAlertUrgency.UNKNOWN

    @staticmethod
    def _certainty(value: object) -> WeatherAlertCertainty:
        text = NwsWeatherAlertProvider._optional_text(value)
        if text is None:
            return WeatherAlertCertainty.UNKNOWN
        try:
            return WeatherAlertCertainty(text.casefold())
        except ValueError:
            return WeatherAlertCertainty.UNKNOWN

    @staticmethod
    def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
        if not isinstance(value, dict):
            raise ForgeWeatherAlertProviderError(
                f"NWS weather alert {field_name} must be an object."
            )
        return cast(Mapping[str, object], value)

    @staticmethod
    def _required_text(value: object, field_name: str) -> str:
        text = NwsWeatherAlertProvider._optional_text(value)
        if text is None:
            raise ForgeWeatherAlertProviderError(
                f"NWS weather alert {field_name} must be non-empty text."
            )
        return text

    @staticmethod
    def _optional_text(value: object) -> str | None:
        if value is None:
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @staticmethod
    def _decode_json(body: bytes) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise ForgeWeatherAlertProviderError(
                "NWS weather alert response was not valid UTF-8 JSON."
            ) from error

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("NWS weather alert clock must be timezone-aware")
        return value.astimezone(UTC)

    @staticmethod
    def _validate_endpoint(endpoint: str) -> str:
        normalized = endpoint.strip().rstrip("?")
        parsed = urlparse(normalized)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("NWS weather alert endpoint must be an absolute HTTPS URL.")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                "NWS weather alert endpoint must not contain parameters, query, or fragment."
            )
        return normalized
