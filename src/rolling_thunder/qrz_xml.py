"""QRZ XML callsign profile adapter with reusable authenticated sessions."""

from dataclasses import dataclass
from threading import Lock
from urllib.error import URLError
from urllib.parse import urlencode
from xml.etree import ElementTree

from pydantic import TypeAdapter, ValidationError

from rolling_thunder.application_secrets import QrzCredentials
from rolling_thunder.http_home_platform import HttpTransport, UrllibHttpTransport
from rolling_thunder.value_types import Callsign, MaidenheadGrid

_QRZ_XML_ENDPOINT = "https://xmldata.qrz.com/xml/current/"
_AGENT = "RollingThunder-v4.1"
_XML_ACCEPT = "application/xml,text/xml"
_GRID_ADAPTER = TypeAdapter(MaidenheadGrid)


class QrzLookupError(Exception):
    """Base exception for QRZ callsign lookup failures."""


class QrzConnectionError(QrzLookupError):
    """Raised when the QRZ XML service cannot be reached."""


class QrzResponseError(QrzLookupError):
    """Raised when the QRZ XML service returns unusable data."""


class QrzAuthenticationError(QrzLookupError):
    """Raised when QRZ authentication does not produce a session key."""


@dataclass(frozen=True)
class QrzCallsignProfile:
    """Normalized presentation metadata returned for one QRZ callsign record."""

    callsign: str
    name: str | None
    image_url: str | None
    grid: MaidenheadGrid | None = None
    address1: str | None = None
    address2: str | None = None
    state: str | None = None
    country: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    geoloc: str | None = None
    license_class: str | None = None
    license_effective_date: str | None = None
    license_expiration_date: str | None = None
    birth_year: int | None = None


def normalize_qrz_callsign(callsign: Callsign | str) -> str:
    """Remove an optional portable suffix before a QRZ lookup."""
    normalized = str(callsign).strip().upper()
    return normalized.split("/", 1)[0]


