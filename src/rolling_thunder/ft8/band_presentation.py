"""Pure FT8 receive-band tune presentation without extra radio I/O."""

from __future__ import annotations

from rolling_thunder.dashboard_state import _format_band, _format_frequency
from rolling_thunder.domain import RadioState
from rolling_thunder.ft8.band_control import FT8BandTuneState, FT8BandTuneStatus
from rolling_thunder.receive_tuning import ReceiveTuneOutcome


def present_ft8_band_tune(
    radio_state: RadioState,
    status: FT8BandTuneStatus,
    acknowledged: object | None,
    frequency_text: str,
    band_text: str,
) -> tuple[str, str, object | None]:
    """Present verified worker state until the regular radio poll catches up.

    Acknowledging the exact outcome prevents displaying an old successful
    tune over future unrelated changes to the radio's actual frequency.
    """
    if status.state is FT8BandTuneState.TUNING:
        target = "" if status.target_band is None else f" {status.target_band.value}"
        return frequency_text, f"TUNING{target}", acknowledged

    outcome: ReceiveTuneOutcome | None = (
        status.outcome if status.state is FT8BandTuneState.SUCCEEDED else None
    )
    if outcome is None or outcome is acknowledged:
        return frequency_text, band_text, acknowledged

    frequency = outcome.state.frequency
    if frequency is None:
        return frequency_text, band_text, acknowledged
    if radio_state.frequency == frequency:
        return frequency_text, band_text, outcome
    return _format_frequency(frequency), _format_band(frequency).replace(" ", ""), acknowledged
