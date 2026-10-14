"""Tests for the nonblocking antenna-reference panel and safe controls."""

from concurrent.futures import Executor, Future
from pathlib import Path
from typing import Any
from uuid import UUID

from rolling_thunder.antenna_reference_commands import AntennaAwareActivePanelCommands
from rolling_thunder.antenna_reference_domain import (
    AntennaCatalogEntry,
    AntennaInstallation,
    BandAssociation,
    ExposureScenario,
    FrequencyRegion,
    FrequencySegment,
    GainSegment,
    GainUnit,
    InstallationBandAssignment,
    LossSegment,
    ModeProfile,
    TextProvenance,
)
from rolling_thunder.antenna_reference_panel import (
    AntennaPanelStatus,
    AntennaReferencePanelController,
    build_reference_cards,
)
from rolling_thunder.antenna_reference_repository import AntennaReferenceRepository
from rolling_thunder.antenna_reference_service import (
    AntennaReferenceService,
    AntennaReferenceSnapshot,
)
from rolling_thunder.antenna_reference_ui import (
    card_summary_lines,
    evaluation_lines,
    scenario_evaluation_lines,
)
from rolling_thunder.config import ConfigurationError, ConfigurationFileError
from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency

ANTENNA_ID = UUID("10000000-0000-0000-0000-000000000001")
INSTALLATION_ID = UUID("20000000-0000-0000-0000-000000000001")
HF_BAND_ID = UUID("30000000-0000-0000-0000-000000000001")
SIX_M_BAND_ID = UUID("30000000-0000-0000-0000-000000000002")
SOURCE = TextProvenance(source="operator manual page 12")
MODE_ID = UUID("40000000-0000-0000-0000-000000000001")


def sample_records() -> tuple[AntennaCatalogEntry, AntennaInstallation]:
    catalog = AntennaCatalogEntry(
        antenna_id=ANTENNA_ID,
        name="Measured multiband reference",
        manufacturer="Example",
        model="REF-1",
        provenance=SOURCE,
        bands=(
            BandAssociation(
                association_id=HF_BAND_ID,
                label="20 m",
                region=FrequencyRegion.HF,
                frequencies=FrequencySegment(
                    lower=Frequency(hz=14_000_000),
                    upper=Frequency(hz=14_350_000),
                ),
                provenance=SOURCE,
            ),
            BandAssociation(
                association_id=SIX_M_BAND_ID,
                label="6 m",
                region=FrequencyRegion.VHF,
                frequencies=FrequencySegment(
                    lower=Frequency(hz=50_000_000),
                    upper=Frequency(hz=54_000_000),
                ),
                provenance=SOURCE,
            ),
        ),
        gains=(
            GainSegment(
                frequencies=FrequencySegment(
                    lower=Frequency(hz=14_000_000),
                    upper=Frequency(hz=14_350_000),
                ),
                gain_db=2.0,
                unit=GainUnit.DBD,
                provenance=SOURCE,
            ),
            GainSegment(
                frequencies=FrequencySegment(
                    lower=Frequency(hz=50_000_000),
                    upper=Frequency(hz=54_000_000),
                ),
                gain_db=3.1,
                unit=GainUnit.DBI,
                provenance=SOURCE,
            ),
        ),
    )
    installation = AntennaInstallation(
        installation_id=INSTALLATION_ID,
        antenna_id=ANTENNA_ID,
        name="Roof mount A",
        location_description="measured roof location",
        losses_complete=True,
        loss_segments=(
            LossSegment(
                name="feedline and switch",
                frequencies=FrequencySegment(
                    lower=Frequency(hz=1_800_000),
                    upper=Frequency(hz=54_000_000),
                ),
                loss_db=1.2,
                provenance=TextProvenance(source="operator VNA measurement"),
            ),
        ),
        band_assignments=(
            InstallationBandAssignment(association_id=HF_BAND_ID, provenance=SOURCE),
            InstallationBandAssignment(association_id=SIX_M_BAND_ID, provenance=SOURCE),
        ),
        provenance=TextProvenance(source="operator installation measurement"),
    )
    return catalog, installation


class FakeSource:
    def __init__(self, snapshot: AntennaReferenceSnapshot) -> None:
        self.snapshot = snapshot
        self.load_calls = 0

    def load_snapshot(self) -> AntennaReferenceSnapshot:
        self.load_calls += 1
        return self.snapshot


class ControlledExecutor(Executor):
    """Hold work until a test explicitly runs it."""

    def __init__(self) -> None:
        self.pending: list[tuple[Future[Any], Any, tuple[Any, ...], dict[str, Any]]] = []

    def submit(self, fn: Any, /, *args: Any, **kwargs: Any) -> Future[Any]:
        future: Future[Any] = Future()
        self.pending.append((future, fn, args, kwargs))
        return future

    def run_next(self) -> None:
        future, fn, args, kwargs = self.pending.pop(0)
        try:
            future.set_result(fn(*args, **kwargs))
        except (ConfigurationError, ValueError) as error:
            future.set_exception(error)


def test_empty_snapshot_starts_without_fabricated_records() -> None:
    cards = build_reference_cards(AntennaReferenceSnapshot())

    assert cards == ()


def test_cards_separate_hf_and_explicit_six_m_vhf_with_units_and_losses() -> None:
    catalog, installation = sample_records()

    cards = build_reference_cards(
        AntennaReferenceSnapshot(catalog=(catalog,), installations=(installation,))
    )

    assert [card.region for card in cards] == [FrequencyRegion.HF, FrequencyRegion.VHF]
    assert cards[0].gain_lines == (
        "14-14.35 MHz 2 dBd (source: operator manual page 12)",
    )
    assert cards[1].loss_lines == (
        "feedline and switch 1.8-54 MHz 1.2 dB (source: operator VNA measurement)",
    )
    assert "6 M  EXPLICITLY ASSOCIATED" in "\n".join(card_summary_lines(cards[1]))


