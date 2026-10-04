"""FT-891 radio adapter built on the typed CAT transport boundary."""

from collections.abc import Callable
from datetime import UTC, datetime
from threading import RLock
from typing import cast

from rolling_thunder.cat_transport import CatTransport
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.fm_repeater import (
    CtcssPlan,
    FmRepeaterConfigurationOutcome,
    FmRepeaterConfigurationRequest,
    FmRepeaterConfigurationStatus,
    FmRepeaterUnsupportedReason,
    resolve_ctcss_plan,
)
from rolling_thunder.ft891_cat import (
    Ft891CatError,
    Ft891OperatingContext,
    Ft891SsbBfo,
    Ft891SsbMicSelect,
    encode_cat_transmit_off,
    encode_cat_transmit_on,
    encode_memory_to_vfo_a,
    encode_read_6m_repeater_offset,
    encode_read_ctcss_behavior,
    encode_read_ctcss_tone,
    encode_read_frequency,
    encode_read_information,
    encode_read_memory_channel,
    encode_read_meter,
    encode_read_mode,
    encode_read_narrow_enabled,
    encode_read_noise_blanker_enabled,
    encode_read_power,
    encode_read_preamp_enabled,
    encode_read_repeater_shift,
    encode_read_ssb_bfo,
    encode_read_ssb_mic_select,
    encode_select_band_memory,
    encode_set_6m_repeater_offset,
    encode_set_ctcss_behavior,
    encode_set_ctcss_tone,
    encode_set_frequency,
    encode_set_mode,
    encode_set_narrow_enabled,
    encode_set_noise_blanker_enabled,
    encode_set_power,
    encode_set_preamp_enabled,
    encode_set_repeater_shift,
    encode_set_ssb_bfo,
    encode_set_ssb_mic_select,
    memory_channel_for_band,
    parse_6m_repeater_offset_reply,
    parse_ctcss_behavior_reply,
    parse_ctcss_tone_reply,
    parse_frequency_reply,
    parse_memory_channel_reply,
    parse_meter_reply,
    parse_mode_reply,
    parse_narrow_enabled_reply,
    parse_noise_blanker_enabled_reply,
    parse_operating_context_reply,
    parse_power_reply,
    parse_preamp_enabled_reply,
    parse_repeater_shift_reply,
    parse_ssb_bfo_reply,
    parse_ssb_mic_select_reply,
)
from rolling_thunder.radio import (
    BandChangeRequiredError,
    RadioBand,
    RadioConnectionError,
    RadioVerificationError,
)
from rolling_thunder.radio_band import (
    RadioBandResolutionError,
    resolve_radio_band,
)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


