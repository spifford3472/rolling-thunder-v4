"""Tests for the UI-independent shared POTA/DX panel controller."""

from datetime import UTC, datetime, timedelta

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import (
    ForgeRemoteProviderHealth,
    ForgeRemoteProviderStatus,
)
from rolling_thunder.pi_forge_spot_service import (
    PiForgeSpotErrorKind,
    PiForgeSpotState,
    PiForgeSpotStateKind,
)
from rolling_thunder.radio import RadioBand
from rolling_thunder.shared_spot_panel import (
    SharedSpotModeFilter,
    SharedSpotPanelController,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
)

NOW = datetime(2026, 8, 8, 0, 45, tzinfo=UTC)
GENERATED = datetime(2026, 8, 8, 0, 44, tzinfo=UTC)


class FakeSharedSource:
    """Mutable no-I/O source standing in for ApplicationRuntime."""

    def __init__(self, state: PiForgeSpotState | None) -> None:
        self.latest_forge_spot_state = state


def pota_spot(
    park: str,
    frequency_hz: int,
    *,
    callsign: str = "K1POTA",
    mode: RadioMode = RadioMode.USB,
    display_mode: str = "SSB",
    age_minutes: int = 2,
    operator_name: str | None = "Park Operator",
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference=park,
            frequency=frequency,
        ),
        callsign=callsign,
        operator_name=operator_name,
        grid="EM79xm",
        frequency=frequency,
        mode=mode,
        display_mode=display_mode,
        spotted_at=NOW - timedelta(minutes=age_minutes),
        source_metadata=(
            SpotSourceMetadataItem(key="comments", value="portable"),
        ),
        pota=PotaSpotMetadata(
            park_reference=park,
            park_name=f"Park {park}",
            location_code="US-OH",
            latitude=39.7,
            longitude=-84.1,
        ),
    )


def dx_spot(
    callsign: str,
    frequency_hz: int,
    *,
    mode: RadioMode = RadioMode.CW,
    display_mode: str = "CW",
    age_minutes: int = 3,
    operator_name: str | None = None,
    grid: str | None = None,
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=DxSpotIdentity(callsign=callsign, frequency=frequency),
        callsign=callsign,
        operator_name=operator_name,
        grid=grid,
        frequency=frequency,
        mode=mode,
        display_mode=display_mode,
        spotted_at=NOW - timedelta(minutes=age_minutes),
        source_metadata=(
            SpotSourceMetadataItem(key="spotter", value="W1AW"),
        ),
    )


def provider_health(
    provider: SpotProvider,
    count: int,
    *,
    status: ForgeRemoteProviderStatus = ForgeRemoteProviderStatus.HEALTHY,
    error: str | None = None,
) -> ForgeRemoteProviderHealth:
    if status is ForgeRemoteProviderStatus.HEALTHY:
        return ForgeRemoteProviderHealth(
            provider=provider,
            status=status,
            active_spot_count=count,
            last_attempt_at=GENERATED,
            last_success_at=GENERATED,
        )
    return ForgeRemoteProviderHealth(
        provider=provider,
        status=status,
        active_spot_count=count,
        last_attempt_at=GENERATED,
        last_success_at=GENERATED,
        last_error=error or "provider degraded",
    )


def published_state(
    spots: tuple[SpotRecord, ...],
    *,
    kind: PiForgeSpotStateKind = PiForgeSpotStateKind.LIVE,
    pota_health: ForgeRemoteProviderHealth | None = None,
    dx_health: ForgeRemoteProviderHealth | None = None,
) -> PiForgeSpotState:
    snapshot = SpotSnapshot.from_spots(generated_at=GENERATED, spots=spots)
    pota_count = sum(spot.provider is SpotProvider.POTA for spot in snapshot.spots)
    dx_count = sum(spot.provider is SpotProvider.DX for spot in snapshot.spots)
    providers = (
        pota_health or provider_health(SpotProvider.POTA, pota_count),
        dx_health or provider_health(SpotProvider.DX, dx_count),
    )
    if kind is PiForgeSpotStateKind.CACHED:
        return PiForgeSpotState(
            kind=kind,
            snapshot_revision=7,
            snapshot=snapshot,
            providers=providers,
            last_success_at=GENERATED,
        )
    if kind is PiForgeSpotStateKind.RETAINED:
        return PiForgeSpotState(
            kind=kind,
            snapshot_revision=7,
            snapshot=snapshot,
            providers=providers,
            last_attempt_at=NOW,
            last_success_at=GENERATED,
            error_kind=PiForgeSpotErrorKind.CLIENT,
            last_error="Forge unavailable",
        )
    return PiForgeSpotState(
        kind=kind,
        snapshot_revision=7,
        snapshot=snapshot,
        providers=providers,
        last_attempt_at=NOW,
        last_success_at=GENERATED,
    )


