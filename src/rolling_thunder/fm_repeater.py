"""Typed FM repeater configuration capability with no transmit authority."""

from decimal import Decimal
from enum import StrEnum
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from rolling_thunder.domain import DomainModel, Frequency, RadioState


class FmRepeaterShiftDirection(StrEnum):
    """Transmit shift relative to the configured receive frequency."""

    MINUS = "minus"
    SIMPLEX = "simplex"
    PLUS = "plus"


class CtcssBehavior(StrEnum):
    """CTCSS behavior representable by the FT-891 CAT interface."""

    OFF = "off"
    ENCODE_ONLY = "encode_only"
    ENCODE_DECODE = "encode_decode"


class FmRepeaterUnsupportedReason(StrEnum):
    """Typed reasons a requested repeater configuration cannot be represented."""

    UNSUPPORTED_BAND = "unsupported_band"
    INDEPENDENT_CTCSS_TONES = "independent_ctcss_tones"
    RECEIVE_ONLY_CTCSS = "receive_only_ctcss"
    CTCSS_TONE_UNSUPPORTED = "ctcss_tone_unsupported"
    OFFSET_OUT_OF_RANGE = "offset_out_of_range"
    OFFSET_STEP_UNSUPPORTED = "offset_step_unsupported"


class FmRepeaterConfigurationStatus(StrEnum):
    """Truthful result of a repeater-configuration request."""

    CONFIGURED = "configured"
    UNSUPPORTED_MANUAL_HANDOFF = "unsupported_manual_handoff"


class FmRepeaterConfigurationRequest(DomainModel):
    """Action-critical values needed to configure one analogue FM repeater."""

    rx_frequency: Frequency
    shift_direction: FmRepeaterShiftDirection
    offset_hz: int = Field(ge=0, strict=True)
    rx_tone_hz: Decimal | None = Field(default=None, gt=0)
    tx_tone_hz: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_shift_and_offset(self) -> "FmRepeaterConfigurationRequest":
        """Reject internally contradictory shift/offset requests."""
        if self.shift_direction is FmRepeaterShiftDirection.SIMPLEX:
            if self.offset_hz != 0:
                raise ValueError("simplex repeater configuration requires zero offset")
        elif self.offset_hz == 0:
            raise ValueError("plus/minus repeater configuration requires nonzero offset")
        return self


class CtcssPlan(DomainModel):
    """One exact shared-tone CTCSS plan supported by the typed boundary."""

    behavior: CtcssBehavior
    tone_hz: Decimal | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_tone_requirement(self) -> "CtcssPlan":
        if self.behavior is CtcssBehavior.OFF and self.tone_hz is not None:
            raise ValueError("CTCSS off cannot carry a tone")
        if self.behavior is not CtcssBehavior.OFF and self.tone_hz is None:
            raise ValueError("enabled CTCSS requires a tone")
        return self


class FmRepeaterConfigurationOutcome(DomainModel):
    """Verified configuration result or explicit unsupported/manual handoff."""

    status: FmRepeaterConfigurationStatus
    state: RadioState | None = None
    unsupported_reason: FmRepeaterUnsupportedReason | None = None
    manual_handoff: str | None = Field(default=None, max_length=500)
    manual_band_confirmation_required: bool = False

    @model_validator(mode="after")
    def validate_status_payload(self) -> "FmRepeaterConfigurationOutcome":
        if self.status is FmRepeaterConfigurationStatus.CONFIGURED:
            if self.state is None:
                raise ValueError("configured repeater outcome requires radio state")
            if self.unsupported_reason is not None or self.manual_handoff is not None:
                raise ValueError("configured repeater outcome cannot be unsupported")
        else:
            if self.unsupported_reason is None or self.manual_handoff is None:
                raise ValueError("unsupported repeater outcome requires a manual handoff")
        return self


@runtime_checkable
class FmRepeaterConfigurableRadio(Protocol):
    """High-level repeater configuration capability with no transmit operation."""

    def configure_fm_repeater(
        self,
        request: FmRepeaterConfigurationRequest,
    ) -> FmRepeaterConfigurationOutcome:
        """Configure one repeater or return a truthful unsupported result."""
        ...


def resolve_ctcss_plan(
    request: FmRepeaterConfigurationRequest,
) -> CtcssPlan | FmRepeaterUnsupportedReason:
    """Resolve exact CTCSS semantics without guessing independent tone behavior."""
    rx_tone = request.rx_tone_hz
    tx_tone = request.tx_tone_hz

    if rx_tone is None and tx_tone is None:
        return CtcssPlan(behavior=CtcssBehavior.OFF)
    if rx_tone is None and tx_tone is not None:
        return CtcssPlan(
            behavior=CtcssBehavior.ENCODE_ONLY,
            tone_hz=tx_tone,
        )
    if rx_tone is not None and tx_tone is None:
        return FmRepeaterUnsupportedReason.RECEIVE_ONLY_CTCSS
    if rx_tone == tx_tone:
        return CtcssPlan(
            behavior=CtcssBehavior.ENCODE_DECODE,
            tone_hz=rx_tone,
        )
    return FmRepeaterUnsupportedReason.INDEPENDENT_CTCSS_TONES
