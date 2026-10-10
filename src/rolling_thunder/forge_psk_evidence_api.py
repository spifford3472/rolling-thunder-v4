"""Private authenticated read-only HTTP application boundary for PSK evidence.

No HTTP listener is instantiated or enabled by this module. A future reviewed
composition step may attach this to a private listener using independent access.
"""
from __future__ import annotations

from dataclasses import dataclass
from hmac import compare_digest
from json import dumps
from typing import Protocol
from urllib.parse import parse_qs, urlsplit

from rolling_thunder.forge_psk_evidence_snapshot import EvidenceSnapshot

_PATH = "/api/v1/ft8/outbound-psk-evidence"
_JSON_HEADERS = (("Content-Type", "application/json; charset=utf-8"), ("Cache-Control", "private, no-store"))


class EvidenceSnapshotReader(Protocol):
    def get(self, *, sender_callsign: str, target_grid: str, frequency_hz: int) -> EvidenceSnapshot: ...


@dataclass(frozen=True)
class EvidenceHttpResponse:
    status_code: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class PrivatePskEvidenceApi:
    """Read endpoint requiring its own bearer token; no write operations."""

    def __init__(self, reader: EvidenceSnapshotReader, *, bearer_token: str) -> None:
        if len(bearer_token) < 32 or any(ch.isspace() for ch in bearer_token):
            raise ValueError("independent evidence token must have at least 32 nonspace characters")
        self._reader = reader
        self._bearer_token = bearer_token

    @staticmethod
    def _response(status: int, body: dict[str, object]) -> EvidenceHttpResponse:
        return EvidenceHttpResponse(status, _JSON_HEADERS, dumps(body).encode("utf-8"))

    def handle(self, method: str, target: str, *, authorization: str | None) -> EvidenceHttpResponse:
        parsed = urlsplit(target)
        if parsed.path != _PATH:
            return self._response(404, {"error": "not_found"})
        if method.strip().upper() != "GET":
            return self._response(405, {"error": "method_not_allowed"})
        supplied = (authorization or "").removeprefix("Bearer ")
        if not compare_digest(supplied, self._bearer_token):
            return self._response(401, {"error": "unauthorized"})
        values = parse_qs(parsed.query, strict_parsing=True)
        if set(values) != {"sender", "target_grid", "frequency_hz"} or any(len(v) != 1 for v in values.values()):
            return self._response(400, {"error": "invalid_parameters"})
        try:
            frequency = int(values["frequency_hz"][0])
            if frequency < 1_800_000 or frequency > 54_000_000:
                raise ValueError("frequency outside supported HF/6m range")
            snapshot = self._reader.get(
                sender_callsign=values["sender"][0],
                target_grid=values["target_grid"][0],
                frequency_hz=frequency,
            )
        except (ValueError, KeyError):
            return self._response(400, {"error": "invalid_parameters"})
        return self._response(200, snapshot.public_data())