def controller_for(state: PiForgeSpotState | None) -> tuple[FakeSharedSource, SharedSpotPanelController]:
    source = FakeSharedSource(state)
    return source, SharedSpotPanelController(source, clock=lambda: NOW)


def test_disabled_source_is_truthful_and_empty() -> None:
    _, controller = controller_for(None)

    state = controller.state

    assert state.source_enabled is False
    assert state.has_usable_snapshot is False
    assert state.status_label == "FORGE DISABLED"
    assert state.rows == ()
    assert state.provider is SpotProvider.POTA


def test_enabled_empty_source_is_distinct_from_disabled() -> None:
    _, controller = controller_for(PiForgeSpotState(kind=PiForgeSpotStateKind.EMPTY))

    state = controller.state

    assert state.source_enabled is True
    assert state.has_usable_snapshot is False
    assert state.status_label == "NO SHARED SPOTS"
    assert state.rows == ()


def test_default_pota_view_preserves_mobile_band_mode_and_age_policy() -> None:
    recent_ssb = pota_spot("US-1001", 14_250_000)
    cw = pota_spot(
        "US-1002",
        14_030_000,
        mode=RadioMode.CW,
        display_mode="CW",
    )
    forty = pota_spot("US-1003", 7_200_000)
    stale = pota_spot("US-1004", 14_260_000, age_minutes=16)
    dx = dx_spot("K1DX", 14_020_000)
    source_state = published_state((recent_ssb, cw, forty, stale, dx))
    original_snapshot = source_state.snapshot
    _, controller = controller_for(source_state)

    state = controller.state

    assert [row.park_reference for row in state.rows] == ["US-1001"]
    assert state.filter_label == "POTA    BAND: 20    MODE: SSB"
    assert source_state.snapshot == original_snapshot
    assert source_state.snapshot is not None
    assert len(source_state.snapshot.spots) == 5


def test_pota_activation_defaults_to_current_supported_radio_band() -> None:
    twenty = pota_spot("US-2001", 14_250_000)
    forty = pota_spot("US-2002", 7_200_000)
    _, controller = controller_for(published_state((twenty, forty)))

    state = controller.activate(
        SpotProvider.POTA,
        current_frequency=Frequency(hz=7_150_000),
    )

    assert state.pota_band is RadioBand.BAND_40M
    assert [row.park_reference for row in state.rows] == ["US-2002"]


def test_pota_filter_controls_preserve_existing_mobile_sequence() -> None:
    seventeen = pota_spot("US-3001", 18_120_000)
    cw = pota_spot(
        "US-3002",
        18_090_000,
        mode=RadioMode.CW,
        display_mode="CW",
    )
    _, controller = controller_for(published_state((seventeen, cw)))

    band_state = controller.next_pota_band()
    mode_state = controller.next_pota_mode()

    assert band_state.pota_band is RadioBand.BAND_17M
    assert mode_state.pota_mode_filter is SharedSpotModeFilter.CW
    assert [row.park_reference for row in mode_state.rows] == ["US-3002"]


def test_dx_uses_same_controller_with_independent_dx_filters() -> None:
    pota = pota_spot("US-4001", 14_250_000)
    dx_twenty = dx_spot(
        "K1DX",
        14_020_000,
        operator_name="DX One",
        grid="FN31pr",
    )
    dx_forty = dx_spot("W9DX", 7_025_000)
    _, controller = controller_for(
        published_state((pota, dx_twenty, dx_forty))
    )

    controller.next_pota_mode()
    state = controller.activate(
        SpotProvider.DX,
        current_frequency=Frequency(hz=14_200_000),
    )

    assert state.provider is SpotProvider.DX
    assert state.pota_mode_filter is SharedSpotModeFilter.CW
    assert state.dx_band is RadioBand.BAND_20M
    assert state.dx_mode_filter is SharedSpotModeFilter.ALL
    assert state.filter_label == "DX    BAND: 20    MODE: ALL"
    assert [row.callsign for row in state.rows] == ["K1DX"]
    assert state.rows[0].operator_name_text == "DX One"
    assert state.rows[0].grid_text == "FN31pr"

    forty = controller.previous_dx_band()

    assert forty.dx_band is RadioBand.BAND_40M
    assert [row.callsign for row in forty.rows] == ["W9DX"]
    assert forty.rows[0].operator_name is None
    assert forty.rows[0].grid is None
    assert forty.rows[0].operator_name_text == "<UNKNOWN>"
    assert forty.rows[0].grid_text == "<UNKNOWN>"

