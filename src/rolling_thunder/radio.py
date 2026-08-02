"""Typed hardware-independent radio boundary."""

from enum import StrEnum
from typing import Protocol, runtime_checkable

from rolling_thunder.domain import Frequency, RadioMode, RadioState


class RadioBand(StrEnum):
    """Amateur bands supported by the initial mobile radio workflow."""

    BAND_160M = "160m"
    BAND_80M = "80m"
    BAND_60M = "60m"
    BAND_40M = "40m"
    BAND_30M = "30m"
    BAND_20M = "20m"
    BAND_17M = "17m"
    BAND_15M = "15m"
    BAND_12M = "12m"
    BAND_10M = "10m"
    BAND_6M = "6m"


class RadioError(Exception):
    """Base exception for radio operations."""


class RadioConnectionError(RadioError):
    """Raised when an operation requires a connected radio."""


class BandChangeRequiredError(RadioError):
    """Raised when a frequency request would cross bands without selection."""


class RadioVerificationError(RadioError):
    """Raised when radio read-back does not match an operator request."""


@runtime_checkable
class Radio(Protocol):
    """Small typed boundary implemented by mock and physical radios.

    This interface intentionally has no transmit or PTT operation. Rolling
    Thunder may read state and perform operator-requested tuning only.
    """

    def connect(self) -> RadioState:
        """Connect to the radio and return its current state."""
        ...

    def disconnect(self) -> RadioState:
        """Disconnect from the radio and return its current state."""
        ...

    def get_state(self) -> RadioState:
        """Return the latest immutable radio-state snapshot."""
        ...

    def refresh_state(self) -> RadioState:
        """Read the current hardware state and return a new snapshot."""
        ...

    def set_frequency(self, frequency: Frequency) -> RadioState:
        """Set an operator-requested frequency and return the resulting state."""
        ...

    def set_mode(self, mode: RadioMode) -> RadioState:
        """Set an operator-requested mode and return the resulting state."""
        ...

    def select_band(self, band: RadioBand) -> RadioState:
        """Select and verify a band without choosing the final frequency or mode."""
        ...