class Ft891Radio:
    """Hardware adapter implementing the safe Rolling Thunder radio boundary."""

    def __init__(self, transport: CatTransport, *, clock: Clock = _utc_now) -> None:
        self._transport = transport
        self._clock = clock
        self._operation_lock = RLock()
        self._cp6_cat_ptt_asserted = False
        self._state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            updated_at=self._timestamp(),
        )

    def connect(self) -> RadioState:
        """Open CAT and read the current frequency and mode."""
        with self._operation_lock:
            try:
                self._transport.open()
                frequency, mode = self._read_hardware_state()
            except (RadioConnectionError, Ft891CatError) as error:
                error_message = self._close_after_failure(
                    str(error) or error.__class__.__name__
                )
                self._state = RadioState(
                    connection_state=RadioConnectionState.ERROR,
                    transmitting=False,
                    updated_at=self._timestamp(),
                    last_error=error_message,
                )
                if isinstance(error, RadioConnectionError):
                    raise
                raise RadioConnectionError(
                    f"Could not connect to FT-891: {error}"
                ) from error

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=frequency,
                mode=mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )
            return self._state

    def disconnect(self) -> RadioState:
        """Close CAT and report a disconnected state."""
        with self._operation_lock:
            if self._cp6_cat_ptt_asserted:
                self._release_cp6_cat_ptt()
            self._transport.close()
            self._state = RadioState(
                connection_state=RadioConnectionState.DISCONNECTED,
                transmitting=False,
                updated_at=self._timestamp(),
            )
            return self._state

    def get_state(self) -> RadioState:
        """Return the latest immutable state snapshot."""
        with self._operation_lock:
            return self._state

    def create_cp6_cat_ptt_capability(self) -> "Ft891CatPttCapability":
        """Create the isolated owner-test CAT PTT capability for Checkpoint 6."""
        return Ft891CatPttCapability(self)

    def _assert_cp6_cat_ptt(self) -> None:
        with self._operation_lock:
            self._require_connected()
            if self._cp6_cat_ptt_asserted:
                return
            try:
                self._transport.command(encode_cat_transmit_on())
            except RadioConnectionError:
                try:
                    self._transport.command(encode_cat_transmit_off())
                except RadioConnectionError:
                    pass
                self._cp6_cat_ptt_asserted = False
                raise
            self._cp6_cat_ptt_asserted = True

    def _release_cp6_cat_ptt(self) -> None:
        with self._operation_lock:
            if not self._cp6_cat_ptt_asserted:
                return
            self._require_connected()
            try:
                self._transport.command(encode_cat_transmit_off())
            finally:
                self._cp6_cat_ptt_asserted = False

    def read_cp6_tx_meters(self) -> tuple[int, int, int]:
        """Read raw ALC, power, and SWR meters for the supervised CP6 test."""
        with self._operation_lock:
            self._require_connected()
            alc = parse_meter_reply(
                self._transport.query(encode_read_meter(4)),
                expected_selector=4,
            )
            power = parse_meter_reply(
                self._transport.query(encode_read_meter(5)),
                expected_selector=5,
            )
            swr = parse_meter_reply(
                self._transport.query(encode_read_meter(6)),
                expected_selector=6,
            )
            return alc, power, swr

    def refresh_state(self) -> RadioState:
        """Read current frequency and mode, detecting CAT device loss."""
        with self._operation_lock:
            self._require_connected()
            previous_frequency = self._state.frequency
            previous_mode = self._state.mode
            try:
                frequency, mode = self._read_hardware_state()
            except (RadioConnectionError, Ft891CatError) as error:
                error_message = self._close_after_failure(
                    str(error) or error.__class__.__name__
                )
                self._state = RadioState(
                    connection_state=RadioConnectionState.ERROR,
                    frequency=previous_frequency,
                    mode=previous_mode,
                    transmitting=False,
                    updated_at=self._timestamp(),
                    last_error=error_message,
                )
                if isinstance(error, RadioConnectionError):
                    raise
                raise RadioConnectionError(
                    f"Could not refresh FT-891 state: {error}"
                ) from error

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=frequency,
                mode=mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )
            return self._state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Set and verify VFO-A frequency without implicitly changing bands."""
        with self._operation_lock:
            self._require_connected()
            current_frequency = self._current_frequency()
            target_band = resolve_radio_band(frequency)

            try:
                current_band = resolve_radio_band(current_frequency)
            except RadioBandResolutionError as error:
                raise BandChangeRequiredError(
                    "Current FT-891 frequency does not identify a supported amateur "
                    f"band; select {target_band.value} before setting frequency."
                ) from error

            if current_band is not target_band:
                raise BandChangeRequiredError(
                    f"Select {target_band.value} before changing frequency from "
                    f"{current_band.value}."
                )

            self._transport.command(encode_set_frequency(frequency))
            verified_frequency = parse_frequency_reply(
                self._transport.query(encode_read_frequency())
            )

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=verified_frequency,
                mode=self._state.mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )

            if verified_frequency != frequency:
                raise RadioVerificationError(
                    "FT-891 frequency verification failed: requested "
                    f"{frequency.hz} Hz but read back {verified_frequency.hz} Hz."
                )

            return self._state

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Set and verify the main receiver mode."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_mode(mode))
            verified_mode = parse_mode_reply(
                self._transport.query(encode_read_mode())
            )

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=self._state.frequency,
                mode=verified_mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )

            if verified_mode is not mode:
                raise RadioVerificationError(
                    "FT-891 mode verification failed: requested "
                    f"{mode.value} but read back {verified_mode.value}."
                )

            return self._state

    def read_preamp_enabled(self) -> bool:
        """Read FT-891 VFO-A preamp state; False means IPO is active."""
        with self._operation_lock:
            self._require_connected()
            return parse_preamp_enabled_reply(
                self._transport.query(encode_read_preamp_enabled())
            )

    def set_preamp_enabled(self, enabled: bool) -> bool:
        """Set and verify FT-891 VFO-A preamp/IPO state."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_preamp_enabled(enabled))
            verified = parse_preamp_enabled_reply(
                self._transport.query(encode_read_preamp_enabled())
            )
            if verified is not enabled:
                raise RadioVerificationError(
                    "FT-891 PRE-AMP/IPO verification failed: requested "
                    f"{'AMP' if enabled else 'IPO'}."
                )
            return verified

    def set_narrow_enabled(self, enabled: bool) -> bool:
        """Set and verify FT-891 VFO-A NARROW state."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_narrow_enabled(enabled))
            verified = parse_narrow_enabled_reply(
                self._transport.query(encode_read_narrow_enabled())
            )
            if verified is not enabled:
                raise RadioVerificationError(
                    "FT-891 NARROW verification failed."
                )
            return verified

    def set_noise_blanker_enabled(self, enabled: bool) -> bool:
        """Set and verify FT-891 VFO-A Noise Blanker state."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_noise_blanker_enabled(enabled))
            verified = parse_noise_blanker_enabled_reply(
                self._transport.query(encode_read_noise_blanker_enabled())
            )
            if verified is not enabled:
                raise RadioVerificationError(
                    "FT-891 Noise Blanker verification failed."
                )
            return verified

    def read_power_watts(self) -> int:
        """Read the configured FT-891 transmitter power through CAT."""
        with self._operation_lock:
            self._require_connected()
            return parse_power_reply(self._transport.query(encode_read_power()))

    def set_power_watts(self, power_watts: int) -> int:
        """Set and verify the configured FT-891 transmitter power."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_power(power_watts))
            verified = parse_power_reply(self._transport.query(encode_read_power()))
            if verified != power_watts:
                raise RadioVerificationError(
                    "FT-891 power verification failed: requested "
                    f"{power_watts} W but read back {verified} W."
                )
            return verified

    def read_ssb_mic_select(self) -> Ft891SsbMicSelect:
        """Read documented FT-891 menu 11-05 SSB MIC SELECT."""
        with self._operation_lock:
            self._require_connected()
            return parse_ssb_mic_select_reply(self._transport.query(encode_read_ssb_mic_select()))

    def set_ssb_mic_select(self, value: Ft891SsbMicSelect) -> Ft891SsbMicSelect:
        """Set and verify documented FT-891 menu 11-05 SSB MIC SELECT."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_ssb_mic_select(value))
            verified = parse_ssb_mic_select_reply(self._transport.query(encode_read_ssb_mic_select()))
            if verified is not value:
                raise RadioVerificationError(
                    "FT-891 SSB MIC SELECT verification failed: requested "
                    f"{value.value.upper()} but read back {verified.value.upper()}."
                )
            return verified

    def read_ssb_bfo(self) -> Ft891SsbBfo:
        """Read documented FT-891 menu 11-07 SSB BFO."""
        with self._operation_lock:
            self._require_connected()
            return parse_ssb_bfo_reply(self._transport.query(encode_read_ssb_bfo()))

    def set_ssb_bfo(self, value: Ft891SsbBfo) -> Ft891SsbBfo:
        """Set and verify documented FT-891 menu 11-07 SSB BFO."""
        with self._operation_lock:
            self._require_connected()
            self._transport.command(encode_set_ssb_bfo(value))
            verified = parse_ssb_bfo_reply(self._transport.query(encode_read_ssb_bfo()))
            if verified is not value:
                raise RadioVerificationError(
                    "FT-891 SSB-BFO verification failed: requested "
                    f"{value.value.upper()} but read back {verified.value.upper()}."
                )
            return verified

    def select_band(self, band: RadioBand) -> RadioState:
        """Recall the dedicated band memory to VFO-A and verify the result."""
        with self._operation_lock:
            self._require_connected()
            expected_memory = memory_channel_for_band(band)

            self._transport.command(encode_select_band_memory(band))
            selected_memory = parse_memory_channel_reply(
                self._transport.query(encode_read_memory_channel())
            )
            if selected_memory != expected_memory:
                raise RadioVerificationError(
                    "FT-891 band-memory verification failed: requested memory "
                    f"{expected_memory:03d} for {band.value} but read back "
                    f"{selected_memory:03d}."
                )

            self._transport.command(encode_memory_to_vfo_a())
            frequency, mode = self._read_hardware_state()

            self._state = RadioState(
                connection_state=RadioConnectionState.CONNECTED,
                frequency=frequency,
                mode=mode,
                transmitting=False,
                updated_at=self._timestamp(),
            )

            try:
                verified_band = resolve_radio_band(frequency)
            except RadioBandResolutionError as error:
                raise RadioVerificationError(
                    "FT-891 band-memory verification failed because the recalled "
                    f"VFO-A frequency {frequency.hz} Hz is outside supported bands."
                ) from error

            if verified_band is not band:
                raise RadioVerificationError(
                    "FT-891 band-memory verification failed: requested "
                    f"{band.value} via memory {expected_memory:03d} but recalled "
                    f"{verified_band.value}."
                )

            return self._state

    def configure_fm_repeater(
        self,
        request: FmRepeaterConfigurationRequest,
    ) -> FmRepeaterConfigurationOutcome:
        """Configure one six-meter FM repeater atomically with exact read-back."""
        if not isinstance(request, FmRepeaterConfigurationRequest):
            raise TypeError("request must be an FmRepeaterConfigurationRequest")

        unsupported = self._preflight_fm_repeater(request)
        if unsupported is not None:
            return unsupported

        tone_plan = cast(CtcssPlan, resolve_ctcss_plan(request))

        with self._operation_lock:
            self._require_connected()
            if self._state.transmitting:
                raise RadioConnectionError(
                    "FM repeater configuration is unavailable while the radio is transmitting."
                )

            starting_band: RadioBand | None = None
            if self._state.frequency is not None:
                try:
                    starting_band = resolve_radio_band(self._state.frequency)
                except RadioBandResolutionError:
                    starting_band = None

            self.select_band(RadioBand.BAND_6M)
            context = parse_operating_context_reply(
                self._transport.query(encode_read_information())
            )
            if context is not Ft891OperatingContext.VFO:
                raise RadioVerificationError(
                    "FT-891 repeater VFO verification failed after the 6 m "
                    f"memory-to-VFO handoff: read back {context.value}."
                )

            self.set_frequency(request.rx_frequency)
            self.set_mode(RadioMode.FM)
            self._set_and_verify_repeater_shift(request)
            self._set_and_verify_6m_offset(request)
            self._set_and_verify_ctcss(tone_plan)

            return FmRepeaterConfigurationOutcome(
                status=FmRepeaterConfigurationStatus.CONFIGURED,
                state=self._state,
                manual_band_confirmation_required=starting_band is not RadioBand.BAND_6M,
            )

    def _preflight_fm_repeater(
        self,
        request: FmRepeaterConfigurationRequest,
    ) -> FmRepeaterConfigurationOutcome | None:
        try:
            target_band = resolve_radio_band(request.rx_frequency)
        except RadioBandResolutionError:
            return self._unsupported_repeater(
                FmRepeaterUnsupportedReason.UNSUPPORTED_BAND,
                "REPEATER RX FREQUENCY IS NOT IN A SUPPORTED AMATEUR BAND — CONFIGURE MANUALLY",
            )
        if target_band is not RadioBand.BAND_6M:
            return self._unsupported_repeater(
                FmRepeaterUnsupportedReason.UNSUPPORTED_BAND,
                "ONLY 6 METER FM REPEATER CONFIGURATION IS SUPPORTED — CONFIGURE MANUALLY",
            )

        if request.offset_hz > 4_000_000:
            return self._unsupported_repeater(
                FmRepeaterUnsupportedReason.OFFSET_OUT_OF_RANGE,
                "6 METER REPEATER OFFSET EXCEEDS THE FT-891 CAT RANGE — CONFIGURE MANUALLY",
            )
        if request.offset_hz % 10_000 != 0:
            return self._unsupported_repeater(
                FmRepeaterUnsupportedReason.OFFSET_STEP_UNSUPPORTED,
                "6 METER REPEATER OFFSET IS NOT A 10 KHZ CAT STEP — CONFIGURE MANUALLY",
            )

        tone_plan = resolve_ctcss_plan(request)
        if isinstance(tone_plan, FmRepeaterUnsupportedReason):
            if tone_plan is FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES:
                message = (
                    "INDEPENDENT RX/TX CTCSS TONES ARE NOT SUPPORTED — "
                    "CONFIGURE REPEATER MANUALLY"
                )
            else:
                message = "RX-ONLY CTCSS IS NOT SUPPORTED — CONFIGURE REPEATER MANUALLY"
            return self._unsupported_repeater(tone_plan, message)

        if tone_plan.tone_hz is not None:
            try:
                encode_set_ctcss_tone(tone_plan.tone_hz)
            except Ft891CatError:
                return self._unsupported_repeater(
                    FmRepeaterUnsupportedReason.CTCSS_TONE_UNSUPPORTED,
                    "CTCSS TONE IS NOT IN THE FT-891 CAT TONE TABLE — CONFIGURE MANUALLY",
                )
        return None

    @staticmethod
    def _unsupported_repeater(
        reason: FmRepeaterUnsupportedReason,
        manual_handoff: str,
    ) -> FmRepeaterConfigurationOutcome:
        return FmRepeaterConfigurationOutcome(
            status=FmRepeaterConfigurationStatus.UNSUPPORTED_MANUAL_HANDOFF,
            unsupported_reason=reason,
            manual_handoff=manual_handoff,
        )

    def _set_and_verify_repeater_shift(
        self,
        request: FmRepeaterConfigurationRequest,
    ) -> None:
        self._transport.command(encode_set_repeater_shift(request.shift_direction))
        verified = parse_repeater_shift_reply(
            self._transport.query(encode_read_repeater_shift())
        )
        if verified is not request.shift_direction:
            raise RadioVerificationError(
                "FT-891 repeater-shift verification failed: requested "
                f"{request.shift_direction.value} but read back {verified.value}."
            )

    def _set_and_verify_6m_offset(
        self,
        request: FmRepeaterConfigurationRequest,
    ) -> None:
        self._transport.command(encode_set_6m_repeater_offset(request.offset_hz))
        verified = parse_6m_repeater_offset_reply(
            self._transport.query(encode_read_6m_repeater_offset())
        )
        if verified != request.offset_hz:
            raise RadioVerificationError(
                "FT-891 6 m repeater-offset verification failed: requested "
                f"{request.offset_hz} Hz but read back {verified} Hz."
            )

    def _set_and_verify_ctcss(self, plan: CtcssPlan) -> None:
        if plan.tone_hz is not None:
            self._transport.command(encode_set_ctcss_tone(plan.tone_hz))
            verified_tone = parse_ctcss_tone_reply(
                self._transport.query(encode_read_ctcss_tone())
            )
            if verified_tone != plan.tone_hz:
                raise RadioVerificationError(
                    "FT-891 CTCSS-tone verification failed: requested "
                    f"{plan.tone_hz} Hz but read back {verified_tone} Hz."
                )

        self._transport.command(encode_set_ctcss_behavior(plan.behavior))
        verified_behavior = parse_ctcss_behavior_reply(
            self._transport.query(encode_read_ctcss_behavior())
        )
        if verified_behavior is not plan.behavior:
            raise RadioVerificationError(
                "FT-891 CTCSS verification failed: requested "
                f"{plan.behavior.value} but read back {verified_behavior.value}."
            )

    def _read_hardware_state(self) -> tuple[Frequency, RadioMode]:
        frequency = parse_frequency_reply(
            self._transport.query(encode_read_frequency())
        )
        mode = parse_mode_reply(self._transport.query(encode_read_mode()))
        return frequency, mode

    def _close_after_failure(self, error_message: str) -> str:
        try:
            self._transport.close()
        except RadioConnectionError as close_error:
            return (
                f"{error_message}; additionally failed to close CAT transport: "
                f"{close_error}"
            )
        return error_message

    def _require_connected(self) -> None:
        if self._state.connection_state is not RadioConnectionState.CONNECTED:
            raise RadioConnectionError(
                "FT-891 operation requires a connected radio."
            )

    def _current_frequency(self) -> Frequency:
        frequency = self._state.frequency
        if frequency is None:
            raise RadioConnectionError(
                "FT-891 operation requires a known current frequency."
            )
        return frequency

    def _timestamp(self) -> datetime:
        timestamp = self._clock()
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("FT-891 clock must return a timezone-aware datetime.")
        return timestamp.astimezone(UTC)



class Ft891CatPttCapability:
    """Checkpoint 6 owner-test CAT PTT capability.

    This concrete capability is intentionally absent from the generic Radio
    protocol and has no audio, QSO-state, retry, UI, voice, or network authority.
    """

    def __init__(self, radio: Ft891Radio) -> None:
        self._radio = radio
        self._closed = False

    def key(self) -> None:
        """Assert CAT PTT once for an explicitly supervised CP6 test."""
        if self._closed:
            raise RadioConnectionError("FT-891 CAT PTT capability is closed.")
        self._radio._assert_cp6_cat_ptt()

    def release(self) -> None:
        """Return the FT-891 to receive; repeated calls are safe."""
        if self._closed:
            return
        self._radio._release_cp6_cat_ptt()

    def cancel(self) -> None:
        """Cancel the owner test by returning the FT-891 to receive."""
        self.release()

    def close(self) -> None:
        """Release PTT before permanently closing this capability."""
        if self._closed:
            return
        try:
            self._radio._release_cp6_cat_ptt()
        finally:
            self._closed = True
