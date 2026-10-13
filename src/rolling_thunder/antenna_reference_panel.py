"""Nonblocking controller and pure presentation for antenna reference data."""

from __future__ import annotations

from concurrent.futures import CancelledError, Executor, Future, ThreadPoolExecutor
from dataclasses import dataclass, field, replace
from enum import StrEnum
from threading import Lock
from uuid import UUID

from rolling_thunder.antenna_reference_domain import (
    AntennaInstallation,
    FrequencyRegion,
)
from rolling_thunder.antenna_reference_service import (
    AntennaReferencePublication,
    AntennaReferenceService,
    AntennaReferenceSnapshot,
    AntennaScenarioEvaluation,
)
from rolling_thunder.config import ConfigurationError


class AntennaPanelStatus(StrEnum):
    """Background publication state for the optional dashboard panel."""

    IDLE = "idle"
    LOADING = "loading"
    READY = "ready"
    ERROR = "error"


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
    evaluations: tuple[AntennaScenarioEvaluation, ...] = ()


@dataclass(frozen=True)
class AntennaPanelState:
    """Immutable state read by Tkinter without storage access."""

    status: AntennaPanelStatus = AntennaPanelStatus.IDLE
    snapshot: AntennaReferenceSnapshot = field(default_factory=AntennaReferenceSnapshot)
    cards: tuple[AntennaReferenceCard, ...] = ()
    selected_index: int | None = None
    error: str | None = None

    @property
    def selected_card(self) -> AntennaReferenceCard | None:
        if self.selected_index is None or not self.cards:
            return None
        return self.cards[self.selected_index]


def _mhz_range(lower_hz: int, upper_hz: int) -> str:
    return f"{lower_hz / 1_000_000:g}-{upper_hz / 1_000_000:g} MHz"


def build_reference_cards(
    snapshot: AntennaReferenceSnapshot,
    evaluations: tuple[AntennaScenarioEvaluation, ...] = (),
) -> tuple[AntennaReferenceCard, ...]:
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
        catalog_regions = tuple(dict.fromkeys(band.region for band in catalog.bands)) or (
            FrequencyRegion.OTHER,
        )
        for installation in installations:
            unmatched_scenario = installation is not None and any(
                evaluation.scenario.installation_id == installation.installation_id
                and not any(
                    band.frequencies.contains(evaluation.scenario.frequency)
                    for band in catalog.bands
                )
                for evaluation in evaluations
            )
            regions = (
                (*catalog_regions, FrequencyRegion.OTHER)
                if unmatched_scenario and FrequencyRegion.OTHER not in catalog_regions
                else catalog_regions
            )
            for region in regions:
                bands = tuple(
                    f"{band.label} {_mhz_range(band.frequencies.lower.hz, band.frequencies.upper.hz)}"
                    for band in catalog.bands
                    if band.region is region
                )
                gains = tuple(
                    f"{_mhz_range(gain.frequencies.lower.hz, gain.frequencies.upper.hz)} "
                    f"{gain.gain_db:g} {gain.unit.value} "
                    f"(source: {gain.provenance.source})"
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
                    f"{'UNKNOWN' if loss.loss_db is None else f'{loss.loss_db:g} dB'} "
                    f"(source: {loss.provenance.source})"
                    for loss in installation.loss_segments
                )
                card_evaluations = () if installation is None else tuple(
                    evaluation
                    for evaluation in evaluations
                    if evaluation.scenario.installation_id == installation.installation_id
                    and (
                        any(
                            band.region is region
                            and band.frequencies.contains(evaluation.scenario.frequency)
                            for band in catalog.bands
                        )
                        or (
                            region is FrequencyRegion.OTHER
                            and not any(
                                band.frequencies.contains(evaluation.scenario.frequency)
                                for band in catalog.bands
                            )
                        )
                    )
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
                        evaluations=card_evaluations,
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
    """Publish one config-backed reference snapshot from a bounded worker."""

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
        """Queue one startup configuration load without blocking the caller."""
        with self._lock:
            if self._closed or self._state.status is not AntennaPanelStatus.IDLE:
                return False
            self._state = replace(
                self._state,
                status=AntennaPanelStatus.LOADING,
                error=None,
            )
        future = self._executor.submit(self._service.load_publication)
        future.add_done_callback(self._snapshot_finished)
        return True

    def _snapshot_finished(self, future: Future[AntennaReferencePublication]) -> None:
        try:
            publication = future.result()
            cards = build_reference_cards(
                publication.snapshot,
                publication.evaluations,
            )
        except (CancelledError, ConfigurationError, ValueError) as error:
            self._publish_error(f"Antenna reference load failed: {error}")
            return
        with self._lock:
            if self._closed:
                return
            self._state = AntennaPanelState(
                status=AntennaPanelStatus.READY,
                snapshot=publication.snapshot,
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
                error=None,
            )
            return True

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
