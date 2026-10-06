"""Distance calculation between Maidenhead grid centers for FT8."""

from __future__ import annotations

import math

from rolling_thunder.maidenhead import maidenhead_grid_center

_EARTH_RADIUS_KM = 6_371.0088
_KM_PER_MILE = 1.609344

# Conservative deterministic initial-power curve. Nearby paths remain at the
# minimum; each threshold raises the initial request by one 5 W step, with a
# hard 70 W ceiling for extreme paths.
_FT8_INITIAL_POWER_THRESHOLDS: tuple[tuple[float, int], ...] = (
    (3_000.0, 20),
    (4_500.0, 25),
    (6_000.0, 30),
    (7_500.0, 35),
    (9_000.0, 40),
    (10_500.0, 45),
    (11_500.0, 50),
    (12_500.0, 55),
    (13_500.0, 60),
    (14_500.0, 65),
)


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


def initial_ft8_power_watts(
    local_grid: str | None,
    remote_grid: str | None,
) -> int:
    """Return the hard-clamped initial QSO power from frozen grid distance."""
    if not local_grid or not remote_grid:
        return 20
    try:
        distance_km = maidenhead_distance_km(local_grid, remote_grid)
    except ValueError:
        return 20
    for maximum_km, power_watts in _FT8_INITIAL_POWER_THRESHOLDS:
        if distance_km <= maximum_km:
            return power_watts
    return 70


def format_maidenhead_distance(local_grid: str | None, remote_grid: str | None) -> str:
    """Return a driver-readable distance or an explicit unavailable value."""
    if not local_grid or not remote_grid:
        return "DISTANCE —"
    try:
        miles = maidenhead_distance_miles(local_grid, remote_grid)
    except ValueError:
        return "DISTANCE —"
    return f"DISTANCE {miles:,.0f} mi"
