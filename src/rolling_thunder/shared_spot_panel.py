"""UI-independent shared POTA/DX panel state and selection controller."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Protocol

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import ForgeRemoteProviderHealth
from rolling_thunder.pi_forge_spot_service import PiForgeSpotState, PiForgeSpotStateKind
from rolling_thunder.radio import RadioBand
from rolling_thunder.radio_band import RadioBandResolutionError, resolve_radio_band
from rolling_thunder.spot_domain import (
    SpotIdentity,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
    format_optional_spot_value,
)
from rolling_thunder.spot_selection import SpotSelectionController, SpotSelectionState

Clock = Callable[[], datetime]
_DEFAULT_POTA_BAND = RadioBand.BAND_20M
_DEFAULT_MAXIMUM_AGE = timedelta(minutes=15)
_POTA_BANDS: tuple[RadioBand, ...] = (
    RadioBand.BAND_80M,
    RadioBand.BAND_40M,
    RadioBand.BAND_20M,
    RadioBand.BAND_17M,
    RadioBand.BAND_15M,
    RadioBand.BAND_12M,
    RadioBand.BAND_10M,
)
_DATA_DISPLAY_MODES = frozenset(
    {
        "DATA",
        "DIGITAL",
        "HELL",
        "JS8",
        "JT65",
        "JT9",
        "MFSK",
        "OLIVIA",
        "PACKET",
        "PSK",
        "PSK31",
        "RTTY",
        "SSTV",
    }
)


class SharedSpotModeFilter(StrEnum):
    """Operator-facing mode groups used by the migrated shared POTA view."""

    SSB = "SSB"
    CW = "CW"
    FT4 = "FT4"
    FT8 = "FT8"
    DATA = "DATA"
    ALL = "ALL"


_POTA_MODES: tuple[SharedSpotModeFilter, ...] = (
    SharedSpotModeFilter.SSB,
    SharedSpotModeFilter.CW,
    SharedSpotModeFilter.FT4,
    SharedSpotModeFilter.FT8,
    SharedSpotModeFilter.DATA,
    SharedSpotModeFilter.ALL,
)


class SharedSpotStateProvider(Protocol):
    """Provide the latest already-published Pi Forge shared-spot state."""

    @property
    def latest_forge_spot_state(self) -> PiForgeSpotState | None:
        """Return immutable shared state without performing I/O."""
        ...


@dataclass(frozen=True, slots=True)
class SharedSpotPanelRow:
    """Provider-neutral row prepared for mobile presentation."""

    identity: SpotIdentity
    provider: SpotProvider
    callsign: str
    operator_name: str | None
    grid: str | None
    frequency: Frequency
    mode: RadioMode
    display_mode: str
    spotted_at: datetime
    age_seconds: int
    source_metadata: tuple[SpotSourceMetadataItem, ...]
    park_reference: str | None = None
    park_name: str | None = None
    location_code: str | None = None
    selected: bool = False

    @property
    def operator_name_text(self) -> str:
        """Format unknown names only at the presentation boundary."""
        return format_optional_spot_value(self.operator_name)

    @property
    def grid_text(self) -> str:
        """Format unknown grids only at the presentation boundary."""
        return format_optional_spot_value(self.grid)

    @property
    def frequency_text(self) -> str:
        """Return a compact MHz value suitable for a mobile row."""
        return f"{self.frequency.hz / 1_000_000:.3f}"

    @property
    def age_minutes(self) -> int:
        """Return whole elapsed minutes without inventing negative age."""
        return self.age_seconds // 60


@dataclass(frozen=True, slots=True)
class SharedSpotPanelState:
    """Immutable shared-panel presentation snapshot."""

    provider: SpotProvider
    source_kind: PiForgeSpotStateKind | None
    snapshot_revision: int | None
    generated_at: datetime | None
    last_success_at: datetime | None
    last_attempt_at: datetime | None
    source_error: str | None
    provider_health: ForgeRemoteProviderHealth | None
    rows: tuple[SharedSpotPanelRow, ...]
    selected_identity: SpotIdentity | None
    staged_identity: SpotIdentity | None
    pota_band: RadioBand
    pota_mode_filter: SharedSpotModeFilter
    pota_maximum_age: timedelta

    @property
    def source_enabled(self) -> bool:
        """Return whether the optional Pi Forge path is configured."""
        return self.source_kind is not None

    @property
    def has_usable_snapshot(self) -> bool:
        """Return whether a cached, live, or retained source is present."""
        return self.generated_at is not None

    @property
    def status_label(self) -> str:
        """Return a compact truthful shared-source status token."""
        if self.source_kind is None:
            return "FORGE DISABLED"
        if self.source_kind is PiForgeSpotStateKind.EMPTY:
            return "NO SHARED SPOTS"
        if self.source_kind is PiForgeSpotStateKind.CACHED:
            return "CACHED"
        if self.source_kind is PiForgeSpotStateKind.RETAINED:
            return "RETAINED"
        return "LIVE"

    @property
    def filter_label(self) -> str:
        """Return the provider-appropriate compact filter summary."""
        if self.provider is SpotProvider.DX:
            return "DX    ALL BANDS / ALL MODES"
        return (
            "POTA    BAND: "
            f"{self.pota_band.value.removesuffix('m')}    MODE: {self.pota_mode_filter.value}"
        )


class SharedSpotPanelController:
    """Filter one shared snapshot and preserve selection by stable identity."""

    def __init__(
        self,
        provider: SharedSpotStateProvider,
        *,
        clock: Clock | None = None,
        maximum_pota_age: timedelta = _DEFAULT_MAXIMUM_AGE,
    ) -> None:
        if maximum_pota_age < timedelta(0):
            raise ValueError("shared POTA maximum spot age must not be negative")
        self._provider_source = provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._provider = SpotProvider.POTA
        self._pota_band = _DEFAULT_POTA_BAND
        self._pota_mode_filter = SharedSpotModeFilter.SSB
        self._pota_maximum_age = maximum_pota_age
        now = self._aware_now()
        self._selection = SpotSelectionController(SpotSnapshot.empty(generated_at=now))

    @property
    def provider(self) -> SpotProvider:
        """Return the active POTA or DX presentation view."""
        return self._provider

    @property
    def selected_identity(self) -> SpotIdentity | None:
        """Return the selected stable identity after synchronizing source state."""
        return self._selection_state().selected_identity

    @property
    def selected_spot(self) -> SpotRecord | None:
        """Return the selected shared-domain record, if still visible."""
        return self._selection_state().selected_spot

    @property
    def visible_spots(self) -> tuple[SpotRecord, ...]:
        """Return the current provider-filtered canonical shared-domain rows."""
        return self._selection_state().snapshot.spots

    @property
    def state(self) -> SharedSpotPanelState:
        """Build one immutable presentation state from already-published data."""
        now = self._aware_now()
        source = self._provider_source.latest_forge_spot_state
        selection = self._replace_visible_snapshot(source, now)
        provider_health = self._provider_health(source)
        rows = tuple(
            self._row_from_spot(
                spot,
                now=now,
                selected=spot.identity == selection.selected_identity,
            )
            for spot in selection.snapshot.spots
        )
        return SharedSpotPanelState(
            provider=self._provider,
            source_kind=source.kind if source is not None else None,
            snapshot_revision=source.snapshot_revision if source is not None else None,
            generated_at=source.generated_at if source is not None else None,
            last_success_at=source.last_success_at if source is not None else None,
            last_attempt_at=source.last_attempt_at if source is not None else None,
            source_error=source.last_error if source is not None else None,
            provider_health=provider_health,
            rows=rows,
            selected_identity=selection.selected_identity,
            staged_identity=selection.staged_identity,
            pota_band=self._pota_band,
            pota_mode_filter=self._pota_mode_filter,
            pota_maximum_age=self._pota_maximum_age,
        )

    def activate(
        self,
        provider: SpotProvider,
        *,
        current_frequency: Frequency | None = None,
    ) -> SharedSpotPanelState:
        """Activate one provider view and apply the POTA current-band default."""
        if provider is not self._provider:
            self._selection.invalidate_context()
        self._provider = provider
        if provider is SpotProvider.POTA:
            self._pota_band = self._supported_pota_band(current_frequency)
        return self.state

    def select_next(self) -> SharedSpotPanelState:
        """Move to the next visible stable identity without wrapping."""
        self._sync_selection()
        self._selection.select_next()
        return self.state

    def select_previous(self) -> SharedSpotPanelState:
        """Move to the previous visible stable identity without wrapping."""
        self._sync_selection()
        self._selection.select_previous()
        return self.state

    def clear_selection(self) -> SharedSpotPanelState:
        """Clear selected and staged spot state."""
        self._selection.clear_selection()
        return self.state

    def stage_selected(self) -> SharedSpotPanelState:
        """Stage action-critical values without performing radio work."""
        self._sync_selection()
        self._selection.stage_selected()
        return self.state

    def cancel_staging(self) -> SharedSpotPanelState:
        """Cancel shared staged state without performing external work."""
        self._selection.cancel_staging()
        return self.state

    def previous_pota_band(self) -> SharedSpotPanelState:
        """Cycle to the previous legacy mobile POTA band."""
        current = _POTA_BANDS.index(self._pota_band)
        self._pota_band = _POTA_BANDS[(current - 1) % len(_POTA_BANDS)]
        return self.state

    def next_pota_band(self) -> SharedSpotPanelState:
        """Cycle to the next legacy mobile POTA band."""
        current = _POTA_BANDS.index(self._pota_band)
        self._pota_band = _POTA_BANDS[(current + 1) % len(_POTA_BANDS)]
        return self.state

    def previous_pota_mode(self) -> SharedSpotPanelState:
        """Cycle to the previous legacy mobile POTA mode group."""
        current = _POTA_MODES.index(self._pota_mode_filter)
        self._pota_mode_filter = _POTA_MODES[(current - 1) % len(_POTA_MODES)]
        return self.state

    def next_pota_mode(self) -> SharedSpotPanelState:
        """Cycle to the next legacy mobile POTA mode group."""
        current = _POTA_MODES.index(self._pota_mode_filter)
        self._pota_mode_filter = _POTA_MODES[(current + 1) % len(_POTA_MODES)]
        return self.state

    def reset_pota_filters(self) -> SharedSpotPanelState:
        """Restore the current mobile 20-meter SSB POTA defaults."""
        self._pota_band = _DEFAULT_POTA_BAND
        self._pota_mode_filter = SharedSpotModeFilter.SSB
        return self.state

    def _sync_selection(self) -> SpotSelectionState:
        return self._replace_visible_snapshot(
            self._provider_source.latest_forge_spot_state,
            self._aware_now(),
        )

    def _selection_state(self) -> SpotSelectionState:
        return self._sync_selection()

    def _replace_visible_snapshot(
        self,
        source: PiForgeSpotState | None,
        now: datetime,
    ) -> SpotSelectionState:
        if source is None or source.snapshot is None:
            visible = SpotSnapshot.empty(generated_at=now)
        else:
            spots = tuple(
                spot
                for spot in source.snapshot.spots
                if self._spot_is_visible(spot, now=now)
            )
            visible = SpotSnapshot(
                generated_at=source.snapshot.generated_at,
                spots=spots,
            )
        return self._selection.replace_snapshot(visible)

    def _spot_is_visible(self, spot: SpotRecord, *, now: datetime) -> bool:
        if spot.provider is not self._provider:
            return False
        if self._provider is SpotProvider.DX:
            return True

        if self._resolved_band(spot.frequency) is not self._pota_band:
            return False
        if not self._matches_pota_mode(spot):
            return False
        return now - spot.spotted_at <= self._pota_maximum_age

    def _matches_pota_mode(self, spot: SpotRecord) -> bool:
        mode_filter = self._pota_mode_filter
        if mode_filter is SharedSpotModeFilter.ALL:
            return True
        display_mode = spot.display_mode
        if mode_filter is SharedSpotModeFilter.SSB:
            return display_mode in {"SSB", "PHONE", "LSB", "USB"} or spot.mode in {
                RadioMode.LSB,
                RadioMode.USB,
            }
        if mode_filter is SharedSpotModeFilter.CW:
            return display_mode == "CW"
        if mode_filter is SharedSpotModeFilter.FT4:
            return display_mode == "FT4"
        if mode_filter is SharedSpotModeFilter.FT8:
            return display_mode == "FT8"
        return display_mode in _DATA_DISPLAY_MODES

    def _supported_pota_band(self, frequency: Frequency | None) -> RadioBand:
        if frequency is None:
            return _DEFAULT_POTA_BAND
        band = self._resolved_band(frequency)
        return band if band in _POTA_BANDS else _DEFAULT_POTA_BAND

    @staticmethod
    def _resolved_band(frequency: Frequency) -> RadioBand | None:
        try:
            return resolve_radio_band(frequency)
        except RadioBandResolutionError:
            return None

    def _provider_health(
        self,
        source: PiForgeSpotState | None,
    ) -> ForgeRemoteProviderHealth | None:
        if source is None:
            return None
        return next(
            (item for item in source.providers if item.provider is self._provider),
            None,
        )

    @staticmethod
    def _row_from_spot(
        spot: SpotRecord,
        *,
        now: datetime,
        selected: bool,
    ) -> SharedSpotPanelRow:
        age_seconds = max(0, int((now - spot.spotted_at).total_seconds()))
        pota = spot.pota
        return SharedSpotPanelRow(
            identity=spot.identity,
            provider=spot.provider,
            callsign=str(spot.callsign),
            operator_name=spot.operator_name,
            grid=str(spot.grid) if spot.grid is not None else None,
            frequency=spot.frequency,
            mode=spot.mode,
            display_mode=spot.display_mode,
            spotted_at=spot.spotted_at,
            age_seconds=age_seconds,
            source_metadata=spot.source_metadata,
            park_reference=str(pota.park_reference) if pota is not None else None,
            park_name=pota.park_name if pota is not None else None,
            location_code=pota.location_code if pota is not None else None,
            selected=selected,
        )

    def _aware_now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("shared spot panel clock must return an aware datetime")
        return value.astimezone(UTC)
