"""Asynchronous, read-only OHGO incident panel adapter for Rolling Thunder.

The Pi polls only its existing private Forge spots API, never Ohio DOT.
The Tkinter refresh path reads only an immutable in-memory snapshot.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from threading import Event, Lock, Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from rolling_thunder.forge_ohgo_incidents import OhgoState

_MAX_BYTES = 64_000


@dataclass(frozen=True, slots=True)
class MeshcoreOhgoPanelState:
    """Immutable, display-only incident preview with explicit availability."""

    status: OhgoState = OhgoState.DISABLED
    last_fetch: datetime | None = None
    lines: tuple[str, ...] = ()
    reason: str = "forge_not_configured"


def decode_forge_ohgo(data: bytes, *, received_at: datetime) -> MeshcoreOhgoPanelState:
    """Reject incomplete/nonversioned snapshots or stale incident dates."""

    if len(data) > _MAX_BYTES:
        raise ValueError("Too much incident preview data")
    raw = json.loads(data)
    if not isinstance(raw, dict) or raw.get("schema") != "rolling-thunder/ohgo-incidents/v1":
        raise ValueError("Unrecognized OHGO snapshot")
    if raw.get("driver_alert_permitted") is not False:
        raise ValueError("OHGO preview must be non-alerting")
    status_text = raw.get("status")
    if not isinstance(status_text, str):
        raise TypeError("Missing OHGO state")
    status = OhgoState(status_text)
    fetched = raw.get("fetched_at")
    fetched_at = datetime.fromisoformat(fetched) if isinstance(fetched, str) else None
    if status == OhgoState.CURRENT and (
        fetched_at is None
        or fetched_at.utcoffset() is None
        or not timedelta(0)
        <= received_at.astimezone(UTC) - fetched_at.astimezone(UTC)
        <= timedelta(minutes=5)
    ):
        return MeshcoreOhgoPanelState(OhgoState.STALE, reason="provider_snapshot_expired")
    lines: list[str] = []
    if status == OhgoState.CURRENT:
        items = raw.get("incidents")
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError("Invalid incident preview count")
        for item in items[:4]:
            if not isinstance(item, dict):
                continue
            route = _safe_label(item.get("route"), 22)
            location = _safe_label(item.get("location"), 55)
            direction = _safe_label(item.get("direction"), 16)
            category = _safe_label(item.get("category"), 25)
            if route or location:
                lines.append(f"{route} {direction}  •  {category}\n{location}".strip())
    return MeshcoreOhgoPanelState(
        status, fetched_at, tuple(lines), str(raw.get("reason") or "")[:45]
    )


def _safe_label(value: object, maximum: int) -> str:
    """Remove control characters from untrusted source labels."""

    return "".join(c for c in value if c.isprintable())[:maximum] if isinstance(value, str) else ""


class MeshcoreOhgoPanelWorker:
    """Independent private Forge polling; no network operations on UI thread."""

    def __init__(
        self,
        forge_url: str | None,
        *,
        interval_s: float = 60.0,
    ) -> None:
        self._base = forge_url.rstrip("/") if forge_url else None
        self._interval = max(60.0, interval_s)
        self._lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._state = MeshcoreOhgoPanelState()

    @property
    def state(self) -> MeshcoreOhgoPanelState:
        """No file I/O, HTTP or UI event handling in a Tk refresh."""

        with self._lock:
            return self._state

    def start(self) -> None:
        """Begin bounded background fetches only with a configured Forge URL."""

        if self._base is None or self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._loop, daemon=True, name="meshcore-ohgo-panel")
        self._thread.start()

    def _loop(self) -> None:
        assert self._base is not None
        while not self._stop.is_set():
            status = MeshcoreOhgoPanelState(OhgoState.UNAVAILABLE, reason="forge_unavailable")
            try:
                request = Request(
                    self._base + "/api/v1/ohgo/incidents",
                    headers={"Accept": "application/json"},
                    method="GET",
                )
                with urlopen(request, timeout=2.0) as response:
                    if response.status == 200:
                        status = decode_forge_ohgo(
                            response.read(_MAX_BYTES + 1),
                            received_at=datetime.now(UTC),
                        )
            except (OSError, HTTPError, URLError, ValueError, TypeError):
                pass
            with self._lock:
                self._state = status
            self._stop.wait(self._interval)

    def stop(self) -> None:
        """Stop the independent panel poller without affecting FT8 or radio."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None


def present_meshcore_ohgo(state: MeshcoreOhgoPanelState) -> str:
    """Legible at-a-glance read-only presentation, never an alert."""

    header = "MESHCORE  •  Passive receive-only\nOHGO  •  Ohio DOT incident reports"
    if state.status == OhgoState.DISABLED:
        status = "OHGO not configured on Forge."
    elif state.status == OhgoState.UNAVAILABLE:
        status = "OHGO unavailable. No current incident data."
    elif state.status == OhgoState.STALE:
        status = "OHGO data stale. Reports withheld."
    elif not state.lines:
        status = "No incidents returned for configured Ohio region."
    else:
        status = "CURRENT OHGO INCIDENT REPORTS (unverified for your route)"
    return "\n\n".join((header, status, *state.lines))