def test_controller_defers_yaml_load_to_injected_executor() -> None:
    source = FakeSource(AntennaReferenceSnapshot())
    executor = ControlledExecutor()
    controller = AntennaReferencePanelController(
        AntennaReferenceService(source),
        executor=executor,
    )

    assert controller.start() is True
    assert controller.state.status is AntennaPanelStatus.LOADING
    assert source.load_calls == 0

    executor.run_next()

    assert source.load_calls == 1
    assert controller.state.status is AntennaPanelStatus.READY
    assert controller.state.cards == ()
    assert controller.start() is False


def test_controller_surfaces_missing_config_without_publishing_safe_state() -> None:
    class MissingSource:
        def load_snapshot(self) -> AntennaReferenceSnapshot:
            raise ConfigurationFileError("manual antenna YAML is missing")

    executor = ControlledExecutor()
    controller = AntennaReferencePanelController(
        AntennaReferenceService(MissingSource()),
        executor=executor,
    )

    controller.start()
    executor.run_next()

    assert controller.state.status is AntennaPanelStatus.ERROR
    assert controller.state.cards == ()
    assert controller.state.snapshot == AntennaReferenceSnapshot()
    assert "manual antenna YAML is missing" in (controller.state.error or "")


def test_configured_six_m_fm_evaluation_publishes_both_limits_without_verdict() -> None:
    catalog, installation = sample_records()
    mode = ModeProfile(
        mode_profile_id=MODE_ID,
        name="6 m FM",
        rf_envelope_duty=1.0,
        provenance=SOURCE,
    )
    scenario = ExposureScenario(
        installation_id=INSTALLATION_ID,
        mode_profile_id=MODE_ID,
        name="File-backed six-foot hypothetical",
        frequency=Frequency(hz=52_000_000),
        forward_tx_watts=40.0,
        controlled_tx_fraction=0.25,
        uncontrolled_tx_fraction=0.05,
        provenance=TextProvenance(source="reviewed manual configuration"),
    )
    source = FakeSource(
        AntennaReferenceSnapshot(
            catalog=(catalog,),
            installations=(installation,),
            mode_profiles=(mode,),
            scenarios=(scenario,),
        )
    )
    executor = ControlledExecutor()
    controller = AntennaReferencePanelController(
        AntennaReferenceService(source),
        executor=executor,
    )
    controller.start()
    executor.run_next()

    evaluations = controller.state.cards[1].evaluations
    assert len(evaluations) == 1
    result = evaluations[0].result

    assert result.inputs_complete is True
    assert result.controlled is not None
    assert result.controlled.limit.averaging_minutes == 6
    assert result.uncontrolled is not None
    assert result.uncontrolled.limit.averaging_minutes == 30
    rendered = "\n".join(evaluation_lines(result)).casefold()
    assert "controlled / 6 min" in rendered
    assert "uncontrolled / 30 min" in rendered
    assert "not a safety or compliance finding" in rendered
    assert "compliant" not in rendered
    assert "unsafe" not in rendered
    scenario_rendered = "\n".join(scenario_evaluation_lines(evaluations[0]))
    assert "40 W FORWARD" in scenario_rendered
    assert "hypothetical_six_foot" in scenario_rendered
    assert "reviewed manual configuration" in scenario_rendered

    incomplete = result.model_copy(
        update={
            "inputs_complete": False,
            "missing_inputs": ("gain is unknown",),
            "controlled": None,
            "uncontrolled": None,
        }
    )
    incomplete_lines = "\n".join(
        evaluation_lines(incomplete, frequency_mhz=52.0)
    )
    assert "CONTROLLED / 6 MIN LIMIT" in incomplete_lines
    assert "UNCONTROLLED / 30 MIN LIMIT" in incomplete_lines


def test_repository_lists_multiple_installations_from_temporary_database(tmp_path: Path) -> None:
    catalog, installation = sample_records()
    repository = AntennaReferenceRepository(tmp_path / "antenna.db")
    repository.save_catalog(catalog)
    repository.save_installation(installation)
    second = installation.model_copy(
        update={
            "installation_id": UUID("20000000-0000-0000-0000-000000000002"),
            "name": "Portable mount B",
            "loss_segments": (),
            "band_assignments": (),
        }
    )
    repository.save_installation(second)

    assert [item.name for item in repository.list_installations()] == [
        "Portable mount B",
        "Roof mount A",
    ]


class FakeDelegate:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        def call(*_args: Any) -> bool:
            self.calls.append(name)
            return True

        return call


class FakePanel:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def select_previous(self) -> bool:
        self.calls.append("previous")
        return True

    def select_next(self) -> bool:
        self.calls.append("next")
        return True

def test_physical_commands_are_view_only_in_antenna_context() -> None:
    navigation = ContextNavigationController(include_antennas=True)
    navigation.select(ContextId.ANTENNAS)
    delegate = FakeDelegate()
    panel = FakePanel()
    commands = AntennaAwareActivePanelCommands(
        navigation,
        delegate,  # type: ignore[arg-type]
        panel,
    )

    assert commands.move_previous() is True
    assert commands.move_next() is True
    assert commands.back() is False
    assert commands.activate_selection() is False
    assert commands.primary() is False
    assert commands.secondary() is False
    assert commands.tertiary() is False
    assert panel.calls == ["previous", "next"]
    assert delegate.calls == []
