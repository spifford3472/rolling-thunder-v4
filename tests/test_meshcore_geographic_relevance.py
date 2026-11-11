"""Synthetic heading and geographic relevance regression tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.meshcore_geographic_relevance import (
    GeoPoint,
    PublishedGpsHeading,
    Relevance,
    VehicleFix,
    assess_relevance,
    distance_bearing,
)


NOW = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)
HOME = GeoPoint(39.54, -84.10)
NORTH = GeoPoint(39.56, -84.10)
SOUTH = GeoPoint(39.52, -84.10)


def _fix(
    timestamp: datetime = NOW,
    point: GeoPoint = HOME,
    *,
    speed: float | None = 15.0,
    course: float | None = 0.0,
    accuracy: float = 5.0,
) -> VehicleFix:
    return VehicleFix(point, timestamp, accuracy, speed, course)


def test_distance_and_bearing() -> None:
    distance, heading = distance_bearing(HOME, NORTH)
    assert 2_000 < distance < 2_500
    assert heading == pytest.approx(0.0, abs=0.01)


def test_approaching_is_not_a_confirmed_route_by_default() -> None:
    tracker = PublishedGpsHeading()
    assert tracker.offer(_fix())
    result = assess_relevance(
        tracker, NORTH, NOW, incident_location_trusted=True
    )
    assert result.relevance == Relevance.POSSIBLY_AHEAD
    assert result.heading_deg == 0


def test_explicit_route_confirmation_is_distinct() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix())
    result = assess_relevance(
        tracker, NORTH, NOW, incident_location_trusted=True, route_confirmed=True
    )
    assert result.relevance == Relevance.AHEAD_CONFIRMED


def test_incident_behind() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix())
    result = assess_relevance(
        tracker, SOUTH, NOW, incident_location_trusted=True
    )
    assert result.relevance == Relevance.BEHIND


def test_stationary_vehicle_has_no_heading() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix(speed=0))
    result = assess_relevance(
        tracker, NORTH, NOW, incident_location_trusted=True
    )
    assert result.relevance == Relevance.NEARBY_ROUTE_UNKNOWN


def test_unverified_incident_location_fails_closed() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix())
    result = assess_relevance(tracker, NORTH, NOW)
    assert result.relevance == Relevance.INSUFFICIENT
    assert result.distance_m is None


def test_stale_gps_fails_closed() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix(NOW - timedelta(seconds=11)))
    assert tracker.heading(NOW) is None
    assert assess_relevance(
        tracker, NORTH, NOW, incident_location_trusted=True
    ).relevance == Relevance.INSUFFICIENT


def test_out_of_order_and_high_frequency_samples_rejected() -> None:
    tracker = PublishedGpsHeading()
    assert tracker.offer(_fix())
    assert not tracker.offer(_fix(NOW + timedelta(milliseconds=500)))
    assert not tracker.offer(_fix(NOW - timedelta(seconds=2)))
    assert tracker.offer(_fix(NOW + timedelta(seconds=1)))


def test_position_derived_heading_without_gps_course() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix(NOW - timedelta(seconds=3), HOME, speed=None, course=None))
    tracker.offer(_fix(NOW, GeoPoint(39.5407, -84.10), speed=None, course=None))
    assert tracker.heading(NOW) == pytest.approx(0, abs=0.1)


def test_gps_jitter_cannot_create_heading() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix(NOW - timedelta(seconds=3), HOME, speed=None, course=None))
    tracker.offer(_fix(NOW, GeoPoint(39.54001, -84.1), speed=None, course=None))
    assert tracker.heading(NOW) is None


def test_implausible_derived_speed_fails_closed() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix(NOW - timedelta(seconds=3), HOME, speed=None, course=None))
    tracker.offer(_fix(NOW, NORTH, speed=None, course=None))
    assert tracker.heading(NOW) is None


def test_nearby_or_distant_incidents() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix())
    assert assess_relevance(
        tracker, HOME, NOW, incident_location_trusted=True
    ).relevance == Relevance.NEARBY_ROUTE_UNKNOWN
    assert assess_relevance(
        tracker, NORTH, NOW, incident_location_trusted=True,
        maximum_distance_m=500
    ).relevance == Relevance.NOT_RELEVANT


@pytest.mark.parametrize(
    "latitude, longitude",
    [(91.0, 0.0), (0.0, 181), (float("nan"), 0), (0, float("inf"))],
)
def test_invalid_coordinates_rejected(latitude: float, longitude: float) -> None:
    with pytest.raises(ValueError):
        GeoPoint(latitude, longitude)


def test_invalid_gps_metadata_rejected() -> None:
    with pytest.raises(ValueError):
        _fix(speed=-1)
    with pytest.raises(ValueError):
        _fix(course=360)
    with pytest.raises(ValueError):
        _fix(accuracy=151)
    with pytest.raises(ValueError):
        _fix(NOW.replace(tzinfo=None))


def test_parallel_road_not_claimed_as_confirmed_route() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix())
    assert assess_relevance(
        tracker, NORTH, NOW, incident_location_trusted=True
    ).relevance == Relevance.POSSIBLY_AHEAD


def test_gps_heading_without_reported_speed_is_not_fabricated() -> None:
    tracker = PublishedGpsHeading()
    tracker.offer(_fix(speed=None, course=55.0))
    assert tracker.heading(NOW) is None


def test_invalid_distance_limit_rejected() -> None:
    with pytest.raises(ValueError):
        assess_relevance(PublishedGpsHeading(), NORTH, NOW, maximum_distance_m=-1)
