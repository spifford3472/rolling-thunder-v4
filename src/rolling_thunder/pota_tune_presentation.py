"""Pure presentation state for POTA tune intent and execution results."""

from rolling_thunder.domain import DomainModel
from rolling_thunder.pota_receive_tune_executor import (
    PotaReceiveTuneResult,
    PotaReceiveTuneResultStatus,
)
from rolling_thunder.pota_tune_intent import (
    PotaTuneIntent,
    PotaTuneIntentStatus,
)


class PotaTunePresentation(DomainModel):
    """Immutable display lines for POTA tune state."""

    summary_line: str | None = None
    status_line: str | None = None
    detail_line: str | None = None


def build_pota_tune_presentation(
    intent: PotaTuneIntent | None,
    result: PotaReceiveTuneResult | None = None,
) -> PotaTunePresentation:
    """Build display-only POTA tune text without performing any action."""
    if intent is None:
        return PotaTunePresentation()

    summary_line = (
        f"TUNE {intent.status.value.upper()}: {intent.activator} "
        f"{intent.park_reference} "
        f"{intent.frequency.mhz:.3f} MHz "
        f"{intent.mode.value}"
    )

    if result is None:
        if intent.status is PotaTuneIntentStatus.PENDING_CONFIRMATION:
            return PotaTunePresentation(
                summary_line=summary_line,
                status_line="PRESS ENTER TO CONFIRM — NO RADIO CHANGE",
            )

        if intent.status is PotaTuneIntentStatus.CONFIRMED:
            return PotaTunePresentation(
                summary_line=summary_line,
                status_line="READY TO EXECUTE — NO RADIO CHANGE",
            )

        return PotaTunePresentation(
            summary_line=summary_line,
            status_line="TUNE INTENT CANCELLED — NO RADIO CHANGE",
        )

    target_line = _target_line(result)

    if result.status is PotaReceiveTuneResultStatus.SUCCEEDED:
        return PotaTunePresentation(
            summary_line=summary_line,
            status_line="RECEIVE TUNE SUCCEEDED",
            detail_line=target_line,
        )

    if result.status is PotaReceiveTuneResultStatus.REJECTED:
        return PotaTunePresentation(
            summary_line=summary_line,
            status_line="RECEIVE TUNE REJECTED",
            detail_line=result.error or target_line,
        )

    return PotaTunePresentation(
        summary_line=summary_line,
        status_line="RECEIVE TUNE FAILED",
        detail_line=result.error or target_line,
    )


def _target_line(result: PotaReceiveTuneResult) -> str | None:
    """Format an optional typed frequency-and-mode execution target."""
    if result.frequency is None and result.mode is None:
        return None

    parts: list[str] = []
    if result.frequency is not None:
        parts.append(f"{result.frequency.mhz:.3f} MHz")
    if result.mode is not None:
        parts.append(result.mode.value)

    return " ".join(parts)
