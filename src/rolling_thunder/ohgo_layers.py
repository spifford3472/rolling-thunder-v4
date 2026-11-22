"""Shared versioned contract for statewide, display-only OHGO map markers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from rolling_thunder.live_map import GeoPoint

OHGO_LAYERS_PATH = "/api/v1/ohgo/map-layers"
OHGO_LAYERS_SCHEMA = "rolling-thunder/ohgo-map-layers/v1"
MAX_OHGO_LAYER_ROWS = 4000
MAX_OHGO_FEED_BYTES = 5_000_000
OHGO_LAYER_MAX_AGE = timedelta(minutes=5)


class OhgoLayer(StrEnum):
    CONSTRUCTION = "construction"
    DANGEROUS_SLOWDOWNS = "dangerous-slowdowns"
    INCIDENTS = "incidents"
    TRAVEL_DELAYS = "travel-delays"


class OhgoLayerStatus(StrEnum):
    DISABLED = "disabled"
    UNAVAILABLE = "unavailable"
    INCOMPLETE = "incomplete"
    CURRENT = "current"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class OhgoMarker:
    provider_id: str
    point: GeoPoint


@dataclass(frozen=True, slots=True)
class OhgoLayerSnapshot:
    layer: OhgoLayer
    status: OhgoLayerStatus
    fetched_at: datetime | None = None
    markers: tuple[OhgoMarker, ...] = ()

    def at(self, now: datetime) -> OhgoLayerSnapshot:
        """Expire current data even when background refresh has stopped."""
        if self.status is OhgoLayerStatus.CURRENT and (
            self.fetched_at is None
            or not timedelta(0) <= now - self.fetched_at <= OHGO_LAYER_MAX_AGE
        ):
            return OhgoLayerSnapshot(self.layer, OhgoLayerStatus.STALE, self.fetched_at)
        return self


OhgoLayersSnapshot = tuple[OhgoLayerSnapshot, ...]


def ohgo_point(latitude: object, longitude: object) -> GeoPoint:
    """Validate provider numbers before projecting them on the map."""
    if (
        not isinstance(latitude, (float, int))
        or isinstance(latitude, bool)
        or not isinstance(longitude, (float, int))
        or isinstance(longitude, bool)
        or not -90 <= latitude <= 90
        or not -180 <= longitude <= 180
        or (latitude == 0 and longitude == 0)
    ):
        raise ValueError("Invalid OHGO marker coordinates")
    return GeoPoint(float(latitude), float(longitude))


def encode_ohgo_layers(snapshots: OhgoLayersSnapshot, *, now: datetime) -> bytes:
    layers = {}
    for snapshot in snapshots:
        current = snapshot.at(now)
        layers[current.layer.value] = {
            "status": current.status.value,
            "fetched_at": current.fetched_at.isoformat() if current.fetched_at else None,
            "markers": [
                {"id": item.provider_id, "latitude": item.point.latitude,
                 "longitude": item.point.longitude}
                for item in current.markers
            ],
        }
    return json.dumps(
        {"schema": OHGO_LAYERS_SCHEMA, "layers": layers},
        separators=(",", ":"),
    ).encode()


def decode_ohgo_layers(body: bytes) -> OhgoLayersSnapshot:
    """Decode categories independently so a malformed layer leaves the others usable."""
    if len(body) > MAX_OHGO_FEED_BYTES:
        raise ValueError("Oversized OHGO map feed")
    payload = json.loads(body)
    if not isinstance(payload, dict) or payload.get("schema") != OHGO_LAYERS_SCHEMA:
        raise ValueError("Unknown OHGO map feed")
    layers = payload.get("layers")
    if not isinstance(layers, dict):
        raise TypeError("Missing OHGO map categories")
    return tuple(_decode_layer(layer, layers.get(layer.value)) for layer in OhgoLayer)


def _decode_layer(layer: OhgoLayer, data: object) -> OhgoLayerSnapshot:
    try:
        if not isinstance(data, dict):
            raise TypeError("Missing category")
        status = OhgoLayerStatus(data["status"])
        fetched = data.get("fetched_at")
        fetched_at = datetime.fromisoformat(fetched) if isinstance(fetched, str) else None
        if fetched_at is not None and fetched_at.utcoffset() is None:
            raise ValueError("Naive OHGO timestamp")
        if status is not OhgoLayerStatus.CURRENT:
            return OhgoLayerSnapshot(layer, status, fetched_at)
        rows = data["markers"]
        if fetched_at is None or not isinstance(rows, list) or len(rows) > MAX_OHGO_LAYER_ROWS:
            raise ValueError("Invalid category snapshot")
        markers: dict[str, OhgoMarker] = {}
        for row in rows:
            key = row["id"]
            if not isinstance(key, str) or not 1 <= len(key) <= 96:
                raise ValueError("Invalid OHGO marker ID")
            point = ohgo_point(row["latitude"], row["longitude"])
            markers.setdefault(key, OhgoMarker(key, point))
        return OhgoLayerSnapshot(layer, status, fetched_at, tuple(markers.values()))
    except (KeyError, TypeError, ValueError):
        return OhgoLayerSnapshot(layer, OhgoLayerStatus.UNAVAILABLE)
