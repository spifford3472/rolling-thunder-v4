"""Tests for durable once-per-alert audible notification claims."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.weather_alert_notification_repository import (
    WeatherAlertNotificationRepository,
)

NOW = datetime(2026, 8, 9, 6, 5, tzinfo=UTC)


def test_first_claim_wins_and_survives_repository_restart(
    tmp_path,
) -> None:
    database = tmp_path / "rolling-thunder.db"

    first = WeatherAlertNotificationRepository(database)

    assert first.claim(
        "urn:test:warning-1",
        "Tornado Warning",
        claimed_at=NOW,
    ) is True

    assert first.claim(
        "urn:test:warning-1",
        "Tornado Warning",
        claimed_at=NOW,
    ) is False

    assert first.is_claimed(
        "urn:test:warning-1"
    ) is True

    restarted = WeatherAlertNotificationRepository(database)

    assert restarted.is_claimed(
        "urn:test:warning-1"
    ) is True

    assert restarted.claim(
        "urn:test:warning-1",
        "Tornado Warning",
        claimed_at=NOW,
    ) is False


def test_different_provider_alert_ids_claim_independently(
    tmp_path,
) -> None:
    repository = WeatherAlertNotificationRepository(
        tmp_path / "rolling-thunder.db"
    )

    assert repository.claim(
        "urn:test:one",
        "Tornado Watch",
        claimed_at=NOW,
    ) is True

    assert repository.claim(
        "urn:test:two",
        "Tornado Watch",
        claimed_at=NOW,
    ) is True


def test_claim_rejects_invalid_values(tmp_path) -> None:
    repository = WeatherAlertNotificationRepository(
        tmp_path / "rolling-thunder.db"
    )

    with pytest.raises(ValueError, match="ID"):
        repository.claim(
            "   ",
            "Tornado Warning",
            claimed_at=NOW,
        )

    with pytest.raises(ValueError, match="event"):
        repository.claim(
            "urn:test:one",
            "   ",
            claimed_at=NOW,
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        repository.claim(
            "urn:test:one",
            "Tornado Warning",
            claimed_at=datetime(2026, 8, 9, 6, 5),  # noqa: DTZ001
        )
