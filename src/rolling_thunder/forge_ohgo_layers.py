"""Forge intake and retained publication for the four statewide OHGO resources."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread
from urllib.parse import urlencode

from rolling_thunder.forge_ohgo_incidents import (
    OhgoProtocolError,
    OhgoTransport,
    _ohgo_field,
)
from rolling_thunder.ohgo_layers import (
    MAX_OHGO_LAYER_ROWS,
    OhgoLayer,
    OhgoLayerSnapshot,
    OhgoLayersSnapshot,
    OhgoLayerStatus,
    OhgoMarker,
    ohgo_point,
)

OHGO_API_ROOT = "https://publicapi.ohgo.com/api/v1/"
_REFRESH_S = 120
_RETRY_LIMIT_S = 480


class IncompleteOhgoLayer(OhgoProtocolError):
    """The result cannot be published as complete."""


def parse_ohgo_layer(body: bytes, layer: OhgoLayer, received_at: datetime) -> OhgoLayerSnapshot:
    """Accept a complete page-all result and retain only validated marker points."""
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise OhgoProtocolError("Unexpected OHGO result")
    rejected = _ohgo_field(payload, "RejectedFilters")
    rows = _ohgo_field(payload, "Results")
    counts = tuple(
        _ohgo_field(payload, field)
        for field in ("TotalPageCount", "CurrentResultCount", "TotalResultCount")
    )
    if not isinstance(rejected, list) or rejected or not isinstance(rows, list):
        raise OhgoProtocolError("Invalid OHGO result or rejected filter")
    pages, count, total = counts
    if (
        any(type(value) is not int for value in counts)
        or pages not in ((0, 1) if not rows else (1,))
        or count != len(rows)
        or total != len(rows)
        or len(rows) > MAX_OHGO_LAYER_ROWS
    ):
        raise IncompleteOhgoLayer("OHGO page set is incomplete")
    markers: dict[str, OhgoMarker] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        key = _ohgo_field(row, "Id")
        if (
            not isinstance(key, str)
            or not 1 <= len(key) <= 96
            or not key.isascii()
            or not key.isprintable()
            or not key.strip()
        ):
            continue
        try:
            point = ohgo_point(_ohgo_field(row, "Latitude"), _ohgo_field(row, "Longitude"))
        except ValueError:
            continue
        markers.setdefault(key, OhgoMarker(key, point))
    return OhgoLayerSnapshot(layer, OhgoLayerStatus.CURRENT, received_at, tuple(markers.values()))


class ForgeOhgoMapLayers:
    """Poll independently of regional incidents and serve memory-only snapshots."""

    def __init__(
        self,
        transport: OhgoTransport,
        api_key: str | None,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._transport = transport
        self._key = api_key
        self._clock = clock
        initial = OhgoLayerStatus.UNAVAILABLE if api_key else OhgoLayerStatus.DISABLED
        self._states = {layer: OhgoLayerSnapshot(layer, initial) for layer in OhgoLayer}
        self._etags: dict[OhgoLayer, str] = {}
        self._failures: dict[OhgoLayer, int] = {}
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def snapshot(self) -> OhgoLayersSnapshot:
        return tuple(self._states.values())

    def start(self) -> None:
        if not self._key or self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="forge-ohgo-map", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            if not self._thread.is_alive():
                self._thread = None

    def _run(self) -> None:
        from time import monotonic

        due = dict.fromkeys(OhgoLayer, monotonic())
        while not self._stop.is_set():
            for layer in OhgoLayer:
                if self._stop.is_set():
                    return
                if monotonic() < due[layer]:
                    continue
                state = self.refresh_layer(layer)
                failed = state.status is not OhgoLayerStatus.CURRENT
                failures = min(self._failures.get(layer, 0) + 1, 2) if failed else 0
                self._failures[layer] = failures
                due[layer] = monotonic() + min(_REFRESH_S * 2**failures, _RETRY_LIMIT_S)
            self._stop.wait(max(0, min(due.values()) - monotonic()))

    def refresh_layer(self, layer: OhgoLayer) -> OhgoLayerSnapshot:
        """Perform one worker-owned refresh with category-local failure handling."""
        if not self._key:
            return self._states[layer]
        headers = {"Authorization": f"APIKEY {self._key}", "Accept": "application/json"}
        etag = self._etags.get(layer)
        if etag is not None:
            headers["If-None-Match"] = etag
        filters = {"page-all": "true"}
        if layer is OhgoLayer.CONSTRUCTION:
            filters["exclude-work-zone"] = "true"
        previous = self._states[layer]
        try:
            response = self._transport(
                f"{OHGO_API_ROOT}{layer.value}?{urlencode(filters)}", headers, 4.0
            )
            now = self._clock()
            if response.status == 304 and etag is not None:
                state = OhgoLayerSnapshot(layer, OhgoLayerStatus.CURRENT, now, previous.markers)
            elif response.status == 200:
                state = parse_ohgo_layer(response.body, layer, now)
                self._etags.pop(layer, None)
                new_tag = response.headers.get("etag")
                if new_tag and len(new_tag) <= 256 and new_tag.isascii() and new_tag.isprintable():
                    self._etags[layer] = new_tag
            else:
                raise OhgoProtocolError("OHGO request unsuccessful")
        except IncompleteOhgoLayer:
            state = OhgoLayerSnapshot(layer, OhgoLayerStatus.INCOMPLETE, previous.fetched_at)
        except (OSError, ValueError, RecursionError):
            state = OhgoLayerSnapshot(layer, OhgoLayerStatus.UNAVAILABLE, previous.fetched_at)
        if state.status is not OhgoLayerStatus.CURRENT:
            self._etags.pop(layer, None)
        self._states[layer] = state
        return state