def test_selection_survives_snapshot_replacement_by_stable_identity() -> None:
    selected = pota_spot("US-5001", 14_250_000)
    source, controller = controller_for(published_state((selected,)))
    controller.select_next()
    selected_identity = controller.selected_identity

    earlier = pota_spot("US-5002", 14_200_000)
    source.latest_forge_spot_state = published_state((earlier, selected))
    state = controller.state

    assert state.selected_identity == selected_identity
    assert len(state.rows) == 2
    assert state.rows[1].selected is True
    assert state.rows[1].park_reference == "US-5001"


def test_selected_disappearance_clears_without_neighbor_fallback() -> None:
    first = pota_spot("US-6001", 14_200_000)
    selected = pota_spot("US-6002", 14_250_000)
    source, controller = controller_for(published_state((first, selected)))
    controller.select_next()
    controller.select_next()
    assert controller.selected_spot == selected

    source.latest_forge_spot_state = published_state((first,))
    state = controller.state

    assert state.selected_identity is None
    assert all(row.selected is False for row in state.rows)


def test_provider_change_invalidates_staging_and_selection() -> None:
    pota = pota_spot("US-7001", 14_250_000)
    dx = dx_spot("K7DX", 14_020_000)
    _, controller = controller_for(published_state((pota, dx)))
    controller.select_next()
    staged = controller.stage_selected()
    assert staged.staged_identity == pota.identity

    dx_state = controller.activate(SpotProvider.DX)

    assert dx_state.staged_identity is None
    assert dx_state.selected_identity is None
    assert [row.callsign for row in dx_state.rows] == ["K7DX"]


def test_action_critical_change_under_same_identity_invalidates_staging() -> None:
    original = pota_spot("US-8001", 14_250_000, callsign="K1AAA")
    source, controller = controller_for(published_state((original,)))
    controller.select_next()
    controller.stage_selected()

    changed = pota_spot("US-8001", 14_250_000, callsign="K1BBB")
    source.latest_forge_spot_state = published_state((changed,))
    state = controller.state

    assert state.selected_identity == original.identity
    assert state.staged_identity is None


def test_cached_and_retained_source_diagnostics_preserve_real_timestamps() -> None:
    spot = pota_spot("US-9001", 14_250_000)
    source, controller = controller_for(
        published_state((spot,), kind=PiForgeSpotStateKind.CACHED)
    )

    cached = controller.state
    assert cached.status_label == "CACHED"
    assert cached.generated_at == GENERATED
    assert cached.last_success_at == GENERATED
    assert cached.last_attempt_at is None

    source.latest_forge_spot_state = published_state(
        (spot,),
        kind=PiForgeSpotStateKind.RETAINED,
    )
    retained = controller.state
    assert retained.status_label == "RETAINED"
    assert retained.generated_at == GENERATED
    assert retained.last_success_at == GENERATED
    assert retained.last_attempt_at == NOW
    assert retained.source_error == "Forge unavailable"


def test_selected_provider_health_is_exposed_without_hiding_degradation() -> None:
    pota = pota_spot("US-9101", 14_250_000)
    dx = dx_spot("K9DX", 14_020_000)
    degraded = provider_health(
        SpotProvider.DX,
        1,
        status=ForgeRemoteProviderStatus.DEGRADED,
        error="cluster timeout",
    )
    source_state = published_state((pota, dx), dx_health=degraded)
    _, controller = controller_for(source_state)

    state = controller.activate(SpotProvider.DX)

    assert state.provider_health is not None
    assert state.provider_health.provider is SpotProvider.DX
    assert state.provider_health.status is ForgeRemoteProviderStatus.DEGRADED
    assert state.provider_health.last_error == "cluster timeout"


