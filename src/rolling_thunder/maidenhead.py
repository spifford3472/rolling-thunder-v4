"""Pure Maidenhead locator calculation from geographic coordinates."""

from rolling_thunder.value_types import MaidenheadGrid


def maidenhead_grid(latitude: float, longitude: float) -> MaidenheadGrid:
    """Return a six-character Maidenhead locator for valid coordinates."""
    if not -90 <= latitude <= 90:
        raise ValueError("latitude must be between -90 and 90 degrees")
    if not -180 <= longitude <= 180:
        raise ValueError("longitude must be between -180 and 180 degrees")

    # The upper bounds belong to the final legal field rather than a new field.
    adjusted_latitude = min(latitude, 90.0 - 1e-12)
    adjusted_longitude = min(longitude, 180.0 - 1e-12)

    longitude_offset = adjusted_longitude + 180.0
    latitude_offset = adjusted_latitude + 90.0

    field_longitude = int(longitude_offset // 20)
    field_latitude = int(latitude_offset // 10)

    square_longitude = int((longitude_offset % 20) // 2)
    square_latitude = int(latitude_offset % 10)

    subsquare_longitude = int(((longitude_offset % 2) / 2) * 24)
    subsquare_latitude = int((latitude_offset % 1) * 24)

    locator = (
        f"{chr(ord('A') + field_longitude)}"
        f"{chr(ord('A') + field_latitude)}"
        f"{square_longitude}"
        f"{square_latitude}"
        f"{chr(ord('a') + subsquare_longitude)}"
        f"{chr(ord('a') + subsquare_latitude)}"
    )
    return locator
