"""Typed Wavelog v2 adapter used only by Forge contact synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from enum import StrEnum
from json import JSONDecodeError, dumps, loads
from typing import Any
from urllib.error import URLError
from urllib.parse import urlparse

from pydantic import SecretStr

from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band

_JSON_CONTENT_TYPE = "application/json"


class WavelogError(Exception):
    """Base exception for Wavelog synchronization operations."""


class WavelogConnectionError(WavelogError):
    """Raised when Wavelog cannot be reached."""


class WavelogAuthenticationError(WavelogError):
    """Raised when the configured Wavelog token is rejected."""


class WavelogResponseError(WavelogError):
    """Raised when Wavelog returns an invalid or unsuccessful response."""


class WavelogStationLocationError(WavelogError):
    """Raised when the configured station location is absent or ambiguous."""


class WavelogUploadDisposition(StrEnum):
    """Outcome of one Wavelog ADIF import."""

    IMPORTED = "imported"
    DUPLICATE = "duplicate"


@dataclass(frozen=True, slots=True)
class WavelogStationLocation:
    """Resolved Wavelog station location used for QSO writes."""

    station_id: int
    name: str
    gridsquare: str
    uuid: str | None = None


class WavelogClient:
    """Synchronous Wavelog v2 client intended for Forge request threads."""

    def __init__(
        self,
        base_url: str,
        token: SecretStr,
        *,
        station_location_name: str,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
    ) -> None:
        self._base_url = self._validate_base_url(base_url)
        if not token.get_secret_value():
            raise ValueError("Wavelog token must not be blank.")
        location_name = station_location_name.strip()
        if not location_name:
            raise ValueError("Wavelog station location name must not be blank.")
        if timeout_s <= 0:
            raise ValueError("Wavelog HTTP timeout must be positive.")
        self._token = token
        self._station_location_name = location_name
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._resolved_location: WavelogStationLocation | None = None

    def resolve_station_location(self, *, refresh: bool = False) -> WavelogStationLocation:
        """Resolve exactly one configured station location without guessing its numeric ID."""
        if self._resolved_location is not None and not refresh:
            return self._resolved_location

        response = self._request("GET", "/index.php/api/v2/station", body=None)
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "station-location lookup")
        payload = self._decode_json(response.body, operation="station-location lookup")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise WavelogResponseError(
                "Wavelog station-location lookup returned an unexpected response schema."
            )

        matches: list[WavelogStationLocation] = []
        for item in payload["data"]:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            station_id = item.get("id")
            if name != self._station_location_name:
                continue
            if isinstance(station_id, bool) or not isinstance(station_id, int):
                raise WavelogResponseError(
                    "Wavelog station-location lookup returned a non-numeric station ID."
                )
            station_grid = item.get("gridsquare", "")
            if station_grid is None:
                station_grid = ""
            if not isinstance(station_grid, str):
                raise WavelogResponseError(
                    "Wavelog station-location lookup returned a non-text gridsquare."
                )
            station_uuid = item.get("uuid")
            matches.append(
                WavelogStationLocation(
                    station_id=station_id,
                    name=name,
                    gridsquare=station_grid.strip().upper(),
                    uuid=station_uuid if isinstance(station_uuid, str) else None,
                )
            )

        if len(matches) != 1:
            raise WavelogStationLocationError(
                "Configured Wavelog station location must resolve to exactly one owned "
                f"profile named {self._station_location_name!r}; found {len(matches)}."
            )
        self._resolved_location = matches[0]
        return matches[0]

    def upload_contact(self, contact: Contact) -> WavelogUploadDisposition:
        """Import one contact into the resolved station location with Wavelog dupe checking."""
        location = self._align_station_location_grid(
            self.resolve_station_location(),
            contact,
        )
        adif = contact_to_adif(contact)
        body = dumps(
            {
                "import_type": "adif",
                "station_profile_id": location.station_id,
                "adif": adif,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request("POST", "/index.php/api/v2/qso", body=body)
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "QSO import")
        payload = self._decode_json(response.body, operation="QSO import")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise WavelogResponseError("Wavelog QSO import returned an unexpected response schema.")

        data: dict[str, Any] = payload["data"]
        parsed = data.get("parsed")
        imported = data.get("imported")
        skipped = data.get("skipped")
        if parsed != 1 or imported not in {0, 1} or skipped not in {0, 1}:
            raise WavelogResponseError(
                "Wavelog QSO import did not report one deterministic parsed record."
            )
        if imported == 1 and skipped == 0:
            return WavelogUploadDisposition.IMPORTED
        if imported == 0 and skipped == 1:
            return WavelogUploadDisposition.DUPLICATE
        raise WavelogResponseError(
            "Wavelog QSO import returned an inconsistent imported/skipped result."
        )

    def _align_station_location_grid(
        self,
        location: WavelogStationLocation,
        contact: Contact,
    ) -> WavelogStationLocation:
        """Make Wavelog's Mobile profile grid match this contact before import."""
        desired_grid = "" if contact.my_grid is None else str(contact.my_grid).strip().upper()
        if location.gridsquare == desired_grid:
            return location

        body = dumps(
            {"gridsquare": desired_grid},
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request(
            "PATCH",
            f"/index.php/api/v2/station/{location.station_id}",
            body=body,
        )
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "station-location grid update")

        payload = self._decode_json(
            response.body,
            operation="station-location grid update",
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise WavelogResponseError(
                "Wavelog station-location grid update returned an unexpected response schema."
            )

        data: dict[str, Any] = payload["data"]
        station_id = data.get("id")
        name = data.get("name")
        station_grid = data.get("gridsquare", "")
        if station_grid is None:
            station_grid = ""
        if (
            station_id != location.station_id
            or name != location.name
            or not isinstance(station_grid, str)
            or station_grid.strip().upper() != desired_grid
        ):
            raise WavelogResponseError(
                "Wavelog station-location grid update did not confirm the requested target."
            )

        station_uuid = data.get("uuid")
        updated_location = WavelogStationLocation(
            station_id=location.station_id,
            name=location.name,
            gridsquare=desired_grid,
            uuid=station_uuid if isinstance(station_uuid, str) else location.uuid,
        )
        self._resolved_location = updated_location
        return updated_location

    def _request(self, method: str, path: str, *, body: bytes | None) -> HttpResponse:
        headers = {
            "Accept": _JSON_CONTENT_TYPE,
            "Authorization": f"Bearer {self._token.get_secret_value()}",
        }
        if body is not None:
            headers["Content-Type"] = _JSON_CONTENT_TYPE
        try:
            return self._transport.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                body=body,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise WavelogConnectionError("Wavelog could not be reached.") from error

    @staticmethod
    def _decode_json(body: bytes, *, operation: str) -> object:
        try:
            return loads(body.decode("utf-8"))
        except (UnicodeDecodeError, JSONDecodeError) as error:
            raise WavelogResponseError(
                f"Wavelog {operation} returned invalid JSON."
            ) from error

    @staticmethod
    def _raise_http_error(status_code: int, operation: str) -> None:
        if status_code in {401, 403}:
            raise WavelogAuthenticationError(
                f"Wavelog {operation} rejected the configured token (HTTP {status_code})."
            )
        raise WavelogResponseError(f"Wavelog {operation} returned HTTP {status_code}.")

    @staticmethod
    def _validate_base_url(base_url: str) -> str:
        normalized = base_url.strip().rstrip("/")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Wavelog base URL must be an absolute http or https URL.")
        if parsed.params or parsed.query or parsed.fragment:
            raise ValueError(
                "Wavelog base URL must not contain parameters, a query, or a fragment."
            )
        return normalized


def contact_to_adif(contact: Contact) -> str:
    """Map a Rolling Thunder contact into one deterministic ADIF record."""
    try:
        band = resolve_radio_band(Frequency(hz=contact.frequency_hz)).value
    except RadioBandResolutionError as error:
        raise WavelogResponseError(
            f"Contact frequency {contact.frequency_hz} Hz does not map to a supported band."
        ) from error

    mode, submode = _adif_mode(contact.mode)
    started_at = contact.started_at.astimezone(UTC)
    frequency_mhz = f"{contact.frequency_hz / 1_000_000:.6f}".rstrip("0").rstrip(".")
    fields: list[tuple[str, str]] = [
        ("CALL", str(contact.callsign)),
        ("BAND", band),
        ("MODE", mode),
        ("FREQ", frequency_mhz),
        ("QSO_DATE", started_at.strftime("%Y%m%d")),
        ("TIME_ON", started_at.strftime("%H%M%S")),
        ("RST_SENT", contact.rst_sent),
        ("RST_RCVD", contact.rst_received),
    ]
    if submode is not None:
        fields.append(("SUBMODE", submode))
    if contact.grid is not None:
        fields.append(("GRIDSQUARE", str(contact.grid)))
    if contact.my_grid is not None:
        fields.append(("MY_GRIDSQUARE", str(contact.my_grid)))
    if contact.pota_reference is not None:
        fields.append(("POTA_REF", str(contact.pota_reference)))
    if contact.notes is not None:
        fields.append(("NOTES", contact.notes))

    return "".join(_adif_field(name, value) for name, value in fields) + "<EOR>"


def _adif_mode(mode: RadioMode) -> tuple[str, str | None]:
    if mode is RadioMode.USB:
        return "SSB", "USB"
    if mode is RadioMode.LSB:
        return "SSB", "LSB"
    return mode.value, None


def _adif_field(name: str, value: str) -> str:
    return f"<{name}:{len(value)}>{value}"
