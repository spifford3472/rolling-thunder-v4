"""Tests for pure POTA dashboard presentation state."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_dashboard_state import build_pota_dashboard_state
from rolling_thunder.pota_spot_service import PotaSpotServiceState
from rolling_thunder.pota_spot_source import PotaSpotSourceAvailability
from rolling_thunder.pota_spots import AmateurBand, ParkReference, PotaSpot


def timestamp(hour: int = 12) -> datetime:
    return datetime(2026, 7, 26, hour, 30, tzinfo=UTC)


def spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    mode: RadioMode,
    *,
    name: str | None = None,
    comments: str | None = None,
) -> PotaSpot:
    return PotaSpot(
        activator=callsign,
        park=ParkReference(reference=reference, name=name),
        frequency=Frequency(hz=frequency_hz),
        mode=mode,
        spotted_at=timestamp(),
        comments=comments,
    )


def test_disabled_state_is_explicit_and_empty() -> None:
    dashboard = build_pota_dashboard_state(None)

    assert dashboard.status == "DISABLED"
    assert dashboard.detail == "POTA SPOTS DISABLED"
    assert dashboard.availability == "DISABLED"
    assert dashboard.is_stale is False
    assert dashboard.last_refresh == "—"
    assert dashboard.error == ""
    assert dashboard.total_spot_count == 0
    assert dashboard.visible_spot_count == 0
    assert dashboard.rows == ()


def test_unknown_state_maps_to_loading() -> None:
    dashboard = build_pota_dashboard_state(
        PotaSpotServiceState(availability=PotaSpotSourceAvailability.UNKNOWN)
    )

    assert dashboard.status == "LOADING"
    assert dashboard.detail == "POTA SPOTS NOT REFRESHED"
    assert dashboard.availability == "UNKNOWN"


def test_available_empty_state_maps_to_empty() -> None:
    dashboard = build_pota_dashboard_state(
        PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.AVAILABLE,
            last_attempt_at=timestamp(),
            last_success_at=timestamp(),
        )
    )

    assert dashboard.status == "EMPTY"
    assert dashboard.detail == "NO CURRENT POTA SPOTS"
    assert dashboard.last_refresh == "2026-07-26 12:30 UTC"


def test_available_spots_are_formatted_for_display() -> None:
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(
            spot(
                "KI5VNB",
                "US-1234",
                14_250_000,
                RadioMode.USB,
                name="Example State Park",
                comments="Listening up 5",
            ),
        ),
        last_attempt_at=timestamp(13),
        last_success_at=timestamp(12),
    )

    dashboard = build_pota_dashboard_state(state)

    assert dashboard.status == "READY"
    assert dashboard.detail == "SHOWING 1 OF 1 SPOTS"
    assert dashboard.total_spot_count == 1
    assert dashboard.visible_spot_count == 1
    assert dashboard.rows[0].activator == "KI5VNB"
    assert dashboard.rows[0].park_reference == "US-1234"
    assert dashboard.rows[0].park_name == "Example State Park"
    assert dashboard.rows[0].frequency == "14.250 MHz"
    assert dashboard.rows[0].mode == "USB"
    assert dashboard.rows[0].spotted_at == "2026-07-26 12:30 UTC"
    assert dashboard.rows[0].comments == "Listening up 5"


def test_band_and_mode_filters_change_only_visible_rows() -> None:
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(
            spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),
            spot("W8ABC", "US-5678", 7_255_000, RadioMode.LSB),
            spot("N0XYZ", "US-9012", 14_074_000, RadioMode.DATA),
        ),
        last_attempt_at=timestamp(),
        last_success_at=timestamp(),
    )

    dashboard = build_pota_dashboard_state(
        state,
        band=AmateurBand.BAND_20M,
        mode=RadioMode.USB,
    )

    assert dashboard.status == "READY"
    assert dashboard.detail == "SHOWING 1 OF 3 SPOTS"
    assert dashboard.total_spot_count == 3
    assert dashboard.visible_spot_count == 1
    assert [row.activator for row in dashboard.rows] == ["KI5VNB"]


def test_unavailable_without_retained_spots_maps_to_error_state() -> None:
    dashboard = build_pota_dashboard_state(
        PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            last_attempt_at=timestamp(),
            last_error="request timed out",
        )
    )

    assert dashboard.status == "UNAVAILABLE"
    assert dashboard.detail == "POTA SPOT SOURCE UNAVAILABLE"
    assert dashboard.is_stale is False
    assert dashboard.error == "request timed out"


def test_unavailable_with_retained_spots_maps_to_stale_state() -> None:
    dashboard = build_pota_dashboard_state(
        PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            spots=(spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),),
            last_attempt_at=timestamp(13),
            last_success_at=timestamp(12),
            last_error="request timed out",
        )
    )

    assert dashboard.status == "STALE"
    assert dashboard.detail == "SHOWING 1 OF 1 RETAINED SPOTS"
    assert dashboard.is_stale is True
    assert dashboard.last_refresh == "2026-07-26 12:30 UTC"
    assert dashboard.error == "request timed out"


def test_missing_optional_row_values_have_stable_placeholders() -> None:
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),),
        last_attempt_at=timestamp(),
        last_success_at=timestamp(),
    )

    row = build_pota_dashboard_state(state).rows[0]

    assert row.park_name == "—"
    assert row.comments == ""


def test_spots_are_ranked_by_recency_when_reference_time_is_supplied() -> None:
    older = PotaSpot(
        activator="K1OLD",
        park=ParkReference(reference="US-1234"),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
    )
    newer = PotaSpot(
        activator="K1NEW",
        park=ParkReference(reference="US-5678"),
        frequency=Frequency(hz=7_255_000),
        mode=RadioMode.LSB,
        spotted_at=datetime(2026, 7, 26, 12, 25, tzinfo=UTC),
    )
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(older, newer),
        last_attempt_at=timestamp(),
        last_success_at=timestamp(),
    )

    dashboard = build_pota_dashboard_state(
        state,
        reference_time=datetime(2026, 7, 26, 12, 30, tzinfo=UTC),
    )

    assert [row.activator for row in dashboard.rows] == ["K1NEW", "K1OLD"]


def test_missing_reference_time_preserves_filtered_source_order() -> None:
    older = PotaSpot(
        activator="K1OLD",
        park=ParkReference(reference="US-1234"),
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        spotted_at=datetime(2026, 7, 26, 12, 0, tzinfo=UTC),
    )
    newer = PotaSpot(
        activator="K1NEW",
        park=ParkReference(reference="US-5678"),
        frequency=Frequency(hz=7_255_000),
        mode=RadioMode.LSB,
        spotted_at=datetime(2026, 7, 26, 12, 25, tzinfo=UTC),
    )
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(older, newer),
        last_attempt_at=timestamp(),
        last_success_at=timestamp(),
    )

    dashboard = build_pota_dashboard_state(state)

    assert [row.activator for row in dashboard.rows] == ["K1OLD", "K1NEW"]


def test_selected_index_marks_only_matching_ranked_row() -> None:
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(
            spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),
            spot("W8ABC", "US-5678", 7_255_000, RadioMode.LSB),
        ),
        last_attempt_at=timestamp(),
        last_success_at=timestamp(),
    )

    dashboard = build_pota_dashboard_state(state, selected_index=1)

    assert [row.is_selected for row in dashboard.rows] == [False, True]


def test_out_of_range_selected_index_marks_no_row() -> None:
    state = PotaSpotServiceState(
        availability=PotaSpotSourceAvailability.AVAILABLE,
        spots=(spot("KI5VNB", "US-1234", 14_250_000, RadioMode.USB),),
        last_attempt_at=timestamp(),
        last_success_at=timestamp(),
    )

    dashboard = build_pota_dashboard_state(state, selected_index=4)

    assert [row.is_selected for row in dashboard.rows] == [False]
