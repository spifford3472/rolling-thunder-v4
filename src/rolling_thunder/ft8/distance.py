"""Distance calculation between Maidenhead grid centers for FT8."""

from __future__ import annotations

import math

from rolling_thunder.maidenhead import maidenhead_grid_center

_EARTH_RADIUS_KM = 6_371.0088
_KM_PER_MILE = 1.609344


def maidenhead_distance_km(local_grid: str, remote_grid: str) -> float:
    """Return great-circle distance between two Maidenhead grid centers."""
    local_lat, local_lon = maidenhead_grid_center(local_grid)
    remote_lat, remote_lon = maidenhead_grid_center(remote_grid)

    lat1 = math.radians(local_lat)
    lat2 = math.radians(remote_lat)
    delta_lat = math.radians(remote_lat - local_lat)
    delta_lon = math.radians(remote_lon - local_lon)

    a = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2.0) ** 2
    )
    central_angle = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return _EARTH_RADIUS_KM * central_angle


def maidenhead_distance_miles(local_grid: str, remote_grid: str) -> float:
    """Return great-circle distance in operator-friendly statute miles."""
    return maidenhead_distance_km(local_grid, remote_grid) / _KM_PER_MILE


def format_maidenhead_distance(local_grid: str | None, remote_grid: str | None) -> str:
    """Return a driver-readable distance or an explicit unavailable value."""
    if not local_grid or not remote_grid:
        return "DISTANCE —"
    try:
        miles = maidenhead_distance_miles(local_grid, remote_grid)
    except ValueError:
        return "DISTANCE —"
    return f"DISTANCE {miles:,.0f} mi"
