"""Reserve the existing FT-891 tuning and DigiRig receive paths for WSPR."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager

from rolling_thunder.domain import Frequency, RadioMode, RadioState
from rolling_thunder.ft8.receive import FT8ReceiveService
from rolling_thunder.ft891_cat import Ft891SsbBfo
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import RadioError, RadioVerificationError
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.receive_tuning import ReceiveTuningService
from rolling_thunder.wspr_receive import WsprBandUnavailable, WsprInhibit


class Ft891WsprLease:
    """Expose only verified receive tuning to the WSPR session worker."""

    def __init__(self, radio: Ft891Radio, previous: RadioState, bfo: Ft891SsbBfo) -> None:
        self._radio = radio
        self._tuner = ReceiveTuningService(radio)
        self._previous = previous
        self._bfo = bfo
        self._expected = previous
        self._expected_bfo = bfo
        self._changed = False

    def tune(self, dial_hz: int) -> None:
        try:
            with self._radio.receive_operation() as current:
                self._verify_expected(current)
                try:
                    self._changed = True
                    self._expected = self._tuner.tune(Frequency(hz=dial_hz), RadioMode.USB).state
                    self._expected_bfo = self._radio.set_ssb_bfo(Ft891SsbBfo.USB)
                except RadioVerificationError as error:
                    # The configured FT-891 band memory may not recall this band.
                    self._expected = self._radio.refresh_state()
                    self._expected_bfo = self._radio.read_ssb_bfo()
                    raise WsprBandUnavailable from error
        except RadioError as error:
            raise WsprInhibit("FT-891 receive authority lost") from error

    def verify(self, dial_hz: int) -> None:
        try:
            with self._radio.receive_operation() as current:
                if (
                    current.frequency != Frequency(hz=dial_hz)
                    or current.mode is not RadioMode.USB
                    or self._radio.read_ssb_bfo() is not Ft891SsbBfo.USB
                ):
                    raise WsprInhibit("FT-891 tuning changed")
        except RadioError as error:
            raise WsprInhibit("FT-891 receive authority lost") from error

    def restore(self) -> None:
        if not self._changed:
            return
        try:
            with self._radio.receive_operation() as current:
                self._verify_expected(current)
                assert self._previous.frequency is not None and self._previous.mode is not None
                self._tuner.tune(self._previous.frequency, self._previous.mode)
                self._radio.set_ssb_bfo(self._bfo)
        except RadioError as error:
            raise WsprInhibit("FT-891 receive restore failed; check the radio") from error

    def _verify_expected(self, current: RadioState) -> None:
        if (
            current.frequency != self._expected.frequency or current.mode is not self._expected.mode
            or self._radio.read_ssb_bfo() is not self._expected_bfo
        ):
            raise WsprInhibit("FT-891 was tuned externally; verify its receive state")


@contextmanager
def reserve_ft891_wspr(
    radio: Ft891Radio,
    ft8: FT8ReceiveService | None,
    available: Callable[[], bool],
) -> Iterator[Ft891WsprLease]:
    """Require a safe radio and suspend the existing background FT8 capture."""
    if not available():
        raise WsprInhibit("FT8 or another radio operation is active")
    resume_ft8 = False
    try:
        with radio.exclusive_receive() as previous:
            if previous.frequency is None or previous.mode is None:
                raise WsprInhibit("FT-891 prior receive state is unavailable")
            resolve_radio_band(previous.frequency)
            bfo = radio.read_ssb_bfo()
            if ft8 is not None and ft8.is_running:
                if not ft8.suspend_for_other_receive():
                    raise WsprInhibit("FT8 is decoding; press Button 3 again when idle")
                resume_ft8 = True
            lease = Ft891WsprLease(radio, previous, bfo)
            try:
                yield lease
            finally:
                lease.restore()
    except (RadioError, RadioBandResolutionError) as error:
        raise WsprInhibit("FT-891 receive is unverified or unavailable") from error
    finally:
        if resume_ft8 and ft8 is not None:
            ft8.start()
