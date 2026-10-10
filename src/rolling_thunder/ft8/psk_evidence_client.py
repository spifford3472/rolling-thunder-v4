"""Bounded, optional read-only Pi client for private Forge PSK path evidence.

Call only from a background worker. Network/JSON/auth failures yield no
evidence and never block CQ display or grant RF authority.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError, loads
from typing import Any, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class OutboundReceptionObservation:
    observed_at_utc: datetime
    receiver_count: int
    median_snr_db: float | None


class PskEvidenceTransport(Protocol):
    def get(self, url: str, *, token: str, timeout_s: float) -> bytes: ...


class UrllibPskEvidenceTransport:
    def get(self, url: str, *, token: str, timeout_s: float) -> bytes:
        request = Request(url, headers={"Authorization": f"Bearer {token}"}, method="GET")
        with urlopen(request, timeout=timeout_s) as response:
            if response.status != 200:
                raise OSError("Forge evidence unavailable")
            return bytes(response.read(16_385))


class HttpPskEvidenceClient:
    """Read candidate evidence with bounded request and response sizes."""

    def __init__(
        self, base_url: str, *, bearer_token: str,
        timeout_s: float = 1.0,
        transport: PskEvidenceTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"https", "http"} or not parsed.netloc or parsed.query or parsed.fragment:
            raise ValueError("valid HTTP(S) base_url required")
        if len(bearer_token) < 32 or any(ch.isspace() for ch in bearer_token):
            raise ValueError("private evidence bearer token must be at least 32 nonspace characters")
        if not 0 < timeout_s <= 5:
            raise ValueError("timeout_s must be within (0, 5]")
        self._base_url = base_url.rstrip("/")
        self._token = bearer_token
        self._timeout_s = timeout_s
        self._transport = transport or UrllibPskEvidenceTransport()

    def lookup(
        self, *, sender_callsign: str, target_grid: str,
        frequency_hz: int, now_utc: datetime,
    ) -> OutboundReceptionObservation | None:
        """Return validated observed reception, not a contact probability."""
        if now_utc.utcoffset() is None:
            raise ValueError("now_utc must be aware")
        if not sender_callsign.strip() or not target_grid.strip() or frequency_hz <= 0:
            return None
        query = urlencode({
            "sender": sender_callsign.strip().upper(),
            "target_grid": target_grid.strip().upper(),
            "frequency_hz": frequency_hz,
        })
        url = f"{self._base_url}/api/v1/ft8/outbound-psk-evidence?{query}"
        try:
            raw = self._transport.get(url, token=self._token, timeout_s=self._timeout_s)
            if len(raw) > 16_384:
                return None
            data: Any = loads(raw)
            if not isinstance(data, dict) or data.get("schema_version") != 1:
                return None
            if data.get("status") != "observed":
                return None
            evidence = data.get("evidence")
            if not isinstance(evidence, dict):
                return None
            if not evidence.get("directional") or evidence.get("usable_for_calibrated_probability") is not False:
                return None
            if evidence.get("sender_callsign") != sender_callsign.strip().upper():
                return None
            if evidence.get("target_grid") != target_grid.strip().upper():
                return None
            if evidence.get("frequency_hz") != frequency_hz:
                return None
            count = evidence["nearby_receivers"]
            if type(count) is not int or not 1 <= count <= 500:
                return None
            stamp = datetime.fromisoformat(evidence["latest_reception_utc"])
            if stamp.utcoffset() is None:
                return None
            age = (now_utc.astimezone(UTC) - stamp.astimezone(UTC)).total_seconds()
            if not 0 <= age <= 1800:
                return None
            snr = evidence.get("median_snr_db")
            if snr is not None and (type(snr) not in {float, int} or not -60 <= snr <= 60):
                return None
            return OutboundReceptionObservation(stamp.astimezone(UTC), count, snr)
        except (OSError, URLError, HTTPError, JSONDecodeError, UnicodeError, ValueError, KeyError, TypeError, OverflowError):
            return None
