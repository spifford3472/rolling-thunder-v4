"""Private HTTP API for on-demand Forge callsign intelligence."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps
from urllib.parse import parse_qs, unquote, urlsplit

from rolling_thunder.callsign_info import CallsignInfoResponse
from rolling_thunder.forge_callsign_info import ForgeCallsignInfoService
from rolling_thunder.qrz_xml import QrzLookupError
from rolling_thunder.wavelog import WavelogError

_JSON = "application/json; charset=utf-8"
_PREFIX = "/api/v1/contact-intelligence/"
_LOGGER = logging.getLogger("rolling_thunder.forge_callsign_info")


@dataclass(frozen=True, slots=True)
class ForgeCallsignInfoHttpResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class ForgeCallsignInfoApiApplication:
    """Bounded router over the independent callsign-info service."""

    def __init__(self, service: ForgeCallsignInfoService) -> None:
        self._service = service

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeCallsignInfoHttpResponse:
        del headers, body
        if method.strip().upper() != "GET":
            return self._error(405, "method_not_allowed", "Only GET is supported.", allow="GET")

        parsed = urlsplit(target)
        if parsed.path == "/health":
            return self._json(200, {"status": "healthy"})
        if not parsed.path.startswith(_PREFIX):
            return self._error(404, "not_found", "Callsign-info path does not exist.")

        callsign = unquote(parsed.path[len(_PREFIX):]).strip().upper()
        if not callsign or "/" in callsign:
            return self._error(400, "invalid_callsign", "A single callsign is required.")

        query = parse_qs(parsed.query, keep_blank_values=False)
        try:
            latitude = _optional_float(query.get("latitude"))
            longitude = _optional_float(query.get("longitude"))
        except ValueError:
            return self._error(400, "invalid_location", "Latitude/longitude must be numeric.")

        source_values = query.get("source", [])
        source = source_values[0].strip().lower() if source_values else None
        if source not in {None, "pota"}:
            return self._error(400, "invalid_source", "Location source must be 'pota'.")
        if (latitude is None) != (longitude is None):
            return self._error(
                400,
                "invalid_location",
                "Latitude and longitude must be supplied together.",
            )
        if source == "pota" and latitude is None:
            return self._error(
                400,
                "invalid_location",
                "POTA source requires latitude and longitude.",
            )

        try:
            response: CallsignInfoResponse = self._service.lookup(
                callsign,
                target_latitude=latitude,
                target_longitude=longitude,
                target_source="pota" if source == "pota" else None,
            )
        except ValueError as error:
            return self._error(422, "invalid_request", str(error))
        except (QrzLookupError, WavelogError, OSError):
            _LOGGER.exception("Callsign-info lookup failed")
            return self._error(
                503,
                "lookup_unavailable",
                "Callsign information is temporarily unavailable.",
            )
        return self._json(200, response.model_dump(mode="json"))

    @classmethod
    def _json(cls, status_code: int, payload: object) -> ForgeCallsignInfoHttpResponse:
        body = dumps(payload, separators=(",", ":")).encode("utf-8")
        return ForgeCallsignInfoHttpResponse(
            status_code=status_code,
            headers=(
                ("Content-Type", _JSON),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ),
            body=body,
        )

    @classmethod
    def _error(
        cls,
        status_code: int,
        error: str,
        message: str,
        *,
        allow: str | None = None,
    ) -> ForgeCallsignInfoHttpResponse:
        response = cls._json(status_code, {"error": error, "message": message})
        if allow is None:
            return response
        return ForgeCallsignInfoHttpResponse(
            response.status_code,
            response.headers + (("Allow", allow),),
            response.body,
        )


def _optional_float(values: list[str] | None) -> float | None:
    if not values:
        return None
    return float(values[0])


def make_forge_callsign_info_handler(
    application: ForgeCallsignInfoApiApplication,
    *,
    logger: logging.Logger | None = None,
) -> type[BaseHTTPRequestHandler]:
    request_logger = logger or _LOGGER

    class Handler(BaseHTTPRequestHandler):
        server_version = "RollingThunderForgeCallsignInfo/1"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            self._send(application.handle("GET", self.path))

        def do_POST(self) -> None:
            self._send(application.handle("POST", self.path))

        def _send(self, response: ForgeCallsignInfoHttpResponse) -> None:
            self.send_response(response.status_code)
            for name, value in response.headers:
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(response.body)

        def log_message(self, format_string: str, *args: object) -> None:
            request_logger.info("%s - %s", self.address_string(), format_string % args)

    return Handler


class ForgeCallsignInfoHttpServer:
    def __init__(
        self,
        bind_host: str,
        bind_port: int,
        application: ForgeCallsignInfoApiApplication,
        *,
        logger: logging.Logger | None = None,
    ) -> None:
        handler = make_forge_callsign_info_handler(application, logger=logger)
        self._server = ThreadingHTTPServer((bind_host, bind_port), handler)
        self._server.daemon_threads = True

    @property
    def server_address(self) -> tuple[str, int]:
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def serve_forever(self) -> None:
        self._server.serve_forever(poll_interval=0.5)

    def close(self) -> None:
        self._server.server_close()
