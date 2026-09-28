"""Tests for typed FM repeater configuration values and tone planning."""

from datetime import UTC, datetime
from decimal import Decimal
from typing import get_protocol_members

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.fm_repeater import (
    CtcssBehavior,
    FmRepeaterConfigurableRadio,
    FmRepeaterConfigurationOutcome,
    FmRepeaterConfigurationRequest,
    FmRepeaterConfigurationStatus,
    FmRepeaterShiftDirection,
    FmRepeaterUnsupportedReason,
    resolve_ctcss_plan,
)


def request(
    *,
    rx_tone: str | None,
    tx_tone: str | None,
) -> FmRepeaterConfigurationRequest:
    return FmRepeaterConfigurationRequest(
        rx_frequency=Frequency(hz=52_525_000),
        shift_direction=FmRepeaterShiftDirection.MINUS,
        offset_hz=1_000_000,
        rx_tone_hz=Decimal(rx_tone) if rx_tone is not None else None,
        tx_tone_hz=Decimal(tx_tone) if tx_tone is not None else None,
    )


def test_repeater_capability_protocol_exposes_only_configuration() -> None:
    assert get_protocol_members(FmRepeaterConfigurableRadio) == {"configure_fm_repeater"}


@pytest.mark.parametrize(
    ("rx_tone", "tx_tone", "behavior", "tone"),
    [
        (None, None, CtcssBehavior.OFF, None),
        (None, "131.8", CtcssBehavior.ENCODE_ONLY, Decimal("131.8")),
        ("131.8", "131.8", CtcssBehavior.ENCODE_DECODE, Decimal("131.8")),
    ],
)
def test_ctcss_plan_preserves_exact_representable_semantics(
    rx_tone: str | None,
    tx_tone: str | None,
    behavior: CtcssBehavior,
    tone: Decimal | None,
) -> None:
    plan = resolve_ctcss_plan(request(rx_tone=rx_tone, tx_tone=tx_tone))

    assert not isinstance(plan, FmRepeaterUnsupportedReason)
    assert plan.behavior is behavior
    assert plan.tone_hz == tone


def test_ctcss_plan_rejects_independent_tones_without_guessing() -> None:
    plan = resolve_ctcss_plan(request(rx_tone="131.8", tx_tone="151.4"))

    assert plan is FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES


def test_ctcss_plan_rejects_receive_only_tone_without_guessing() -> None:
    plan = resolve_ctcss_plan(request(rx_tone="131.8", tx_tone=None))

    assert plan is FmRepeaterUnsupportedReason.RECEIVE_ONLY_CTCSS


@pytest.mark.parametrize(
    ("direction", "offset_hz", "message"),
    [
        (FmRepeaterShiftDirection.SIMPLEX, 1_000_000, "simplex"),
        (FmRepeaterShiftDirection.MINUS, 0, "nonzero"),
        (FmRepeaterShiftDirection.PLUS, 0, "nonzero"),
    ],
)
def test_request_rejects_contradictory_shift_offset(
    direction: FmRepeaterShiftDirection,
    offset_hz: int,
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        FmRepeaterConfigurationRequest(
            rx_frequency=Frequency(hz=52_525_000),
            shift_direction=direction,
            offset_hz=offset_hz,
        )


def test_outcome_requires_truthful_payload_for_status() -> None:
    state = RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=52_525_000),
        mode=RadioMode.FM,
        updated_at=datetime(2026, 8, 11, 23, 0, tzinfo=UTC),
    )

    configured = FmRepeaterConfigurationOutcome(
        status=FmRepeaterConfigurationStatus.CONFIGURED,
        state=state,
        manual_band_confirmation_required=True,
    )
    unsupported = FmRepeaterConfigurationOutcome(
        status=FmRepeaterConfigurationStatus.UNSUPPORTED_MANUAL_HANDOFF,
        unsupported_reason=FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES,
        manual_handoff="CONFIGURE REPEATER TONES MANUALLY",
    )

    assert configured.state is state
    assert unsupported.manual_handoff is not None

    with pytest.raises(ValidationError, match="requires radio state"):
        FmRepeaterConfigurationOutcome(
            status=FmRepeaterConfigurationStatus.CONFIGURED,
        )
