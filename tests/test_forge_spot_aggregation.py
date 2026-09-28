"""Tests for persistence-before-activation Forge spot aggregation."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_snapshot_repository import (
    ForgeSnapshotStorageError,
    ForgeStoredSnapshot,
)
from rolling_thunder.forge_spot_aggregation import (
    ForgeProviderHealthStatus,
    ForgeSpotAggregationService,
)
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    MockForgeSpotProvider,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
)

BASE_TIME = datetime(2026, 8, 5, 20, 0, tzinfo=UTC)


class TickingClock:
    def __init__(self) -> None:
        self._value = BASE_TIME

    def __call__(self) -> datetime:
        value = self._value
        self._value += timedelta(seconds=1)
        return value


class MemoryRepository:
    def __init__(
        self,
        stored: ForgeStoredSnapshot | None = None,
        *,
        load_error: ForgeSnapshotStorageError | None = None,
    ) -> None:
        self.stored = stored
        self.load_error = load_error
        self.replace_error: ForgeSnapshotStorageError | None = None
        self.replace_calls: list[
            tuple[SpotSnapshot, tuple[ForgeProviderSlice, ...]]
        ] = []
        self.on_replace: Callable[[], None] | None = None

    def load(self) -> ForgeStoredSnapshot | None:
        if self.load_error is not None:
            raise self.load_error
        return self.stored

    def replace(
        self,
        snapshot: SpotSnapshot,
        provider_slices: tuple[ForgeProviderSlice, ...],
    ) -> ForgeStoredSnapshot:
        self.replace_calls.append((snapshot, provider_slices))
        if self.on_replace is not None:
            self.on_replace()
        if self.replace_error is not None:
            raise self.replace_error
        revision = 1 if self.stored is None else self.stored.revision + 1
        self.stored = ForgeStoredSnapshot(
            revision=revision,
            snapshot=snapshot,
            provider_slices=provider_slices,
        )
        return self.stored


class ReentrantProvider:
    def __init__(self, provider_slice: ForgeProviderSlice) -> None:
        self._slice = provider_slice
        self.callback: Callable[[], None] | None = None
        self.fetch_count = 0

    @property
    def provider(self) -> SpotProvider:
        return self._slice.provider

    def fetch_slice(self) -> ForgeProviderSlice:
        self.fetch_count += 1
        if self.callback is not None:
            self.callback()
        return self._slice


class WrongFamilyProvider:
    def __init__(self, returned_slice: ForgeProviderSlice) -> None:
        self._returned_slice = returned_slice

    @property
    def provider(self) -> SpotProvider:
        return SpotProvider.POTA

    def fetch_slice(self) -> ForgeProviderSlice:
        return self._returned_slice


def pota_spot(
    callsign: str = "KI5VNB",
    reference: str = "US-1234",
    frequency_hz: int = 14_250_000,
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference=reference,
            frequency=frequency,
        ),
        callsign=callsign,
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="SSB",
        spotted_at=BASE_TIME,
        pota=PotaSpotMetadata(park_reference=reference),
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
    fetched_at: datetime = BASE_TIME,
) -> ForgeProviderSlice:
    return ForgeProviderSlice.from_spots(
        provider=provider,
        fetched_at=fetched_at,
        spots=spots,
    )


def health_for(state_provider: SpotProvider, service: ForgeSpotAggregationService):
    return next(
        item
        for item in service.get_state().providers
        if item.provider is state_provider
    )


def test_success_persists_before_publishing_new_snapshot() -> None:
    repository = MemoryRepository()
    slice_ = provider_slice(SpotProvider.POTA, (pota_spot(),))
    provider = MockForgeSpotProvider(slice_)
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )

    def assert_not_activated_early() -> None:
        state = service.get_state()
        assert state.revision == 0
        assert state.snapshot.spots == ()

    repository.on_replace = assert_not_activated_early

    state = service.refresh_provider(SpotProvider.POTA)

    assert state.revision == 1
    assert state.snapshot.spots == slice_.spots
    assert repository.stored is not None
    assert state.snapshot == repository.stored.snapshot
    health = health_for(SpotProvider.POTA, service)
    assert health.status is ForgeProviderHealthStatus.HEALTHY
    assert health.active_spot_count == 1
    assert health.last_error is None


def test_successful_empty_provider_slice_is_activated() -> None:
    repository = MemoryRepository()
    provider = MockForgeSpotProvider(provider_slice(SpotProvider.POTA, ()))
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )

    state = service.refresh_provider(SpotProvider.POTA)

    assert state.revision == 1
    assert state.snapshot.spots == ()
    health = health_for(SpotProvider.POTA, service)
    assert health.status is ForgeProviderHealthStatus.HEALTHY
    assert health.active_spot_count == 0


def test_provider_failure_retains_previous_slice_and_revision() -> None:
    repository = MemoryRepository()
    slice_ = provider_slice(SpotProvider.POTA, (pota_spot(),))
    provider = MockForgeSpotProvider(slice_)
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )
    successful = service.refresh_provider(SpotProvider.POTA)
    provider.set_error(ForgeSpotProviderConnectionError("POTA unavailable"))

    failed = service.refresh_provider(SpotProvider.POTA)

    assert failed.revision == successful.revision
    assert failed.snapshot == successful.snapshot
    assert len(repository.replace_calls) == 1
    health = health_for(SpotProvider.POTA, service)
    assert health.status is ForgeProviderHealthStatus.DEGRADED
    assert health.last_error == "POTA unavailable"
    assert health.last_success_at == slice_.fetched_at


def test_persistence_failure_retains_previous_snapshot() -> None:
    repository = MemoryRepository()
    first_slice = provider_slice(SpotProvider.POTA, (pota_spot(),))
    provider = MockForgeSpotProvider(first_slice)
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )
    successful = service.refresh_provider(SpotProvider.POTA)
    provider.set_slice(
        provider_slice(
            SpotProvider.POTA,
            (pota_spot(callsign="W8NEW"),),
            fetched_at=BASE_TIME + timedelta(minutes=1),
        )
    )
    repository.replace_error = ForgeSnapshotStorageError("disk full")

    failed = service.refresh_provider(SpotProvider.POTA)

    assert failed.revision == successful.revision
    assert failed.snapshot == successful.snapshot
    assert failed.persistence_error == "disk full"
    health = health_for(SpotProvider.POTA, service)
    assert health.status is ForgeProviderHealthStatus.DEGRADED
    assert health.last_error == "disk full"


def test_multi_provider_refresh_composes_complete_snapshot() -> None:
    repository = MemoryRepository()
    pota = MockForgeSpotProvider(
        provider_slice(SpotProvider.POTA, (pota_spot(),))
    )
    dx = MockForgeSpotProvider(provider_slice(SpotProvider.DX, (dx_spot(),)))
    service = ForgeSpotAggregationService(
        (pota, dx),
        repository,
        now=TickingClock(),
    )

    service.refresh_provider(SpotProvider.POTA)
    state = service.refresh_provider(SpotProvider.DX)

    assert state.revision == 2
    assert state.snapshot.spots == (dx_spot(), pota_spot())
    assert tuple(item.provider for item in state.providers) == (
        SpotProvider.DX,
        SpotProvider.POTA,
    )
    assert all(
        item.status is ForgeProviderHealthStatus.HEALTHY
        for item in state.providers
    )


def test_wrong_provider_slice_is_rejected_without_activation() -> None:
    repository = MemoryRepository()
    provider = WrongFamilyProvider(provider_slice(SpotProvider.DX, (dx_spot(),)))
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )

    state = service.refresh_provider(SpotProvider.POTA)

    assert state.revision == 0
    assert state.snapshot.spots == ()
    assert repository.replace_calls == []
    health = health_for(SpotProvider.POTA, service)
    assert health.status is ForgeProviderHealthStatus.UNAVAILABLE
    assert "another provider" in (health.last_error or "")


def test_startup_load_publishes_retained_snapshot_as_degraded() -> None:
    slice_ = provider_slice(SpotProvider.POTA, (pota_spot(),))
    snapshot = SpotSnapshot.from_spots(generated_at=BASE_TIME, spots=slice_.spots)
    repository = MemoryRepository(
        ForgeStoredSnapshot(
            revision=4,
            snapshot=snapshot,
            provider_slices=(slice_,),
        )
    )
    service = ForgeSpotAggregationService(
        (MockForgeSpotProvider(slice_),),
        repository,
        now=TickingClock(),
    )

    state = service.get_state()

    assert state.revision == 4
    assert state.snapshot == snapshot
    health = health_for(SpotProvider.POTA, service)
    assert health.status is ForgeProviderHealthStatus.DEGRADED
    assert health.last_success_at == slice_.fetched_at
    assert "retained" in (health.last_error or "").lower()


def test_startup_storage_failure_is_visible_and_does_not_crash() -> None:
    slice_ = provider_slice(SpotProvider.POTA, (pota_spot(),))
    repository = MemoryRepository(
        load_error=ForgeSnapshotStorageError("malformed durable snapshot")
    )
    service = ForgeSpotAggregationService(
        (MockForgeSpotProvider(slice_),),
        repository,
        now=TickingClock(),
    )

    state = service.get_state()

    assert state.revision == 0
    assert state.snapshot.spots == ()
    assert state.startup_storage_error == "malformed durable snapshot"
    assert health_for(SpotProvider.POTA, service).status is ForgeProviderHealthStatus.STARTING


def test_refresh_all_continues_after_one_provider_failure() -> None:
    repository = MemoryRepository()
    dx = MockForgeSpotProvider(
        provider_slice(SpotProvider.DX, (dx_spot(),)),
        error=ForgeSpotProviderConnectionError("DX unavailable"),
    )
    pota = MockForgeSpotProvider(
        provider_slice(SpotProvider.POTA, (pota_spot(),))
    )
    service = ForgeSpotAggregationService(
        (dx, pota),
        repository,
        now=TickingClock(),
    )

    state = service.refresh_all()

    assert state.snapshot.spots == (pota_spot(),)
    assert health_for(SpotProvider.DX, service).status is ForgeProviderHealthStatus.UNAVAILABLE
    assert health_for(SpotProvider.POTA, service).status is ForgeProviderHealthStatus.HEALTHY


def test_future_refresh_recovers_after_provider_failure() -> None:
    repository = MemoryRepository()
    slice_ = provider_slice(SpotProvider.POTA, (pota_spot(),))
    provider = MockForgeSpotProvider(
        slice_,
        error=ForgeSpotProviderConnectionError("temporary outage"),
    )
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )
    failed = service.refresh_provider(SpotProvider.POTA)
    provider.set_slice(slice_)

    recovered = service.refresh_provider(SpotProvider.POTA)

    assert failed.revision == 0
    assert recovered.revision == 1
    assert recovered.snapshot.spots == slice_.spots
    assert health_for(SpotProvider.POTA, service).status is ForgeProviderHealthStatus.HEALTHY


def test_reentrant_refresh_does_not_overlap_provider_work() -> None:
    repository = MemoryRepository()
    provider = ReentrantProvider(
        provider_slice(SpotProvider.POTA, (pota_spot(),))
    )
    service = ForgeSpotAggregationService(
        (provider,),
        repository,
        now=TickingClock(),
    )
    nested_revisions: list[int] = []
    provider.callback = lambda: nested_revisions.append(
        service.refresh_provider(SpotProvider.POTA).revision
    )

    state = service.refresh_provider(SpotProvider.POTA)

    assert nested_revisions == [0]
    assert provider.fetch_count == 1
    assert state.revision == 1
    assert service.is_refreshing is False