class QrzXmlCallsignNameProvider:
    """Synchronous QRZ XML adapter intended for background-worker use."""

    def __init__(
        self,
        credentials: QrzCredentials,
        *,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        endpoint: str = _QRZ_XML_ENDPOINT,
    ) -> None:
        if timeout_s <= 0:
            raise ValueError("QRZ HTTP timeout must be positive.")
        self._credentials = credentials
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._endpoint = endpoint
        self._session_key: str | None = None
        self._lock = Lock()

    def lookup_name(self, callsign: Callsign | str) -> str | None:
        """Return a display name, or none when QRZ has no usable name."""
        profile = self.lookup_profile(callsign)
        return profile.name if profile is not None else None

    def lookup_profile(self, callsign: Callsign | str) -> QrzCallsignProfile | None:
        """Return QRZ name and optional primary-image URL for one callsign."""
        query_callsign = normalize_qrz_callsign(callsign)
        with self._lock:
            return self._lookup_locked(query_callsign, allow_relogin=True)

    def _lookup_locked(
        self,
        callsign: str,
        *,
        allow_relogin: bool,
    ) -> QrzCallsignProfile | None:
        session_key = self._session_key or self._login()
        root = self._request_xml(
            {
                "s": session_key,
                "callsign": callsign,
            },
            operation="callsign lookup",
        )

        callsign_node = self._first_node(root, "Callsign")
        if callsign_node is not None:
            first_name = self._child_text(callsign_node, "fname")
            last_name = self._child_text(callsign_node, "name")
            display_name = self._format_name(first_name, last_name)
            returned_callsign = self._child_text(callsign_node, "call") or callsign
            image_url = self._child_text(callsign_node, "image")
            grid = self._validated_grid(self._child_text(callsign_node, "grid"))
            latitude = self._validated_coordinate(
                self._child_text(callsign_node, "lat"),
                minimum=-90.0,
                maximum=90.0,
            )
            longitude = self._validated_coordinate(
                self._child_text(callsign_node, "lon"),
                minimum=-180.0,
                maximum=180.0,
            )
            self._refresh_session_key(root)
            return QrzCallsignProfile(
                callsign=returned_callsign,
                name=display_name,
                image_url=image_url,
                grid=grid,
                address1=self._child_text(callsign_node, "addr1"),
                address2=self._child_text(callsign_node, "addr2"),
                state=self._child_text(callsign_node, "state"),
                country=self._child_text(callsign_node, "country"),
                latitude=latitude,
                longitude=longitude,
                geoloc=self._child_text(callsign_node, "geoloc"),
                license_class=self._child_text(callsign_node, "class"),
                license_effective_date=self._child_text(callsign_node, "efdate"),
                license_expiration_date=self._child_text(callsign_node, "expdate"),
                birth_year=self._validated_birth_year(
                    self._child_text(callsign_node, "born")
                ),
            )

        error = self._session_text(root, "Error")
        self._refresh_session_key(root)
        if error is not None and self._is_not_found(error):
            return None

        if allow_relogin and self._session_key is None:
            return self._lookup_locked(callsign, allow_relogin=False)

        if error:
            raise QrzResponseError(f"QRZ callsign lookup failed: {error}")
        raise QrzResponseError("QRZ callsign lookup returned no callsign record.")

    def _login(self) -> str:
        root = self._request_xml(
            {
                "username": self._credentials.username,
                "password": self._credentials.password.get_secret_value(),
                "agent": _AGENT,
            },
            operation="authentication",
        )
        key = self._session_text(root, "Key")
        if key is None:
            error = self._session_text(root, "Error")
            if error:
                raise QrzAuthenticationError(f"QRZ authentication failed: {error}")
            raise QrzAuthenticationError("QRZ authentication did not return a session key.")
        self._session_key = key
        return key

    def _request_xml(
        self,
        parameters: dict[str, str],
        *,
        operation: str,
    ) -> ElementTree.Element:
        url = f"{self._endpoint}?{urlencode(parameters)}"
        try:
            response = self._transport.request(
                "GET",
                url,
                headers={"Accept": _XML_ACCEPT, "User-Agent": _AGENT},
                body=None,
                timeout_s=self._timeout_s,
            )
        except (TimeoutError, URLError, OSError) as error:
            raise QrzConnectionError(f"QRZ {operation} could not be completed.") from error

        if not 200 <= response.status_code < 300:
            raise QrzConnectionError(f"QRZ {operation} returned HTTP {response.status_code}.")

        try:
            return ElementTree.fromstring(response.body)
        except ElementTree.ParseError as error:
            raise QrzResponseError(f"QRZ {operation} returned invalid XML.") from error

    def _refresh_session_key(self, root: ElementTree.Element) -> None:
        key = self._session_text(root, "Key")
        self._session_key = key

    @classmethod
    def _session_text(cls, root: ElementTree.Element, name: str) -> str | None:
        session = cls._first_node(root, "Session")
        if session is None:
            return None
        return cls._child_text(session, name)

    @staticmethod
    def _first_node(
        root: ElementTree.Element,
        local_name: str,
    ) -> ElementTree.Element | None:
        for node in root.iter():
            if node.tag.rsplit("}", 1)[-1] == local_name:
                return node
        return None

    @staticmethod
    def _child_text(node: ElementTree.Element, local_name: str) -> str | None:
        for child in node:
            if child.tag.rsplit("}", 1)[-1] != local_name:
                continue
            if child.text is None:
                return None
            normalized = child.text.strip()
            return normalized or None
        return None

    @staticmethod
    def _validated_grid(value: str | None) -> MaidenheadGrid | None:
        """Return a normalized QRZ grid, ignoring unusable values."""
        if value is None:
            return None
        try:
            return _GRID_ADAPTER.validate_python(value)
        except ValidationError:
            return None

    @staticmethod
    def _validated_coordinate(
        value: str | None,
        *,
        minimum: float,
        maximum: float,
    ) -> float | None:
        """Return one bounded QRZ coordinate without failing the whole profile."""
        if value is None:
            return None
        try:
            coordinate = float(value)
        except ValueError:
            return None
        if not minimum <= coordinate <= maximum:
            return None
        return coordinate

    @staticmethod
    def _validated_birth_year(value: str | None) -> int | None:
        """Return QRZ's optional four-digit birth year when plausible."""
        if value is None or len(value) != 4 or not value.isdigit():
            return None
        year = int(value)
        return year if 1900 <= year <= 2100 else None

    @staticmethod
    def _is_not_found(message: str) -> bool:
        normalized = message.casefold()
        return "not found" in normalized or "no callsign" in normalized

    @staticmethod
    def _format_name(first_name: str | None, last_name: str | None) -> str | None:
        parts = [part for part in (first_name, last_name) if part]
        if not parts:
            return None
        name = " ".join(" ".join(parts).split())
        if name.isupper():
            return name.title()
        return name
