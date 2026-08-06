"""End-to-end tests for checkpoint-five Forge DX and QRZ behavior."""

from datetime import UTC, datetime, timedelta
from json import loads
from pathlib import Path

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_config import ForgeQrzEnrichmentConfig
from rolling_thunder.forge_qrz_enrichment import ForgeQrzEnricher
from rolling_thunder.forge_qrz_provider import ForgeQrzEnrichedSpotProvider
from rolling_thunder.forge_snapshot_repository import SqliteForgeSnapshotRepository
from rolling_thunder.forge_spot_aggregation import (
    ForgeProviderHealthStatus,
    ForgeSpotAggregationService,
)
from rolling_thunder.forge_spot_api import ForgeSpotApiApplication
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    MockForgeSpotProvider,
)
from rolling_thunder.qrz_xml import QrzCallsignProfile
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
)

BASE_TIME = datetime(2026, 8, 6, 2, 5, tzinfo=UTC)


class TickingClock:
    def __init__(self) -> None:
        self.value = BASE_TIME

    def __call__(self) -> datetime:
        value = self.value
        self.value += timedelta(seconds=1)
        return value


class FakeQrzLookup:
    def __init__(self) -> None:
        self.profiles = {
            "K1ABC": QrzCallsignProfile(
                callsign="K1ABC",
                name="DX Operator",
                image_url=None,
                grid="FN31pr",
            ),
            "KI5VNB": QrzCallsignProfile(
                callsign="KI5VNB",
                name="Geoff Kline",
                image_url=None,
                grid="EM79xm",
            ),
            "W8NEW": QrzCallsignProfile(
                callsign="W8NEW",
                name="New Activator",
                image_url=None,
                grid="EN80aa",
            ),
        }
        self.calls: list[str] = []

    def lookup_profile(self, callsign: str) -> QrzCallsignProfile | None:
        normalized = str(callsign)
        self.calls.append(normalized)
        return self.profiles.get(normalized)


def pota_spot(
    callsign: str = "KI5VNB",
    *,
    spotted_at: datetime = BASE_TIME,
) -> SpotRecord:
    frequency = Frequency(hz=14_250_000)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference="US-1234",
            frequency=frequency,
        ),
        callsign=callsign,
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="SSB",
        spotted_at=spotted_at,
        pota=PotaSpotMetadata(
            park_reference="US-1234",
            park_name="Example State Park",
            location_code="US-OH",
        ),
    )


def dx_spot() -> SpotRecord:
    frequency = Frequency(hz=14_025_000)
    return SpotRecord(
        identity=DxSpotIdentity(callsign="K1ABC", frequency=frequency),
        callsign="K1ABC",
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=BASE_TIME,
    )


def provider_slice(
    provider: SpotProvider,
    spots: tuple[SpotRecord, ...],
    *,
    fetched_at: datetime = BASE_TIME + timedelta(seconds=1),
) -> ForgeProviderSlice:
    return ForgeProviderSlice.from_spots(
        provider=provider,
        fetched_at=fetched_at,
        spots=spots,
    )


def qrz_enricher(lookup: FakeQrzLookup) -> ForgeQrzEnricher:
    return ForgeQrzEnricher(
        ForgeQrzEnrichmentConfig(
            enabled=True,
            minimum_request_interval_s=0,
        ),
        lookup,
    )


def initial_service(
    database_path: Path,
) -> tuple[
    ForgeSpotAggregationService,
    MockForgeSpotProvider,
    MockForgeSpotProvider,
    FakeQrzLookup,
]:
    lookup = FakeQrzLookup()
    enricher = qrz_enricher(lookup)
    pota = MockForgeSpotProvider(
        provider_slice(SpotProvider.POTA, (pota_spot(),))
    )
    dx = MockForgeSpotProvider(
        provider_slice(SpotProvider.DX, (dx_spot(),))
    )
    service = ForgeSpotAggregationService(
        (
            ForgeQrzEnrichedSpotProvider(pota, enricher),
            ForgeQrzEnrichedSpotProvider(dx, enricher),
        ),
        SqliteForgeSnapshotRepository(database_path),
        now=TickingClock(),
    )
    return service, pota, dx, lookup


def test_enriched_combined_snapshot_round_trips_and_serializes(tmp_path: Path) -> None:
    database_path = tmp_path / "forge.db"
    service, _, _, lookup = initial_service(database_path)

    active = service.refresh_all()

    assert active.revision == 2
    assert lookup.calls == ["K1ABC", "KI5VNB"]
    active_by_callsign = {str(spot.callsign): spot for spot in active.snapshot.spots}
    assert active_by_callsign["K1ABC"].operator_name == "DX Operator"
    assert active_by_callsign["K1ABC"].grid == "FN31pr"
    assert active_by_callsign["KI5VNB"].operator_name == "Geoff Kline"
    assert active_by_callsign["KI5VNB"].grid == "EM79xm"

    retained_service, _, _, _ = initial_service(database_path)
    retained = retained_service.get_state()

    assert retained.revision == 2
    assert retained.snapshot == active.snapshot
    assert all(
        health.status is ForgeProviderHealthStatus.DEGRADED
        for health in retained.providers
    )

    response = ForgeSpotApiApplication(retained_service).handle(
        "GET",
        "/api/v1/spots",
    )
    payload = loads(response.body)
    serialized = {spot["callsign"]: spot for spot in payload["spots"]}

    assert response.status_code == 200
    assert tuple(item["provider"] for item in payload["providers"]) == (
        "dx",
        "pota",
    )
    assert serialized["K1ABC"]["identity"]["provider"] == "dx"
    assert serialized["K1ABC"]["operator_name"] == "DX Operator"
    assert serialized["K1ABC"]["grid"] == "FN31pr"
    assert serialized["KI5VNB"]["identity"]["provider"] == "pota"
    assert serialized["KI5VNB"]["operator_name"] == "Geoff Kline"
    assert serialized["KI5VNB"]["grid"] == "EM79xm"


def test_dx_failure_retains_dx_while_pota_refreshes_after_restart(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "forge.db"
    initial, _, _, _ = initial_service(database_path)
    initial.refresh_all()

    retained, pota, dx, _ = initial_service(database_path)
    dx.set_error(ForgeSpotProviderConnectionError("DX cluster unavailable"))
    pota.set_slice(
        provider_slice(
            SpotProvider.POTA,
            (
                pota_spot(
                    "W8NEW",
                    spotted_at=BASE_TIME + timedelta(minutes=1),
                ),
            ),
            fetched_at=BASE_TIME + timedelta(minutes=1, seconds=1),
        )
    )

    refreshed = retained.refresh_all()
    refreshed_by_callsign = {
        str(spot.callsign): spot for spot in refreshed.snapshot.spots
    }
    health = {item.provider: item for item in refreshed.providers}

    assert refreshed.revision == 3
    assert set(refreshed_by_callsign) == {"K1ABC", "W8NEW"}
    assert refreshed_by_callsign["K1ABC"].operator_name == "DX Operator"
    assert refreshed_by_callsign["W8NEW"].operator_name == "New Activator"
    assert health[SpotProvider.DX].status is ForgeProviderHealthStatus.DEGRADED
    assert health[SpotProvider.DX].last_error == "DX cluster unavailable"
    assert health[SpotProvider.POTA].status is ForgeProviderHealthStatus.HEALTHY
