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



def maidenhead_grid_center(grid: MaidenheadGrid | str) -> tuple[float, float]:
    """Return the geographic center of a validated 4/6/8-character locator."""
    value = str(grid).strip()
    if len(value) not in {4, 6, 8}:
        raise ValueError("Maidenhead grid must contain 4, 6, or 8 characters.")

    upper = value.upper()
    if not (
        "A" <= upper[0] <= "R"
        and "A" <= upper[1] <= "R"
        and upper[2:4].isdigit()
    ):
        raise ValueError("Maidenhead grid is not structurally valid.")

    longitude = (ord(upper[0]) - ord("A")) * 20.0 - 180.0
    latitude = (ord(upper[1]) - ord("A")) * 10.0 - 90.0
    longitude += int(upper[2]) * 2.0
    latitude += int(upper[3]) * 1.0
    longitude_size = 2.0
    latitude_size = 1.0

    if len(value) >= 6:
        if not (
            "A" <= upper[4] <= "X"
            and "A" <= upper[5] <= "X"
        ):
            raise ValueError("Maidenhead subsquare is not structurally valid.")
        longitude_size /= 24.0
        latitude_size /= 24.0
        longitude += (ord(upper[4]) - ord("A")) * longitude_size
        latitude += (ord(upper[5]) - ord("A")) * latitude_size

    if len(value) == 8:
        if not upper[6:8].isdigit():
            raise ValueError("Maidenhead extended square is not structurally valid.")
        longitude_size /= 10.0
        latitude_size /= 10.0
        longitude += int(upper[6]) * longitude_size
        latitude += int(upper[7]) * latitude_size

    return (
        latitude + latitude_size / 2.0,
        longitude + longitude_size / 2.0,
    )
