from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)


def make_intent() -> PotaTuneIntent:
    return PotaTuneIntent(
        status=PotaTuneIntentStatus.PENDING_CONFIRMATION,
        activator="KI5VNB",
        park_reference="US-1234",
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        created_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )


def test_intent_is_immutable_and_typed() -> None:
    intent = make_intent()

    assert intent.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert intent.activator == "KI5VNB"
    assert intent.frequency.hz == 14_250_000
    assert intent.mode is RadioMode.USB

    with pytest.raises(ValidationError):
        intent.status = PotaTuneIntentStatus.CANCELLED


def test_cancel_returns_new_cancelled_intent() -> None:
    pending = make_intent()

    cancelled = pending.cancel()

    assert pending.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert cancelled.status is PotaTuneIntentStatus.CANCELLED
    assert cancelled.frequency == pending.frequency


def test_created_at_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        PotaTuneIntent(
            status=PotaTuneIntentStatus.PENDING_CONFIRMATION,
            activator="KI5VNB",
            park_reference="US-1234",
            frequency=Frequency(hz=14_250_000),
            mode=RadioMode.USB,
            created_at=datetime(2026, 7, 27, 1, 0),  # noqa: DTZ001
        )


def test_confirm_transitions_only_pending_intent() -> None:
    pending = make_intent()

    confirmed = pending.confirm()

    assert pending.status is PotaTuneIntentStatus.PENDING_CONFIRMATION
    assert confirmed.status is PotaTuneIntentStatus.CONFIRMED


def test_confirm_is_idempotent_after_confirmation() -> None:
    confirmed = make_intent().confirm()

    assert confirmed.confirm() is confirmed


def test_cancel_is_allowed_after_confirmation() -> None:
    confirmed = make_intent().confirm()

    cancelled = confirmed.cancel()

    assert cancelled.status is PotaTuneIntentStatus.CANCELLED


def test_cancelled_intent_cannot_be_confirmed() -> None:
    cancelled = make_intent().cancel()

    assert cancelled.confirm() is cancelled
    assert cancelled.status is PotaTuneIntentStatus.CANCELLED
