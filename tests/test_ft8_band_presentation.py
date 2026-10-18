"""FT8 display reflects worker progress without adding CAT traffic."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.band_control import FT8BandTuneState, FT8BandTuneStatus
from rolling_thunder.ft8.band_presentation import present_ft8_band_tune
from rolling_thunder.radio import RadioBand
from rolling_thunder.receive_tuning import ReceiveTuneOutcome


def _radio(hz: int) -> RadioState:
    return RadioState(
        connection_state=RadioConnectionState.CONNECTED,
        frequency=Frequency(hz=hz),
        mode=RadioMode.USB,
        transmitting=False,
        updated_at=datetime(2026, 10, 18, tzinfo=UTC),
    )


def test_ft8_tune_shows_progress_then_verified_band_until_poll_catches_up() -> None:
    old = _radio(14_074_000)
    new = _radio(18_100_000)
    tuning = FT8BandTuneStatus(
        state=FT8BandTuneState.TUNING, target_band=RadioBand.BAND_17M
    )
    frequency, band, ack = present_ft8_band_tune(
        old, tuning, None, "14.074 MHz", "20m"
    )
    assert frequency == "14.074 MHz"
    assert band.startswith("TUNING")
    assert ack is None

    outcome = ReceiveTuneOutcome(
        state=new, target_band=RadioBand.BAND_17M, band_changed=True
    )
    success = FT8BandTuneStatus(
        state=FT8BandTuneState.SUCCEEDED,
        target_band=RadioBand.BAND_17M,
        outcome=outcome,
    )
    frequency, band, ack = present_ft8_band_tune(
        old, success, ack, "14.074 MHz", "20m"
    )
    assert (frequency, band) == ("18.100 MHz", "17m")
    assert ack is None

    frequency, band, ack = present_ft8_band_tune(
        new, success, ack, "18.100 MHz", "17m"
    )
    assert (frequency, band) == ("18.100 MHz", "17m")
    assert ack is outcome

    # After regular radio polling catches up, a later independent tune
    # must not be overwritten by an old FT8 success result.
    frequency, band, ack = present_ft8_band_tune(
        old, success, ack, "14.074 MHz", "20m"
    )
    assert (frequency, band) == ("14.074 MHz", "20m")
    assert ack is outcome


def test_ft8_failed_tune_never_claims_new_band() -> None:
    failed = FT8BandTuneStatus(
        state=FT8BandTuneState.FAILED,
        target_band=RadioBand.BAND_17M,
        error="not connected",
    )
    assert present_ft8_band_tune(
        _radio(14_074_000), failed, None, "14.074 MHz", "20m"
    ) == ("14.074 MHz", "20m", None)
