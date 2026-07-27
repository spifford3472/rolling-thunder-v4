from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)
from rolling_thunder.pota_tune_presentation import (
    build_pota_tune_presentation,
)


def intent(status: PotaTuneIntentStatus) -> PotaTuneIntent:
    return PotaTuneIntent(
        status=status,
        activator="KI5VNB",
        park_reference="US-1234",
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        created_at=datetime(2026, 7, 27, 1, 0, tzinfo=UTC),
    )


def result(
    status: PotaReceiveTuneResultStatus,
    *,
    error: str | None = None,
) -> PotaReceiveTuneResult:
    return PotaReceiveTuneResult(
        status=status,
        frequency=Frequency(hz=14_250_000),
        mode=RadioMode.USB,
        error=error,
    )


def test_no_intent_builds_empty_presentation() -> None:
    presentation = build_pota_tune_presentation(None)

    assert presentation.summary_line is None
    assert presentation.status_line is None
    assert presentation.detail_line is None


def test_pending_intent_requests_confirmation() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.PENDING_CONFIRMATION),
    )

    assert presentation.summary_line == (
        "TUNE PENDING_CONFIRMATION: KI5VNB US-1234 "
        "14.250 MHz USB"
    )
    assert presentation.status_line == (
        "PRESS ENTER TO CONFIRM — NO RADIO CHANGE"
    )
    assert presentation.detail_line is None


def test_confirmed_intent_is_ready_without_execution() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.CONFIRMED),
    )

    assert presentation.status_line == (
        "READY TO EXECUTE — NO RADIO CHANGE"
    )
    assert presentation.detail_line is None


def test_cancelled_intent_reports_no_radio_change() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.CANCELLED),
    )

    assert presentation.status_line == (
        "TUNE INTENT CANCELLED — NO RADIO CHANGE"
    )


def test_success_result_preserves_target_details() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.CONFIRMED),
        result(PotaReceiveTuneResultStatus.SUCCEEDED),
    )

    assert presentation.status_line == "RECEIVE TUNE SUCCEEDED"
    assert presentation.detail_line == "14.250 MHz USB"


def test_rejected_result_displays_reason() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.CONFIRMED),
        result(
            PotaReceiveTuneResultStatus.REJECTED,
            error="This POTA tune intent has already been executed.",
        ),
    )

    assert presentation.status_line == "RECEIVE TUNE REJECTED"
    assert presentation.detail_line == (
        "This POTA tune intent has already been executed."
    )


def test_failed_result_displays_failure_detail() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.CONFIRMED),
        result(
            PotaReceiveTuneResultStatus.FAILED,
            error="Unable to set receive frequency: disconnected",
        ),
    )

    assert presentation.status_line == "RECEIVE TUNE FAILED"
    assert presentation.detail_line == (
        "Unable to set receive frequency: disconnected"
    )


def test_result_does_not_replace_selected_target_summary() -> None:
    presentation = build_pota_tune_presentation(
        intent(PotaTuneIntentStatus.CONFIRMED),
        result(PotaReceiveTuneResultStatus.SUCCEEDED),
    )

    assert presentation.summary_line == (
        "TUNE CONFIRMED: KI5VNB US-1234 14.250 MHz USB"
    )
