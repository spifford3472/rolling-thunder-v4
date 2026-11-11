"""Optional OHGO retained-incidents route layered over existing Forge spots API.

No network operations occur inside HTTP request handlers; an optional
independent background provider owns all external requests.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from threading import Event, Thread
from urllib.parse import urlsplit

from rolling_thunder.forge_ohgo_incidents import (
    ForgeOhgoIncidentProvider,
    OhgoState,
    OhioIncidentSnapshot,
)
from rolling_thunder.forge_spot_api import (
    ForgeHttpResponse,
    ForgeSpotApiApplication,
)

_OHGO_PATH = "/api/v1/ohgo/incidents"


class ForgeOhgoBackgroundService:
    """Poll in an independent daemon with no Tkinter/radio dependency."""

    def __init__(
        self, provider: ForgeOhgoIncidentProvider | None, *, interval_s: float = 120.0
    ) -> None:
        self._provider = provider
        self._interval = interval_s
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def snapshot(self) -> OhioIncidentSnapshot:
        """Atomically read the last published provider snapshot without I/O."""

        if self._provider is None:
            return OhioIncidentSnapshot(OhgoState.DISABLED, reason="not_configured")
        return self._provider.snapshot

    def start(self) -> None:
        """Start only an enabled, composed provider, and never block Forge HTTP."""

        if self._provider is None:
            return
        if self._thread is not None:
            raise RuntimeError("OHGO worker already started")
        self._stop.clear()
        self._thread = Thread(target=self._run, daemon=True, name="forge-ohgo")
        self._thread.start()

    def _run(self) -> None:
        """Acquire new snapshots while preserving independent Forge lifecycles."""

        assert self._provider is not None
        while not self._stop.is_set():
            self._provider.refresh(datetime.now(UTC))
            if self._stop.wait(self._interval):
                break

    def stop(self) -> None:
        """Signal stop without interrupting other Forge services."""

        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=6)
            self._thread = None


class OhgoAwareForgeSpotApiApplication(ForgeSpotApiApplication):
    """Add an optional, read-only OHGO status and incident list."""

    def __init__(
        self,
        core: ForgeSpotApiApplication,
        ohgo: ForgeOhgoBackgroundService,
    ) -> None:
        self._core = core
        self._ohgo = ohgo

    def handle(
        self,
        method: str,
        target: str,
        *,
        headers: Mapping[str, str] | None = None,
        body: bytes | None = None,
    ) -> ForgeHttpResponse:
        """Return bounded retained response without upstream fetch."""

        if urlsplit(target).path != _OHGO_PATH:
            return self._core.handle(method, target, headers=headers, body=body)
        if method.strip().upper() != "GET":
            return ForgeSpotApiApplication.error_response(
                status_code=405,
                error="method_not_allowed",
                message="Only GET is supported for OHGO incidents.",
                extra_headers=(("Allow", "GET"),),
            )
        state = self._ohgo.snapshot
        response = {
            "schema": "rolling-thunder/ohgo-incidents/v1",
            "provider": state.source,
            "status": state.state.value,
            "fetched_at": state.fetched_at.isoformat() if state.fetched_at is not None else None,
            "reason": state.reason,
            "incidents": [
                {
                    "id": item.incident_id,
                    "latitude": item.point.latitude,
                    "longitude": item.point.longitude,
                    "route": item.route,
                    "direction": item.direction,
                    "category": item.category,
                    "description": item.description,
                    "location": item.location,
                    "road_status": item.road_status,
                }
                for item in state.incidents
            ]
            if state.eligible_for_display
            else [],
            "incident_confirmed": False,
            "driver_alert_permitted": False,
        }
        encoded = json.dumps(response, separators=(",", ":")).encode("utf-8")
        return ForgeHttpResponse(
            status_code=200,
            headers=(
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(encoded))),
                ("Cache-Control", "private, max-age=0"),
            ),
            body=encoded,
        )