def test_row_age_comes_from_source_timestamp_not_panel_refresh_time() -> None:
    spot = dx_spot("K0DX", 14_020_000, age_minutes=9)
    _, controller = controller_for(published_state((spot,)))

    state = controller.activate(SpotProvider.DX)

    assert state.rows[0].age_seconds == 9 * 60
    assert state.rows[0].age_minutes == 9


def test_naive_panel_clock_is_rejected() -> None:
    naive = NOW.replace(tzinfo=None)
    source = FakeSharedSource(None)

    with pytest.raises(ValueError, match="aware datetime"):
        SharedSpotPanelController(source, clock=lambda: naive)


def test_dx_activation_defaults_to_current_supported_radio_band() -> None:
    twenty = dx_spot("K1DX", 14_020_000)
    forty = dx_spot("W9DX", 7_025_000)
    _, controller = controller_for(published_state((twenty, forty)))

    state = controller.activate(
        SpotProvider.DX,
        current_frequency=Frequency(hz=7_150_000),
    )

    assert state.dx_band is RadioBand.BAND_40M
    assert state.dx_mode_filter is SharedSpotModeFilter.ALL
    assert [row.callsign for row in state.rows] == ["W9DX"]
    assert state.filter_label == "DX    BAND: 40    MODE: ALL"


def test_dx_band_and_mode_filters_use_shared_filtering() -> None:
    forty_ssb = dx_spot(
        "W4SSB",
        7_200_000,
        mode=RadioMode.LSB,
        display_mode="SSB",
    )
    twenty_cw = dx_spot("K1CW", 14_020_000)
    twenty_ssb = dx_spot(
        "K2SSB",
        14_250_000,
        mode=RadioMode.USB,
        display_mode="SSB",
    )
    _, controller = controller_for(
        published_state((forty_ssb, twenty_cw, twenty_ssb))
    )

    all_modes = controller.activate(
        SpotProvider.DX,
        current_frequency=Frequency(hz=14_200_000),
    )
    assert {row.callsign for row in all_modes.rows} == {"K1CW", "K2SSB"}

    ssb = controller.next_dx_mode()
    assert ssb.dx_mode_filter is SharedSpotModeFilter.SSB
    assert [row.callsign for row in ssb.rows] == ["K2SSB"]

    forty = controller.previous_dx_band()
    assert forty.dx_band is RadioBand.BAND_40M
    assert [row.callsign for row in forty.rows] == ["W4SSB"]


def test_pota_and_dx_mode_filter_state_are_independent() -> None:
    pota_cw = pota_spot(
        "US-9201",
        14_030_000,
        mode=RadioMode.CW,
        display_mode="CW",
    )
    dx_ssb = dx_spot(
        "K3SSB",
        14_250_000,
        mode=RadioMode.USB,
        display_mode="SSB",
    )
    _, controller = controller_for(published_state((pota_cw, dx_ssb)))

    pota_state = controller.next_pota_mode()
    assert pota_state.pota_mode_filter is SharedSpotModeFilter.CW

    dx_state = controller.activate(
        SpotProvider.DX,
        current_frequency=Frequency(hz=14_200_000),
    )
    assert dx_state.dx_mode_filter is SharedSpotModeFilter.ALL

    dx_state = controller.next_dx_mode()
    assert dx_state.dx_mode_filter is SharedSpotModeFilter.SSB

    pota_state = controller.activate(
        SpotProvider.POTA,
        current_frequency=Frequency(hz=14_200_000),
    )
    assert pota_state.pota_mode_filter is SharedSpotModeFilter.CW


def test_dx_filter_change_cancels_staging_even_when_selection_remains_visible() -> None:
    spot = dx_spot(
        "K4SSB",
        14_250_000,
        mode=RadioMode.USB,
        display_mode="SSB",
    )
    _, controller = controller_for(published_state((spot,)))
    controller.activate(
        SpotProvider.DX,
        current_frequency=Frequency(hz=14_200_000),
    )
    controller.select_next()

    staged = controller.stage_selected()
    assert staged.staged_identity == spot.identity

    filtered = controller.next_dx_mode()

    assert filtered.dx_mode_filter is SharedSpotModeFilter.SSB
    assert filtered.selected_identity == spot.identity
    assert filtered.staged_identity is None
