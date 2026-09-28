"""Tests for provider-neutral shared spot viewport presentation."""

from datetime import UTC, datetime, timedelta

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import ForgeRemoteProviderHealth, ForgeRemoteProviderStatus
from rolling_thunder.pi_forge_spot_service import PiForgeSpotStateKind
from rolling_thunder.radio import RadioBand
from rolling_thunder.shared_spot_panel import (
    SharedSpotModeFilter,
    SharedSpotPanelRow,
    SharedSpotPanelState,
)
from rolling_thunder.shared_spot_ui import build_shared_spot_viewport
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    SpotProvider,
    SpotSourceMetadataItem,
)

NOW = datetime(2026, 8, 8, 1, 0, tzinfo=UTC)


def row(
    *,
    provider: SpotProvider,
    callsign: str,
    frequency_hz: int,
    selected: bool = False,
    operator_name: str | None = None,
    grid: str | None = None,
    park_reference: str | None = None,
    park_name: str | None = None,
    location_code: str | None = None,
    worked: bool = False,
) -> SharedSpotPanelRow:
    frequency = Frequency(hz=frequency_hz)
    identity = (
        PotaSpotIdentity(park_reference=park_reference or "US-0001", frequency=frequency)
        if provider is SpotProvider.POTA
        else DxSpotIdentity(callsign=callsign, frequency=frequency)
    )
    return SharedSpotPanelRow(
        identity=identity,
        provider=provider,
        callsign=callsign,
        operator_name=operator_name,
        grid=grid,
        frequency=frequency,
        mode=RadioMode.USB if provider is SpotProvider.POTA else RadioMode.CW,
        display_mode="SSB" if provider is SpotProvider.POTA else "CW",
        spotted_at=NOW - timedelta(minutes=4),
        age_seconds=240,
        source_metadata=(SpotSourceMetadataItem(key="spotter", value="W1AW"),),
        park_reference=park_reference,
        park_name=park_name,
        location_code=location_code,
        selected=selected,
        worked=worked,
    )


def panel_state(
    rows: tuple[SharedSpotPanelRow, ...],
    *,
    provider: SpotProvider,
    kind: PiForgeSpotStateKind | None = PiForgeSpotStateKind.LIVE,
    provider_status: ForgeRemoteProviderStatus = ForgeRemoteProviderStatus.HEALTHY,
    provider_error: str | None = None,
    source_error: str | None = None,
) -> SharedSpotPanelState:
    health = None
    if kind is not None:
        health = ForgeRemoteProviderHealth(
            provider=provider,
            status=provider_status,
            active_spot_count=len(rows),
            last_attempt_at=NOW,
            last_success_at=(NOW if provider_status is not ForgeRemoteProviderStatus.UNAVAILABLE else None),
            last_error=provider_error,
        )
    return SharedSpotPanelState(
        provider=provider,
        source_kind=kind,
        snapshot_revision=8 if kind is not None else None,
        generated_at=NOW if kind is not None else None,
        last_success_at=NOW if kind is not None else None,
        last_attempt_at=NOW if kind is not None else None,
        source_error=source_error,
        provider_health=health,
        rows=rows,
        selected_identity=next((item.identity for item in rows if item.selected), None),
        pota_band=RadioBand.BAND_20M,
        pota_mode_filter=SharedSpotModeFilter.SSB,
        pota_maximum_age=timedelta(minutes=15),
        dx_band=RadioBand.BAND_20M,
        dx_mode_filter=SharedSpotModeFilter.ALL,
    )


def test_pota_card_uses_shared_name_park_frequency_and_age() -> None:
    state = panel_state(
        (
            row(
                provider=SpotProvider.POTA,
                callsign="K1POTA",
                frequency_hz=14_250_000,
                operator_name="Park Operator",
                park_reference="US-1234",
                park_name="Example Park",
                location_code="US-OH",
            ),
        ),
        provider=SpotProvider.POTA,
    )

    viewport = build_shared_spot_viewport(state)

    assert viewport.title == "POTA    BAND: 20    MODE: SSB"
    assert viewport.status_line == "1 SPOTS"
    assert viewport.detail_line == "GENERATED 01:00:00Z"
    assert viewport.cards[0].line1 == "K1POTA - Park Operator"
    assert viewport.cards[0].line2 == "14.250 MHz  SSB  4m"
    assert viewport.cards[0].line3 == "US-1234 - Example Park"
    assert viewport.cards[0].line4 == "US-OH"


def test_dx_card_uses_same_four_line_card_with_grid_and_source_metadata() -> None:
    state = panel_state(
        (
            row(
                provider=SpotProvider.DX,
                callsign="K1DX",
                frequency_hz=14_020_000,
                operator_name="DX Operator",
                grid="FN31pr",
            ),
        ),
        provider=SpotProvider.DX,
    )

    viewport = build_shared_spot_viewport(state)
    card = viewport.cards[0]

    assert viewport.status_line == "1 SPOTS"
    assert viewport.detail_line == "GENERATED 01:00:00Z"
    assert card.line1 == "K1DX - DX Operator"
    assert card.line2 == "14.020 MHz  CW  4m"
    assert card.line3 == "GRID FN31pr"
    assert card.line4 == "SPOTTER W1AW"


def test_selected_row_is_kept_inside_three_card_window() -> None:
    rows = tuple(
        row(
            provider=SpotProvider.DX,
            callsign=f"K{index}DX",
            frequency_hz=14_020_000 + index * 1_000,
            selected=index == 4,
        )
        for index in range(5)
    )

    viewport = build_shared_spot_viewport(panel_state(rows, provider=SpotProvider.DX))

    assert len(viewport.cards) == 3
    assert viewport.hidden_above_count == 2
    assert viewport.hidden_below_count == 0
    assert viewport.cards[-1].selected is True


def test_disabled_source_has_truthful_empty_detail() -> None:
    state = panel_state((), provider=SpotProvider.POTA, kind=None)

    viewport = build_shared_spot_viewport(state)

    assert viewport.status_line == "0 SPOTS"
    assert viewport.detail_line == "Shared Forge spots are disabled in this configuration."
    assert viewport.cards == ()


def test_provider_degradation_and_pi_error_are_both_visible_without_footer_clutter() -> None:
    state = panel_state(
        (),
        provider=SpotProvider.DX,
        provider_status=ForgeRemoteProviderStatus.DEGRADED,
        provider_error="cluster timeout",
        source_error="Forge unavailable",
    )

    viewport = build_shared_spot_viewport(state)

    assert viewport.status_line == "0 SPOTS"
    assert viewport.detail_line == "GENERATED 01:00:00Z"
    assert viewport.error_line == "Forge unavailable — cluster timeout"


def test_row_limit_must_be_positive() -> None:
    state = panel_state((), provider=SpotProvider.DX)

    try:
        build_shared_spot_viewport(state, max_rows=0)
    except ValueError as error:
        assert "positive" in str(error)
    else:
        raise AssertionError("expected positive row-limit validation")


def test_worked_pota_card_adds_label_and_presentation_flag() -> None:
    state = panel_state(
        (
            row(
                provider=SpotProvider.POTA,
                callsign="K1POTA",
                frequency_hz=14_250_000,
                park_reference="US-1234",
                park_name="Example Park",
                location_code="US-OH",
                worked=True,
            ),
        ),
        provider=SpotProvider.POTA,
    )

    card = build_shared_spot_viewport(state).cards[0]

    assert card.worked is True
    assert card.line1 == "K1POTA — WORKED"
