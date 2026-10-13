"""Nonblocking controller and pure presentation for antenna reference data."""

from __future__ import annotations

from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import StrEnum
from threading import Lock
from uuid import UUID

from pydantic import Field

from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    ExposureScenario,
    FrequencyRegion,
    GroundReflectionModel,
    ModeProfile,
    TextProvenance,
    standard_mode_profiles,
)
from rolling_thunder.antenna_reference_service import (
    AntennaReferenceService,
    AntennaReferenceSnapshot,
)
from rolling_thunder.domain import DomainModel, Frequency
from rolling_thunder.rf_exposure_calculator import RfExposureResult
from rolling_thunder.storage import StorageError


class AntennaPanelStatus(StrEnum):
    """Background publication state for the optional dashboard panel."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    EVALUATING = "evaluating"
    ERROR = "error"


class ReferenceMode(StrEnum):
    """Sourced reference mode choices exposed by the advisory form."""

    FT8 = "FT8"
    SSB_UNPROCESSED = "SSB unprocessed"
    SSB_PROCESSED = "SSB heavily processed"
    SIX_M_FM = "6 m FM"

    @property
    def profile(self) -> ModeProfile:
        """Return the immutable sourced mode profile without storing it."""
        return next(profile for profile in standard_mode_profiles() if profile.name == self.value)


class AntennaEvaluationRequest(DomainModel):
    """Explicit operator-entered inputs for one transient what-if evaluation."""

    installation_id: UUID
    mode: ReferenceMode
    frequency_mhz: float = Field(ge=0.3, le=100_000, allow_inf_nan=False)
    forward_tx_watts: float = Field(gt=0, allow_inf_nan=False)
    controlled_tx_fraction: float = Field(gt=0, le=1, allow_inf_nan=False)
    uncontrolled_tx_fraction: float = Field(gt=0, le=1, allow_inf_nan=False)
    distance_feet: float = Field(gt=0, allow_inf_nan=False)
    distance_verified: bool = False
    ground_reflection_model: GroundReflectionModel = GroundReflectionModel.ARRL_TYPICAL_GROUND
    provenance: TextProvenance


@dataclass(frozen=True)
class AntennaReferenceCard:
    """One region-specific, presentation-ready antenna/installation card."""

    antenna_id: UUID
    installation_id: UUID | None
    region: FrequencyRegion
    antenna_name: str
    installation_name: str
    bands: tuple[str, ...]
    gain_lines: tuple[str, ...]
    loss_lines: tuple[str, ...]
    provenance: str
    losses_complete: bool


@dataclass(frozen=True)
class AntennaPanelState:
    """Immutable state read by Tkinter without storage access."""

    status: AntennaPanelStatus = AntennaPanelStatus.IDLE
    snapshot: AntennaReferenceSnapshot = field(default_factory=AntennaReferenceSnapshot)
    cards: tuple[AntennaReferenceCard, ...] = ()
    selected_index: int | None = None
    evaluation: RfExposureResult | None = None
    evaluation_request: AntennaEvaluationRequest | None = None
    error: str | None = None

    @property
    def selected_card(self) -> AntennaReferenceCard | None:
        if self.selected_index is None or not self.cards:
            return None
        return self.cards[self.selected_index]


def _mhz_range(lower_hz: int, upper_hz: int) -> str:
    return f"{lower_hz / 1_000_000:g}-{upper_hz / 1_000_000:g} MHz"


def build_reference_cards(snapshot: AntennaReferenceSnapshot) -> tuple[AntennaReferenceCard, ...]:
    """Build HF/VHF/UHF cards without inferring bands, gain, or loss."""
    installations_by_antenna: dict[UUID, list[AntennaInstallation]] = {}
    for stored_installation in snapshot.installations:
        installations_by_antenna.setdefault(stored_installation.antenna_id, []).append(
            stored_installation
        )

    cards: list[AntennaReferenceCard] = []
    region_order = {
        FrequencyRegion.HF: 0,
        FrequencyRegion.VHF: 1,
        FrequencyRegion.UHF: 2,
        FrequencyRegion.OTHER: 3,
    }
    for catalog in snapshot.catalog:
        known_installations = installations_by_antenna.get(catalog.antenna_id, [])
        installations: tuple[AntennaInstallation | None, ...] = (
            tuple(known_installations) if known_installations else (None,)
        )
        regions = tuple(dict.fromkeys(band.region for band in catalog.bands)) or (
            FrequencyRegion.OTHER,
        )
        for installation in installations:
            for region in regions:
                bands = tuple(
                    f"{band.label} {_mhz_range(band.frequencies.lower.hz, band.frequencies.upper.hz)}"
                    for band in catalog.bands
                    if band.region is region
                )
                gains = tuple(
                    f"{_mhz_range(gain.frequencies.lower.hz, gain.frequencies.upper.hz)} "
                    f"{gain.gain_db:g} {gain.unit.value}"
                    for gain in catalog.gains
                    if any(
                        band.region is region
                        and band.frequencies.lower.hz <= gain.frequencies.upper.hz
                        and gain.frequencies.lower.hz <= band.frequencies.upper.hz
                        for band in catalog.bands
                    )
                )
                losses = () if installation is None else tuple(
                    f"{loss.name} {_mhz_range(loss.frequencies.lower.hz, loss.frequencies.upper.hz)} "
                    f"{'UNKNOWN' if loss.loss_db is None else f'{loss.loss_db:g} dB'}"
                    for loss in installation.loss_segments
                )
                cards.append(
                    AntennaReferenceCard(
                        antenna_id=catalog.antenna_id,
                        installation_id=(
                            None if installation is None else installation.installation_id
                        ),
                        region=region,
                        antenna_name=catalog.name,
                        installation_name=(
                            "NO INSTALLATION" if installation is None else installation.name
                        ),
                        bands=bands,
                        gain_lines=gains,
                        loss_lines=losses,
                        provenance=(
                            catalog.provenance.source
                            if installation is None
                            else f"Antenna: {catalog.provenance.source}; "
                            f"installation: {installation.provenance.source}"
                        ),
                        losses_complete=(
                            False if installation is None else installation.losses_complete
                        ),
                    )
                )
    return tuple(
        sorted(
            cards,
            key=lambda item: (
                region_order[item.region],
                item.antenna_name.casefold(),
                item.installation_name.casefold(),
            ),
        )
    )


class AntennaReferencePanelController:
    """Publish repository state and evaluations from one bounded worker."""

    def __init__(
        self,
        service: AntennaReferenceService,
        *,
        executor: Executor | None = None,
    ) -> None:
        self._service = service
        self._executor = executor or ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="antenna-reference",
        )
        self._owns_executor = executor is None
        self._state = AntennaPanelState()
        self._lock = Lock()
        self._closed = False

    @property
    def state(self) -> AntennaPanelState:
        with self._lock:
            return self._state

    def start(self) -> bool:
        """Queue the initial database snapshot without blocking the caller."""
        with self._lock:
            if self._closed or self._state.status is AntennaPanelStatus.LOADING:
                return False
            self._state = replace(
                self._state,
                status=AntennaPanelStatus.LOADING,
                error=None,
            )
        future = self._executor.submit(self._service.load_snapshot)
        future.add_done_callback(self._snapshot_finished)
        return True

    def _snapshot_finished(self, future: Future[AntennaReferenceSnapshot]) -> None:
        try:
            snapshot = future.result()
            cards = build_reference_cards(snapshot)
        except (CancelledError, StorageError, ValueError) as error:
            self._publish_error(f"Antenna reference load failed: {error}")
            return
        with self._lock:
            if self._closed:
                return
            self._state = AntennaPanelState(
                status=AntennaPanelStatus.READY,
                snapshot=snapshot,
                cards=cards,
                selected_index=0 if cards else None,
            )

    def select_previous(self) -> bool:
        return self._move(-1)

    def select_next(self) -> bool:
        return self._move(1)

    def _move(self, offset: int) -> bool:
        with self._lock:
            if not self._state.cards or self._state.selected_index is None:
                return False
            selected = (self._state.selected_index + offset) % len(self._state.cards)
            if selected == self._state.selected_index:
                return False
            self._state = replace(
                self._state,
                selected_index=selected,
                evaluation=None,
                evaluation_request=None,
                error=None,
            )
            return True

    def clear_evaluation(self) -> bool:
        with self._lock:
            if self._state.evaluation is None and self._state.error is None:
                return False
            self._state = replace(
                self._state,
                evaluation=None,
                evaluation_request=None,
                error=None,
                status=AntennaPanelStatus.READY,
            )
            return True

    def start_evaluation(self, request: AntennaEvaluationRequest) -> bool:
        """Queue a transient advisory calculation using the published snapshot."""
        with self._lock:
            if self._closed or self._state.status is AntennaPanelStatus.EVALUATING:
                return False
            snapshot = self._state.snapshot
            installation = next(
                (
                    item
                    for item in snapshot.installations
                    if item.installation_id == request.installation_id
                ),
                None,
            )
            if installation is None:
                self._state = replace(self._state, error="Selected installation is unavailable.")
                return False
            catalog = next(
                (item for item in snapshot.catalog if item.antenna_id == installation.antenna_id),
                None,
            )
            if catalog is None:
                self._state = replace(self._state, error="Selected antenna is unavailable.")
                return False
            self._state = replace(
                self._state,
                status=AntennaPanelStatus.EVALUATING,
                evaluation=None,
                evaluation_request=request,
                error=None,
            )

        future = self._executor.submit(
            self._evaluate,
            catalog,
            installation,
            request,
        )
        future.add_done_callback(self._evaluation_finished)
        return True

    def _evaluate(
        self,
        catalog: AntennaCatalogEntry,
        installation: AntennaInstallation,
        request: AntennaEvaluationRequest,
    ) -> RfExposureResult:
        profile = request.mode.profile
        scenario = ExposureScenario(
            installation_id=installation.installation_id,
            mode_profile_id=profile.mode_profile_id,
            name=f"Transient {request.mode.value} advisory",
            frequency=Frequency(hz=round(request.frequency_mhz * 1_000_000)),
            forward_tx_watts=request.forward_tx_watts,
            controlled_tx_fraction=request.controlled_tx_fraction,
            uncontrolled_tx_fraction=request.uncontrolled_tx_fraction,
            occupant_distance_m=request.distance_feet * 0.3048,
            occupant_distance_verified=request.distance_verified,
            ground_reflection_model=request.ground_reflection_model,
            provenance=request.provenance,
        )
        return self._service.evaluate_inputs(
            catalog=catalog,
            installation=installation,
            mode=profile,
            scenario=scenario,
        )

    def _evaluation_finished(self, future: Future[RfExposureResult]) -> None:
        try:
            result = future.result()
        except (CancelledError, StorageError, ValueError) as error:
            self._publish_error(f"RF advisory calculation failed: {error}")
            return
        with self._lock:
            if self._closed:
                return
            self._state = replace(
                self._state,
                status=AntennaPanelStatus.READY,
                evaluation=result,
                error=None,
            )

    def _publish_error(self, message: str) -> None:
        with self._lock:
            if self._closed:
                return
            self._state = replace(
                self._state,
                status=AntennaPanelStatus.ERROR,
                error=message,
            )

    def close(self) -> None:
        with self._lock:
            self._closed = True
        if self._owns_executor:
            self._executor.shutdown(wait=False, cancel_futures=True)
