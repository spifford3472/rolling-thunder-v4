"""Open-Meteo adapter for current park weather and local time."""

from collections.abc import Mapping
from json import JSONDecodeError, loads
from urllib.error import URLError
from urllib.parse import urlencode

from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.pota_enrichment import ParkWeather
from rolling_thunder.pota_spots import ParkReference

_DEFAULT_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
_JSON_ACCEPT = "application/json"


class OpenMeteoError(OSError):
    """Raised when Open-Meteo data cannot be retrieved or validated."""


class OpenMeteoParkWeatherProvider:
    """Synchronous Open-Meteo adapter intended for background-worker use."""

    def __init__(
        self,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        endpoint: str = _DEFAULT_ENDPOINT,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("Open-Meteo HTTP timeout must be positive.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._endpoint = endpoint

    def fetch_weather(self, park: ParkReference) -> ParkWeather:
        """Return current temperature, condition, and local time for one park."""
        if park.latitude is None or park.longitude is None:
            raise ValueError("Park coordinates are required for weather lookup.")

        query = urlencode(
            {
                "latitude": park.latitude,
                "longitude": park.longitude,
                "current": "temperature_2m,weather_code,is_day",
                "timezone": "auto",
                "forecast_days": 1,
            }
        )
        try:
            response = self._transport.request(
                "GET",
                f"{self._endpoint}?{query}",
                headers={"Accept": _JSON_ACCEPT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise OpenMeteoError("Open-Meteo could not be reached.") from error

        if not 200 <= response.status_code < 300:
            raise OpenMeteoError(
                f"Open-Meteo returned HTTP {response.status_code}."
            )

        payload = self._decode_json(response.body)
        if not isinstance(payload, Mapping):
            raise OpenMeteoError("Open-Meteo response must be a JSON object.")
        if payload.get("error") is True:
            raise OpenMeteoError("Open-Meteo rejected the weather request.")

        current = payload.get("current")
        if not isinstance(current, Mapping):
            raise OpenMeteoError("Open-Meteo response is missing current weather.")

        temperature = current.get("temperature_2m")
        if isinstance(temperature, bool) or not isinstance(temperature, (int, float)):
            raise OpenMeteoError("Open-Meteo returned an invalid temperature.")

        weather_code = current.get("weather_code")
        if isinstance(weather_code, bool) or not isinstance(weather_code, int):
            raise OpenMeteoError("Open-Meteo returned an invalid weather code.")

        is_day = current.get("is_day")
        if isinstance(is_day, bool) or is_day not in {0, 1}:
            raise OpenMeteoError("Open-Meteo returned an invalid day-state value.")

        local_timestamp = current.get("time")
        if not isinstance(local_timestamp, str) or "T" not in local_timestamp:
            raise OpenMeteoError("Open-Meteo returned an invalid local time.")
        local_time = local_timestamp.split("T", 1)[1][:5]
        if len(local_time) != 5 or local_time[2] != ":":
            raise OpenMeteoError("Open-Meteo returned an invalid local time.")

        timezone = payload.get("timezone")
        normalized_timezone = timezone if isinstance(timezone, str) else None
        temperature_c = float(temperature)
        return ParkWeather(
            temperature_c=temperature_c,
            temperature_f=(temperature_c * 9.0 / 5.0) + 32.0,
            local_time=local_time,
            weather_code=weather_code,
            is_day=is_day == 1,
            timezone=normalized_timezone,
        )

    @staticmethod
    def _decode_json(body: bytes) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise OpenMeteoError("Open-Meteo returned invalid JSON.") from error
