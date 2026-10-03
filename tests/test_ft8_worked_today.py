"""Tests for UTC-day successful FT8 callsign/band suppression."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from rolling_thunder.domain import Contact, RadioMode
from rolling_thunder.ft8.worked_today import FT8WorkedTodayService
from rolling_thunder.radio import RadioBand


def _contact(
    *,
    contact_id: str,
    callsign: str = "K1ABC",
    frequency_hz: int = 14_074_000,
    mode: RadioMode = RadioMode.FT8,
    started_at: datetime,
) -> Contact:
    return Contact(
        contact_id=UUID(contact_id),
        callsign=callsign,
        frequency_hz=frequency_hz,
        mode=mode,
        started_at=started_at,
        rst_sent="-10",
        rst_received="-08",
        my_grid="EM79xm",
        grid="FN31",
    )


class Repository:
    def __init__(self, contacts: list[Contact]) -> None:
        self.contacts = contacts
        self.calls: list[tuple[datetime, RadioMode | None]] = []

    def list_since(
        self,
        started_at: datetime,
        *,
        mode: RadioMode | None = None,
    ) -> list[Contact]:
        self.calls.append((started_at, mode))
        return [
            contact
            for contact in self.contacts
            if contact.started_at >= started_at
            and (mode is None or contact.mode is mode)
        ]


def test_restart_seed_suppresses_completed_callsign_band_for_current_utc_date() -> None:
    now = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    repository = Repository(
        [
            _contact(
                contact_id="00000000-0000-0000-0000-000000000001",
                started_at=now - timedelta(hours=2),
            )
        ]
    )

    worked = FT8WorkedTodayService(repository, clock=lambda: now)

    assert worked.is_suppressed("k1abc", RadioBand.BAND_20M) is True
    assert worked.is_suppressed("K1ABC", RadioBand.BAND_40M) is False
    assert repository.calls == [
        (datetime(2026, 10, 2, 0, 0, tzinfo=UTC), RadioMode.FT8)
    ]


def test_previous_utc_day_contact_is_not_suppressed() -> None:
    now = datetime(2026, 10, 2, 0, 5, tzinfo=UTC)
    repository = Repository(
        [
            _contact(
                contact_id="00000000-0000-0000-0000-000000000002",
                started_at=datetime(2026, 10, 1, 23, 59, tzinfo=UTC),
            )
        ]
    )

    worked = FT8WorkedTodayService(repository, clock=lambda: now)

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is False


def test_non_ft8_contact_never_seeds_suppression() -> None:
    now = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    repository = Repository(
        [
            _contact(
                contact_id="00000000-0000-0000-0000-000000000003",
                mode=RadioMode.USB,
                started_at=now - timedelta(minutes=5),
            )
        ]
    )

    worked = FT8WorkedTodayService(repository, clock=lambda: now)

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is False


def test_completed_contact_updates_cache_without_second_repository_query() -> None:
    now = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    repository = Repository([])
    worked = FT8WorkedTodayService(repository, clock=lambda: now)

    worked.record_completed(
        _contact(
            contact_id="00000000-0000-0000-0000-000000000004",
            started_at=now,
        )
    )

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is True
    assert len(repository.calls) == 1


def test_same_callsign_different_band_remains_eligible() -> None:
    now = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    worked = FT8WorkedTodayService(Repository([]), clock=lambda: now)
    worked.record_completed(
        _contact(
            contact_id="00000000-0000-0000-0000-000000000005",
            callsign="K1ABC",
            frequency_hz=7_074_000,
            started_at=now,
        )
    )

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_40M) is True
    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is False


def test_next_utc_date_clears_prior_day_suppression_without_database_polling() -> None:
    current = {"now": datetime(2026, 10, 2, 23, 59, tzinfo=UTC)}
    repository = Repository([])
    worked = FT8WorkedTodayService(repository, clock=lambda: current["now"])
    worked.record_completed(
        _contact(
            contact_id="00000000-0000-0000-0000-000000000006",
            started_at=current["now"],
        )
    )

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is True

    current["now"] = datetime(2026, 10, 3, 0, 0, tzinfo=UTC)

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is False
    assert len(repository.calls) == 1


def test_failed_or_aborted_attempt_has_no_suppression_api_side_effect() -> None:
    now = datetime(2026, 10, 2, 20, 0, tzinfo=UTC)
    worked = FT8WorkedTodayService(Repository([]), clock=lambda: now)

    assert worked.is_suppressed("K1ABC", RadioBand.BAND_20M) is False
