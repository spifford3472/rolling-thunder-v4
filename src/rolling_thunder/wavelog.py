"""Typed Wavelog v2 adapter used only by Forge contact synchronization."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from json import JSONDecodeError, dumps, loads
from typing import Any, Protocol
from urllib.error import URLError
from urllib.parse import urlencode, urlparse

from pydantic import SecretStr

from rolling_thunder.domain import Contact, Frequency, RadioMode
from rolling_thunder.http_home_platform import (
    HttpResponse,
    HttpTransport,
    UrllibHttpTransport,
)
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band

_JSON_CONTENT_TYPE = "application/json"
_UNKNOWN_MOBILE_STATION_NAME = "Mobile - Unknown Location"


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


class WavelogLogbookError(WavelogError):
    """Raised when the configured station logbook cannot be verified safely."""


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
    callsign: str | None = None
    dxcc: int | None = None
    cq: int | None = None
    itu: int | None = None
    state: str = ""


@dataclass(frozen=True, slots=True)
class WavelogLogbook:
    """One owner-scoped Wavelog logbook and its complete station membership."""

    logbook_id: int
    name: str
    station_ids: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class WavelogStationTarget:
    """Verified exact QSO target selected before the idempotency claim."""

    location: WavelogStationLocation
    dynamic: bool


@dataclass(frozen=True, slots=True)
class WavelogStationBinding:
    """Durable Forge recovery identity for one verified dynamic station."""

    name: str
    station_id: int
    uuid: str


class WavelogStationBindingStore(Protocol):
    """Narrow durable recovery boundary used by dynamic station routing."""

    def get_station_binding(self, name: str) -> WavelogStationBinding | None: ...

    def bind_station(self, binding: WavelogStationBinding) -> None: ...


@dataclass(frozen=True, slots=True)
class WavelogQsoSummary:
    """Compact historical QSO data needed by callsign information."""

    callsign: str
    qso_id: int | str | None
    station_id: int | None
    occurred_at: datetime | None
    comments: str | None
    notes: str | None
    qth: str | None
    grid: str | None
    pota_reference: str | None
    my_pota_reference: str | None


class WavelogClient:
    """Synchronous Wavelog v2 client intended for Forge request threads."""

    def __init__(
        self,
        base_url: str,
        token: SecretStr,
        *,
        station_location_name: str,
        station_logbook_name: str | None = None,
        timeout_s: float = 5.0,
        transport: HttpTransport | None = None,
        station_binding_store: WavelogStationBindingStore | None = None,
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
        self._station_logbook_name = (
            station_logbook_name.strip() if station_logbook_name is not None else None
        )
        if station_logbook_name is not None and not self._station_logbook_name:
            raise ValueError("Wavelog station logbook name must not be blank.")
        self._timeout_s = timeout_s
        self._transport = transport or UrllibHttpTransport()
        self._station_binding_store = station_binding_store
        self._resolved_location: WavelogStationLocation | None = None

    def resolve_station_location(self, *, refresh: bool = False) -> WavelogStationLocation:
        """Resolve exactly one configured station location without guessing its numeric ID."""
        if self._resolved_location is not None and not refresh:
            return self._resolved_location
        location = self.resolve_exact_station_location(
            self._station_location_name,
            self.list_station_locations(),
        )
        if location is None:
            raise WavelogStationLocationError(
                "Configured Wavelog station location does not exist: "
                f"{self._station_location_name!r}."
            )
        self._resolved_location = location
        return location

    def list_station_locations(self) -> tuple[WavelogStationLocation, ...]:
        """Return normalized owner-scoped station profiles."""
        response = self._request("GET", "/index.php/api/v2/station", body=None)
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "station-location lookup")
        payload = self._decode_json(response.body, operation="station-location lookup")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise WavelogResponseError(
                "Wavelog station-location lookup returned an unexpected response schema."
            )

        return tuple(
            self._parse_station(item, operation="station-location lookup")
            for item in payload["data"]
        )

    @staticmethod
    def resolve_exact_station_location(
        name: str,
        locations: tuple[WavelogStationLocation, ...],
    ) -> WavelogStationLocation | None:
        """Return an exact unique name match, distinguishing absence from ambiguity."""
        matches = tuple(location for location in locations if location.name == name)
        if len(matches) > 1:
            raise WavelogStationLocationError(
                "Wavelog station location name is ambiguous; refusing to guess an ID: "
                f"{name!r}."
            )
        return matches[0] if matches else None

    def list_logbooks(self) -> tuple[WavelogLogbook, ...]:
        """Return normalized owner-scoped station logbooks."""
        response = self._request("GET", "/index.php/api/v2/logbook", body=None)
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "station-logbook lookup")
        payload = self._decode_json(response.body, operation="station-logbook lookup")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise WavelogResponseError(
                "Wavelog station-logbook lookup returned an unexpected response schema."
            )
        return tuple(
            self._parse_logbook(item, operation="station-logbook lookup")
            for item in payload["data"]
        )

    def resolve_station_logbook(self) -> WavelogLogbook:
        """Resolve the one configured logbook by exact name."""
        if self._station_logbook_name is None:
            raise WavelogLogbookError("Wavelog station logbook name is not configured.")
        matches = tuple(
            item for item in self.list_logbooks() if item.name == self._station_logbook_name
        )
        if len(matches) != 1:
            raise WavelogLogbookError(
                "Configured Wavelog station logbook must resolve to exactly one owned "
                f"logbook named {self._station_logbook_name!r}; found {len(matches)}."
            )
        return matches[0]

    def resolve_station_target(self, contact: Contact) -> WavelogStationTarget:
        """Resolve/create/link the exact station target using only frozen Contact data."""
        locations = self.list_station_locations()
        legacy = self.resolve_exact_station_location(self._station_location_name, locations)
        if legacy is None:
            raise WavelogStationLocationError(
                "Configured legacy Wavelog station location does not exist: "
                f"{self._station_location_name!r}."
            )
        self._verify_template_station(legacy)
        self._resolved_location = legacy
        logbook = self.resolve_station_logbook()

        dynamic_identity = _dynamic_station_identity(contact)
        if dynamic_identity is None:
            return self._resolve_unknown_station(
                locations=locations,
                template=legacy,
                logbook=logbook,
            )

        name, grid, state, cq, itu = dynamic_identity
        binding = self._get_station_binding(name)
        dynamic = self.resolve_exact_station_location(name, locations)
        if dynamic is not None:
            self._verify_dynamic_station(
                dynamic,
                name=name,
                grid=grid,
                state=state,
                cq=cq,
                itu=itu,
                template=legacy,
            )
            if binding is not None and (
                dynamic.station_id != binding.station_id
                or dynamic.uuid != binding.uuid
            ):
                raise WavelogStationLocationError(
                    "Visible exact-name Wavelog station conflicts with the durable "
                    "Forge binding; refusing to overwrite or guess."
                )
            self._bind_verified_station(dynamic)
        elif binding is not None:
            dynamic = self._resolve_bound_station(
                binding,
                grid=grid,
                state=state,
                cq=cq,
                itu=itu,
                template=legacy,
            )
        else:
            dynamic = self._create_dynamic_station(
                name=name,
                grid=grid,
                state=state,
                cq=cq,
                itu=itu,
                template=legacy,
                prior_binding=binding,
            )
        self._verify_dynamic_station(
            dynamic,
            name=name,
            grid=grid,
            state=state,
            cq=cq,
            itu=itu,
            template=legacy,
        )
        if dynamic.station_id not in logbook.station_ids:
            self._link_station_to_logbook(dynamic.station_id, logbook)
        return WavelogStationTarget(location=dynamic, dynamic=True)

    def verify_health_target(self) -> None:
        """Read-only validation of the configured legacy target and logbook membership."""
        legacy = self.resolve_station_location(refresh=True)
        self._verify_template_station(legacy)
        logbook = self.resolve_station_logbook()
        if legacy.station_id not in logbook.station_ids:
            raise WavelogLogbookError(
                "Configured legacy Wavelog station location is not linked to the "
                f"configured logbook {logbook.name!r}."
            )

    def _resolve_unknown_station(
        self,
        *,
        locations: tuple[WavelogStationLocation, ...],
        template: WavelogStationLocation,
        logbook: WavelogLogbook,
    ) -> WavelogStationTarget:
        """Resolve/create/link the location-neutral mobile fallback station."""
        name = _UNKNOWN_MOBILE_STATION_NAME
        binding = self._get_station_binding(name)
        unknown = self.resolve_exact_station_location(name, locations)
        if unknown is not None:
            self._verify_unknown_station(unknown, template=template)
            if binding is not None and (
                unknown.station_id != binding.station_id or unknown.uuid != binding.uuid
            ):
                raise WavelogStationLocationError(
                    "Visible unknown-location station conflicts with the durable Forge binding."
                )
            self._bind_verified_station(unknown)
        elif binding is not None:
            unknown = self._resolve_bound_unknown_station(binding, template=template)
        else:
            unknown = self._create_unknown_station(template=template)
        self._verify_unknown_station(unknown, template=template)
        if unknown.station_id not in logbook.station_ids:
            self._link_station_to_logbook(unknown.station_id, logbook)
        return WavelogStationTarget(location=unknown, dynamic=True)

    def _create_unknown_station(
        self,
        *,
        template: WavelogStationLocation,
    ) -> WavelogStationLocation:
        body = dumps(
            {
                "name": _UNKNOWN_MOBILE_STATION_NAME,
                "callsign": template.callsign,
                "dxcc": template.dxcc,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request("POST", "/index.php/api/v2/station", body=body)
        if response.status_code == 409:
            locations = self.list_station_locations()
            raced = self.resolve_exact_station_location(
                _UNKNOWN_MOBILE_STATION_NAME, locations
            )
            if raced is not None:
                self._verify_unknown_station(raced, template=template)
                self._bind_verified_station(raced)
                return raced
            binding = self._get_station_binding(_UNKNOWN_MOBILE_STATION_NAME)
            if binding is not None:
                return self._resolve_bound_unknown_station(binding, template=template)
            raise WavelogStationLocationError(
                "Wavelog reported an unknown-location station creation conflict, but "
                "no visible exact match or durable binding can resolve it safely."
            )
        if response.status_code != 201:
            self._raise_http_error(response.status_code, "unknown station-location creation")
        payload = self._decode_json(
            response.body, operation="unknown station-location creation"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise WavelogResponseError(
                "Wavelog unknown station-location creation returned an unexpected response schema."
            )
        created = self._parse_station(
            payload["data"], operation="unknown station-location creation"
        )
        self._verify_unknown_station(created, template=template)
        self._bind_verified_station(created)
        return created

    def _resolve_bound_unknown_station(
        self,
        binding: WavelogStationBinding,
        *,
        template: WavelogStationLocation,
    ) -> WavelogStationLocation:
        bound = self.get_station_location(binding.station_id)
        if bound.name != binding.name or bound.uuid != binding.uuid:
            raise WavelogStationLocationError(
                "Durable unknown-location station binding no longer matches Wavelog."
            )
        self._verify_unknown_station(bound, template=template)
        self._bind_verified_station(bound)
        return bound

    def _create_dynamic_station(
        self,
        *,
        name: str,
        grid: str,
        state: str,
        cq: int,
        itu: int,
        template: WavelogStationLocation,
        prior_binding: WavelogStationBinding | None,
    ) -> WavelogStationLocation:
        body = dumps(
            {
                "name": name,
                "callsign": template.callsign,
                "dxcc": template.dxcc,
                "cq": cq,
                "itu": itu,
                "gridsquare": grid,
                "state": state,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request("POST", "/index.php/api/v2/station", body=body)
        if response.status_code == 409:
            locations = self.list_station_locations()
            raced = self.resolve_exact_station_location(name, locations)
            if raced is not None:
                self._verify_dynamic_station(
                    raced,
                    name=name,
                    grid=grid,
                    state=state,
                    cq=cq,
                    itu=itu,
                    template=template,
                )
                self._bind_verified_station(raced)
                return raced
            recovery_binding = prior_binding or self._get_station_binding(name)
            if recovery_binding is not None:
                return self._resolve_bound_station(
                    recovery_binding,
                    grid=grid,
                    state=state,
                    cq=cq,
                    itu=itu,
                    template=template,
                )
            else:
                raise WavelogStationLocationError(
                    "Wavelog reported a station creation conflict, but its response did "
                    "not identify the station and no visible exact match or prior verified "
                    "Forge binding can resolve it safely; refusing to guess an ID."
                )
        if response.status_code != 201:
            self._raise_http_error(response.status_code, "station-location creation")
        payload = self._decode_json(response.body, operation="station-location creation")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise WavelogResponseError(
                "Wavelog station-location creation returned an unexpected response schema."
            )
        created = self._parse_station(payload["data"], operation="station-location creation")
        self._verify_dynamic_station(
            created,
            name=name,
            grid=grid,
            state=state,
            cq=cq,
            itu=itu,
            template=template,
        )
        self._bind_verified_station(created)
        return created

    def _get_station_binding(self, name: str) -> WavelogStationBinding | None:
        store = self._station_binding_store
        return None if store is None else store.get_station_binding(name)

    def _bind_verified_station(self, location: WavelogStationLocation) -> None:
        store = self._station_binding_store
        if store is None:
            raise WavelogStationLocationError(
                "Durable Forge station binding storage is required for dynamic routing."
            )
        if location.uuid is None:
            raise WavelogStationLocationError(
                "Verified dynamic Wavelog station location lacks a UUID."
            )
        store.bind_station(
            WavelogStationBinding(location.name, location.station_id, location.uuid)
        )

    def _resolve_bound_station(
        self,
        binding: WavelogStationBinding,
        *,
        grid: str,
        state: str,
        cq: int,
        itu: int,
        template: WavelogStationLocation,
    ) -> WavelogStationLocation:
        bound = self.get_station_location(binding.station_id)
        if bound.name != binding.name or bound.uuid != binding.uuid:
            raise WavelogStationLocationError(
                "Durable Forge station binding no longer matches the Wavelog station "
                "identity; refusing to overwrite or guess."
            )
        self._verify_dynamic_station(
            bound,
            name=binding.name,
            grid=grid,
            state=state,
            cq=cq,
            itu=itu,
            template=template,
        )
        self._bind_verified_station(bound)
        return bound

    def get_station_location(self, station_id: int) -> WavelogStationLocation:
        """Fetch one known owned station directly, bypassing the filtered list."""
        response = self._request(
            "GET",
            f"/index.php/api/v2/station/{station_id}",
            body=None,
        )
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "direct station-location lookup")
        payload = self._decode_json(
            response.body,
            operation="direct station-location lookup",
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise WavelogResponseError(
                "Wavelog direct station-location lookup returned an unexpected response schema."
            )
        location = self._parse_station(
            payload["data"],
            operation="direct station-location lookup",
        )
        if location.station_id != station_id:
            raise WavelogResponseError(
                "Wavelog direct station-location lookup returned a different station ID."
            )
        return location

    def _link_station_to_logbook(
        self,
        station_id: int,
        logbook: WavelogLogbook,
    ) -> None:
        prior_ids = logbook.station_ids
        replacement_ids = (*prior_ids, station_id)
        body = dumps(
            {"station_ids": list(replacement_ids)},
            separators=(",", ":"),
        ).encode("utf-8")
        response = self._request(
            "PATCH",
            f"/index.php/api/v2/logbook/{logbook.logbook_id}",
            body=body,
        )
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "station-logbook membership update")
        payload = self._decode_json(
            response.body,
            operation="station-logbook membership update",
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), dict):
            raise WavelogResponseError(
                "Wavelog station-logbook membership update returned an unexpected "
                "response schema."
            )
        patched = self._parse_logbook(
            payload["data"],
            operation="station-logbook membership update",
        )
        self._verify_logbook_membership(patched, logbook, station_id)

        verified = self.resolve_station_logbook()
        self._verify_logbook_membership(verified, logbook, station_id)

    @staticmethod
    def _verify_logbook_membership(
        candidate: WavelogLogbook,
        original: WavelogLogbook,
        station_id: int,
    ) -> None:
        if candidate.logbook_id != original.logbook_id or candidate.name != original.name:
            raise WavelogLogbookError(
                "Wavelog station-logbook membership update changed the target identity."
            )
        if station_id not in candidate.station_ids or not set(original.station_ids).issubset(
            candidate.station_ids
        ):
            raise WavelogLogbookError(
                "Wavelog station-logbook membership verification did not preserve all "
                "existing station IDs and add the requested station."
            )

    @staticmethod
    def _verify_template_station(location: WavelogStationLocation) -> None:
        if (
            not location.uuid
            or not location.callsign
            or location.dxcc is None
            or location.cq is None
            or location.itu is None
        ):
            raise WavelogStationLocationError(
                "Configured legacy Wavelog station location lacks verified template "
                "identity metadata."
            )

    @classmethod
    def _verify_unknown_station(
        cls,
        location: WavelogStationLocation,
        *,
        template: WavelogStationLocation,
    ) -> None:
        if (
            not location.uuid
            or not location.callsign
            or location.dxcc is None
            or location.name != _UNKNOWN_MOBILE_STATION_NAME
            or location.gridsquare
            or location.state
            or location.cq is not None
            or location.itu is not None
            or location.callsign != template.callsign
            or location.dxcc != template.dxcc
        ):
            raise WavelogStationLocationError(
                "Unknown-location Wavelog station has incompatible metadata."
            )

    @classmethod
    def _verify_dynamic_station(
        cls,
        location: WavelogStationLocation,
        *,
        name: str,
        grid: str,
        state: str,
        cq: int,
        itu: int,
        template: WavelogStationLocation,
    ) -> None:
        cls._verify_template_station(location)
        if (
            location.name != name
            or location.gridsquare != grid
            or location.state != state
            or location.cq != cq
            or location.itu != itu
            or location.callsign != template.callsign
            or location.dxcc != template.dxcc
        ):
            raise WavelogStationLocationError(
                "Exact-name Wavelog dynamic station location has incompatible metadata; "
                "refusing to reuse or mutate it."
            )

    @classmethod
    def _parse_station(cls, item: object, *, operation: str) -> WavelogStationLocation:
        if not isinstance(item, dict):
            raise WavelogResponseError(f"Wavelog {operation} returned an invalid station.")
        station_id = cls._positive_int(item.get("id"))
        name = cls._required_text(item.get("name"))
        callsign = cls._required_text(item.get("callsign"), uppercase=True)
        gridsquare = cls._optional_text(item.get("gridsquare")) or ""
        station_uuid = cls._required_text(item.get("uuid"))
        dxcc = cls._positive_int(item.get("dxcc"))
        cq = cls._positive_int(item.get("cq"))
        itu = cls._positive_int(item.get("itu"))
        state_raw = item.get("state") or ""
        if not isinstance(state_raw, str):
            raise WavelogResponseError(
                f"Wavelog {operation} returned invalid station metadata."
            )
        if (
            station_id is None
            or name is None
            or callsign is None
            or station_uuid is None
            or dxcc is None
        ):
            raise WavelogResponseError(
                f"Wavelog {operation} returned incomplete station identity metadata."
            )
        return WavelogStationLocation(
            station_id=station_id,
            name=name,
            gridsquare=gridsquare.upper(),
            uuid=station_uuid,
            callsign=callsign,
            dxcc=dxcc,
            cq=cq,
            itu=itu,
            state=state_raw.strip().upper(),
        )

    @classmethod
    def _parse_logbook(cls, item: object, *, operation: str) -> WavelogLogbook:
        if not isinstance(item, dict):
            raise WavelogResponseError(f"Wavelog {operation} returned an invalid logbook.")
        logbook_id = cls._positive_int(item.get("id"))
        name = cls._required_text(item.get("name"))
        raw_station_ids = item.get("station_ids")
        if logbook_id is None or name is None or not isinstance(raw_station_ids, list):
            raise WavelogResponseError(
                f"Wavelog {operation} returned incomplete logbook identity metadata."
            )
        station_ids: list[int] = []
        for raw_station_id in raw_station_ids:
            station_id = cls._positive_int(raw_station_id)
            if station_id is None or station_id in station_ids:
                raise WavelogResponseError(
                    f"Wavelog {operation} returned invalid logbook station IDs."
                )
            station_ids.append(station_id)
        return WavelogLogbook(logbook_id, name, tuple(station_ids))

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return None
        return value

    @staticmethod
    def _required_text(value: object, *, uppercase: bool = False) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None
        normalized = value.strip()
        return normalized.upper() if uppercase else normalized

    def latest_qso(self, callsign: str) -> WavelogQsoSummary | None:
        """Return the newest exact-callsign QSO, or none when never worked."""
        normalized = callsign.strip().upper()
        if not normalized:
            raise ValueError("Wavelog callsign lookup must not be blank.")
        query = urlencode({"callsign": normalized, "limit": 1})
        response = self._request(
            "GET",
            f"/index.php/api/v2/qso?{query}",
            body=None,
        )
        if not 200 <= response.status_code < 300:
            self._raise_http_error(response.status_code, "QSO history lookup")
        payload = self._decode_json(response.body, operation="QSO history lookup")
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            raise WavelogResponseError(
                "Wavelog QSO history lookup returned an unexpected response schema."
            )
        if not payload["data"]:
            return None

        item = payload["data"][0]
        if not isinstance(item, dict):
            raise WavelogResponseError(
                "Wavelog QSO history lookup returned an invalid QSO record."
            )
        returned_callsign = self._optional_text(item.get("call")) or normalized
        if returned_callsign.strip().upper() != normalized:
            raise WavelogResponseError(
                "Wavelog QSO history lookup returned a different callsign."
            )

        station_raw = item.get("station_id")
        station_id = (
            station_raw
            if isinstance(station_raw, int) and not isinstance(station_raw, bool)
            else None
        )
        qso_id_raw = item.get("id")
        qso_id = qso_id_raw if isinstance(qso_id_raw, (int, str)) else None

        return WavelogQsoSummary(
            callsign=normalized,
            qso_id=qso_id,
            station_id=station_id,
            occurred_at=self._parse_qso_datetime(item),
            comments=self._optional_text(item.get("comment"))
            or self._optional_text(item.get("comments")),
            notes=self._optional_text(item.get("notes")),
            qth=self._optional_text(item.get("qth")),
            grid=self._optional_text(item.get("gridsquare")),
            pota_reference=self._optional_text(item.get("pota_ref")),
            my_pota_reference=self._optional_text(item.get("my_pota_ref")),
        )

    def upload_contact(
        self,
        contact: Contact,
        *,
        target: WavelogStationTarget,
    ) -> WavelogUploadDisposition:
        """Import one contact into its preselected exact station target."""
        location = target.location
        if not target.dynamic:
            location = self._align_station_location_grid(location, contact)
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
        station_uuid = data.get("uuid")
        if station_grid is None:
            station_grid = ""
        if (
            station_id != location.station_id
            or name != location.name
            or not isinstance(station_uuid, str)
            or station_uuid.strip() != location.uuid
            or not isinstance(station_grid, str)
            or station_grid.strip().upper() != desired_grid
        ):
            raise WavelogResponseError(
                "Wavelog station-location grid update did not confirm the requested target."
            )

        updated_location = WavelogStationLocation(
            station_id=location.station_id,
            name=location.name,
            gridsquare=desired_grid,
            uuid=location.uuid,
            callsign=location.callsign,
            dxcc=location.dxcc,
            cq=location.cq,
            itu=location.itu,
            state=location.state,
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
    def _optional_text(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    @classmethod
    def _parse_qso_datetime(cls, item: dict[str, Any]) -> datetime | None:
        """Parse common Wavelog v2 QSO date/time shapes without guessing."""
        for key in ("qso_date_time", "datetime", "date_time", "start"):
            value = cls._optional_text(item.get(key))
            if value is None:
                continue
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                continue
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed.astimezone(UTC)

        date_value = cls._optional_text(item.get("qso_date"))
        time_value = cls._optional_text(item.get("time_on"))
        if date_value is None:
            return None

        # Wavelog v2 normally returns qso_date as one combined timestamp,
        # for example "2026-06-16 17:06:00". Preserve compatibility with
        # date-only/ADIF-shaped payloads that carry time_on separately.
        try:
            parsed_date = datetime.fromisoformat(date_value)
        except ValueError:
            parsed_date = None
        if parsed_date is not None and (
            " " in date_value or "T" in date_value
        ):
            if parsed_date.tzinfo is None or parsed_date.utcoffset() is None:
                parsed_date = parsed_date.replace(tzinfo=UTC)
            return parsed_date.astimezone(UTC)

        digits_date = date_value.replace("-", "")
        digits_time = (time_value or "000000").replace(":", "")
        if len(digits_time) == 4:
            digits_time += "00"
        try:
            return datetime.strptime(
                f"{digits_date}{digits_time[:6]}",
                "%Y%m%d%H%M%S",
            ).replace(tzinfo=UTC)
        except ValueError:
            return None

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
    notes = contact.notes
    fields.append(("NOTES", "Mobile QSO" if notes is None or not notes.strip() else notes))

    return "".join(_adif_field(name, value) for name, value in fields) + "<EOR>"


def _adif_mode(mode: RadioMode) -> tuple[str, str | None]:
    if mode is RadioMode.FT8:
        return "FT8", None
    if mode is RadioMode.USB:
        return "SSB", "USB"
    if mode is RadioMode.LSB:
        return "SSB", "LSB"
    if mode is RadioMode.DMR:
        return "DIGITALVOICE", "DMR"
    return mode.value, None


def _adif_field(name: str, value: str) -> str:
    return f"<{name}:{len(value)}>{value}"


def _dynamic_station_identity(
    contact: Contact,
) -> tuple[str, str, str, int, int] | None:
    """Return a deterministic identity only when all frozen routing data is usable."""
    if (
        contact.my_grid is None
        or contact.my_state is None
        or contact.my_cq_zone is None
        or contact.my_itu_zone is None
    ):
        return None
    grid = str(contact.my_grid).strip().upper()[:4]
    state = contact.my_state.strip().upper()
    if len(grid) != 4 or len(state) != 2:
        return None
    return (
        f"Mobile - {grid} - {state}",
        grid,
        state,
        contact.my_cq_zone,
        contact.my_itu_zone,
    )
