from concurrent.futures import Executor, Future
from datetime import UTC, datetime, timedelta
from typing import Any
from collections.abc import Callable

from rolling_thunder.context_navigation import ContextId, ContextNavigationController
from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.pota_detail_overlay import PotaDetailOverlayController
from rolling_thunder.pota_enrichment import PotaEnrichmentService
from rolling_thunder.pota_spots import ParkReference, PotaSpot


class ImmediateExecutor(Executor):
    def submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[Any]:
        future: Future[Any] = Future()
        try:
            future.set_result(fn(*args, **kwargs))
        except BaseException as error:
            future.set_exception(error)
        return future


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class SelectedSpotProvider:
    def __init__(self, selected_spot: PotaSpot | None) -> None:
        self.selected_spot = selected_spot


def spot() -> PotaSpot:
    return PotaSpot(
        activator="KI5VNB",
        park=ParkReference(
            reference="US-1940",
            name="Caesar Creek State Park",
            location_code="US-OH",
            latitude=39.489,
            longitude=-84.055,
        ),
        frequency=Frequency(hz=14_260_000),
        mode=RadioMode.USB,
        spot_mode="SSB",
        spotted_at=datetime(2026, 8, 2, 5, 0, tzinfo=UTC),
    )


def controller_fixture() -> tuple[
    PotaDetailOverlayController,
    ContextNavigationController,
    MutableClock,
]:
    navigation = ContextNavigationController(ContextId.POTA)
    clock = MutableClock(datetime(2026, 8, 2, 5, 1, tzinfo=UTC))
    enrichment = PotaEnrichmentService(executor=ImmediateExecutor())
    enrichment.start()
    controller = PotaDetailOverlayController(
        navigation,
        SelectedSpotProvider(spot()),
        enrichment,
        clock=clock,
    )
    return controller, navigation, clock


def test_overlay_shows_selected_park_and_expires_after_twenty_seconds() -> None:
    controller, _navigation, clock = controller_fixture()

    assert controller.show_selected() is True
    assert controller.state.visible is True
    assert controller.state.snapshot is not None
    assert controller.state.snapshot.park_name == "Caesar Creek State Park"

    clock.value += timedelta(seconds=19)
    assert controller.state.visible is True

    clock.value += timedelta(seconds=1)
    assert controller.state.visible is False


def test_overlay_can_be_dismissed_immediately() -> None:
    controller, _navigation, _clock = controller_fixture()

    assert controller.show_selected() is True
    assert controller.hide() is True
    assert controller.state.visible is False
    assert controller.hide() is False


def test_panel_change_dismisses_overlay() -> None:
    controller, navigation, _clock = controller_fixture()
    assert controller.show_selected() is True

    navigation.select(ContextId.DX)

    assert controller.state.visible is False
    navigation.select(ContextId.POTA)
    assert controller.state.visible is False


def test_overlay_requires_a_selected_pota_spot() -> None:
    navigation = ContextNavigationController(ContextId.POTA)
    enrichment = PotaEnrichmentService(executor=ImmediateExecutor())
    enrichment.start()
    controller = PotaDetailOverlayController(
        navigation,
        SelectedSpotProvider(None),
        enrichment,
    )

    assert controller.show_selected() is False
    assert controller.state.visible is False
