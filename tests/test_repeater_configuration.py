"""Tests for typed repeater staging, service conversion, and background execution."""

from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.fm_repeater import (
    FmRepeaterConfigurationOutcome,
    FmRepeaterConfigurationStatus,
    FmRepeaterShiftDirection,
    FmRepeaterUnsupportedReason,
)
from rolling_thunder.repeater_configuration import (
    RepeaterConfigurationController,
    RepeaterConfigurationService,
    RepeaterConfigurationStatusKind,
    StagedRepeaterRadioAction,
)
from rolling_thunder.repeater_domain import (
    RepeaterChannelType,
    RepeaterIdentity,
    RepeaterLocation,
    RepeaterRecord,
)

_TEST_TIME = datetime(2026, 8, 11, 22, 0, tzinfo=UTC)


def record(*, rx_tone: str | None = None, tx_tone: str | None = "131.8") -> RepeaterRecord:
    rx = Frequency(hz=53_050_000)
    return RepeaterRecord(
        identity=RepeaterIdentity(name="K8AAA Alpha", rx_frequency=rx),
        name="K8AAA Alpha",
        callsign="K8AAA",
        channel_type=RepeaterChannelType.ANALOGUE,
        rx_frequency=rx,
        tx_frequency=Frequency(hz=52_050_000),
        bandwidth_khz=Decimal(25),
        rx_tone_hz=Decimal(rx_tone) if rx_tone is not None else None,
        tx_tone_hz=Decimal(tx_tone) if tx_tone is not None else None,
        location=RepeaterLocation(latitude=39.5, longitude=-84.0),
        source_active=True,
    )


class RecordingRadio:
    def __init__(self, outcome: FmRepeaterConfigurationOutcome) -> None:
        self.outcome = outcome
        self.requests = []

    def configure_fm_repeater(self, request):
        self.requests.append(request)
        return self.outcome


def configured_outcome() -> FmRepeaterConfigurationOutcome:
    return FmRepeaterConfigurationOutcome(
        status=FmRepeaterConfigurationStatus.CONFIGURED,
        state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=53_050_000),
            mode=RadioMode.FM,
            transmitting=False,
            updated_at=_TEST_TIME,
        ),
    )


def immediate(worker: Callable[[], None]) -> None:
    worker()


def test_stage_captures_all_action_critical_values_exactly() -> None:
    repeater = record(rx_tone="131.8", tx_tone="131.8")

    action = StagedRepeaterRadioAction.from_repeater(repeater)

    assert action.stable_key == repeater.stable_key
    assert action.request.rx_frequency == repeater.rx_frequency
    assert action.request.shift_direction is FmRepeaterShiftDirection.MINUS
    assert action.request.offset_hz == 1_000_000
    assert action.request.rx_tone_hz == Decimal("131.8")
    assert action.request.tx_tone_hz == Decimal("131.8")


def test_service_routes_only_typed_request_to_radio() -> None:
    radio = RecordingRadio(configured_outcome())
    service = RepeaterConfigurationService(radio)
    action = StagedRepeaterRadioAction.from_repeater(record())

    outcome = service.configure(action)

    assert outcome.status is FmRepeaterConfigurationStatus.CONFIGURED
    assert radio.requests == [action.request]


def test_background_controller_executes_one_accepted_action() -> None:
    radio = RecordingRadio(configured_outcome())
    controller = RepeaterConfigurationController(
        RepeaterConfigurationService(radio),
        worker_launcher=immediate,
    )
    action = StagedRepeaterRadioAction.from_repeater(record())

    assert controller.start_configure(action) is True

    status = controller.status
    assert status.kind is RepeaterConfigurationStatusKind.CONFIGURED
    assert status.completed_action == action
    assert status.completion_revision == 1
    assert radio.requests == [action.request]


def test_unsupported_radio_outcome_is_truthful_manual_handoff() -> None:
    outcome = FmRepeaterConfigurationOutcome(
        status=FmRepeaterConfigurationStatus.UNSUPPORTED_MANUAL_HANDOFF,
        unsupported_reason=FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES,
        manual_handoff=(
            "INDEPENDENT RX/TX CTCSS TONES ARE NOT SUPPORTED — "
            "CONFIGURE REPEATER MANUALLY"
        ),
    )
    radio = RecordingRadio(outcome)
    controller = RepeaterConfigurationController(
        RepeaterConfigurationService(radio),
        worker_launcher=immediate,
    )
    action = StagedRepeaterRadioAction.from_repeater(
        record(rx_tone="100.0", tx_tone="131.8")
    )

    assert controller.start_configure(action) is True

    status = controller.status
    assert status.kind is RepeaterConfigurationStatusKind.MANUAL_HANDOFF
    assert status.outcome == outcome
    assert status.outcome.manual_handoff is not None
