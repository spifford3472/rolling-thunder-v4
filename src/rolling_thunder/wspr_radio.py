"""Reserve the existing FT-891 tuning and DigiRig receive paths for WSPR."""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from time import sleep

from rolling_thunder.domain import Frequency, RadioMode, RadioState
from rolling_thunder.ft8.receive import FT8ReceiveService
from rolling_thunder.ft891_cat import Ft891SsbBfo
from rolling_thunder.ft891_radio import Ft891Radio
from rolling_thunder.radio import RadioError, RadioVerificationError
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.receive_tuning import ReceiveTuningService
from rolling_thunder.wspr_receive import WsprBandUnavailable, WsprInhibit

_READBACK_SETTLE_S = 0.08
_LOGGER = logging.getLogger(__name__)


class _ReceiveSettingChanged(WsprInhibit):
    """A verified mismatch in frequency, mode or BFO."""


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
                self._verify_expected_with_recheck(current)
                self._changed = True
                frequency = Frequency(hz=dial_hz)
                try:
                    self._tuner.tune(frequency, RadioMode.USB)
                    if self._radio.read_ssb_bfo() is not Ft891SsbBfo.USB:
                        self._radio.set_ssb_bfo(Ft891SsbBfo.USB)
                    # Read the complete hardware state after the last write.
                    verified = self._radio.refresh_state()
                    bfo = self._radio.read_ssb_bfo()
                    if verified.frequency != frequency or verified.mode is not RadioMode.USB:
                        raise RadioVerificationError("WSPR frequency or mode did not verify.")
                    if bfo is not Ft891SsbBfo.USB:
                        raise RadioVerificationError("WSPR USB BFO did not verify.")
                except RadioVerificationError as error:
                    # A failed band's readback becomes the next expected state.
                    self._expected = self._radio.refresh_state()
                    self._expected_bfo = self._radio.read_ssb_bfo()
                    raise WsprBandUnavailable from error
                self._expected = verified
                self._expected_bfo = bfo
        except RadioError as error:
            raise WsprInhibit("FT-891 receive authority lost") from error

    def verify(self, dial_hz: int) -> None:
        try:
            with self._radio.receive_operation() as current:
                self._verify_expected_with_recheck(current)
                if self._expected.frequency != Frequency(hz=dial_hz):
                    raise WsprInhibit("FT-891 is on the wrong WSPR frequency")
        except RadioError as error:
            raise WsprInhibit("FT-891 receive authority lost") from error

    def restore(self) -> None:
        if not self._changed:
            return
        try:
            with self._radio.receive_operation() as current:
                self._verify_expected_with_recheck(current)
                assert self._previous.frequency is not None and self._previous.mode is not None
                self._tuner.tune(self._previous.frequency, self._previous.mode)
                self._radio.set_ssb_bfo(self._bfo)
        except RadioError as error:
            raise WsprInhibit("FT-891 receive restore failed; check the radio") from error

    def _verify_expected_with_recheck(self, current: RadioState) -> None:
        try:
            self._verify_expected(current)
        except _ReceiveSettingChanged:
            # Confirm a single inconsistent read after the rig has settled.
            # The second read rechecks RX and makes no CAT writes.
            sleep(_READBACK_SETTLE_S)
            with self._radio.receive_operation() as refreshed:
                self._verify_expected(refreshed)

    def _verify_expected(self, current: RadioState) -> None:
        if current.frequency != self._expected.frequency:
            expected = self._expected.frequency
            received = current.frequency
            expected_hz = expected.hz if expected is not None else "unknown"
            received_hz = received.hz if received is not None else "unknown"
            raise _ReceiveSettingChanged(
                f"FT-891 frequency changed ({expected_hz} → {received_hz} Hz)"
            )
        if current.mode is not self._expected.mode:
            raise _ReceiveSettingChanged(
                f"FT-891 mode changed ({self._expected.mode} → {current.mode})"
            )
        bfo = self._radio.read_ssb_bfo()
        if bfo is not self._expected_bfo:
            raise _ReceiveSettingChanged(
                f"FT-891 SSB BFO changed ({self._expected_bfo.value} → {bfo.value})"
            )


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
            except BaseException:
                try:
                    lease.restore()
                except WsprInhibit as restore_error:
                    _LOGGER.warning("WSPR receive restore withheld: %s", restore_error)
                raise
            else:
                lease.restore()
    except (RadioError, RadioBandResolutionError) as error:
        raise WsprInhibit("FT-891 receive is unverified or unavailable") from error
    finally:
        if resume_ft8 and ft8 is not None:
            ft8.start()
