"""Tests for the Pi-side Forge shared-spot service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from threading import Event, Thread

import pytest

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_client import (
    ForgeClientConnectionError,
    ForgeRemoteProviderHealth,
    ForgeRemoteProviderStatus,
    ForgeSpotClientResult,
)
from rolling_thunder.pi_forge_spot_service import (
    PiForgeSpotErrorKind,
    PiForgeSpotService,
    PiForgeSpotStateKind,
)
from rolling_thunder.spot_domain import (
    DxSpotIdentity,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
)
from rolling_thunder.storage import StorageError


class FakeClient:
    """Deterministic synchronous client with optional blocking hooks."""

    def __init__(
        self,
        result: ForgeSpotClientResult | None = None,
        *,
        error: Exception | None = None,
        entered: Event | None = None,
        release: Event | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.entered = entered
        self.release = release
        self.calls = 0

    def fetch_spots(self) -> ForgeSpotClientResult:
        self.calls += 1
        if self.entered is not None:
            self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=2.0)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


class FakeCache:
    """Deterministic cache that records complete replacement attempts."""

    def __init__(
        self,
        loaded: ForgeSpotClientResult | None = None,
        *,
        load_error: StorageError | None = None,
        replace_error: StorageError | None = None,
        on_replace: Callable[[ForgeSpotClientResult], None] | None = None,
    ) -> None:
        self.loaded = loaded
        self.load_error = load_error
        self.replace_error = replace_error
        self.on_replace = on_replace
        self.replacements: list[ForgeSpotClientResult] = []

    def load(self) -> ForgeSpotClientResult | None:
        if self.load_error is not None:
            raise self.load_error
        return self.loaded

    def replace(self, result: ForgeSpotClientResult) -> None:
        self.replacements.append(result)
        if self.on_replace is not None:
            self.on_replace(result)
        if self.replace_error is not None:
            raise self.replace_error
        self.loaded = result


def result(
    revision: int,
    *,
    generated_at: datetime,
    received_at: datetime,
    callsign: str = "K1ABC",
) -> ForgeSpotClientResult:
    """Build one valid complete DX-only Forge result."""
    frequency = Frequency(hz=14_074_000)
    snapshot = SpotSnapshot.from_spots(
        generated_at=generated_at,
        spots=(
            SpotRecord(
                identity=DxSpotIdentity(callsign=callsign, frequency=frequency),
                callsign=callsign,
                frequency=frequency,
                mode=RadioMode.DATA,
                display_mode="FT8",
                spotted_at=generated_at,
            ),
        ),
    )
    return ForgeSpotClientResult(
        snapshot_revision=revision,
        snapshot=snapshot,
        providers=(
            ForgeRemoteProviderHealth(
                provider=SpotProvider.DX,
                status=ForgeRemoteProviderStatus.HEALTHY,
                active_spot_count=1,
                last_attempt_at=generated_at,
                last_success_at=generated_at,
            ),
        ),
        received_at=received_at,
    )


def test_initial_state_is_empty_without_cached_snapshot() -> None:
    service = PiForgeSpotService(FakeClient(), FakeCache())

    state = service.get_state()

    assert state.kind is PiForgeSpotStateKind.EMPTY
    assert state.snapshot is None
    assert state.snapshot_revision is None
    assert state.active_spot_count == 0
    assert state.last_attempt_at is None
    assert state.last_success_at is None
    assert state.error_kind is None


def test_cached_startup_preserves_original_generated_and_received_age() -> None:
    generated_at = datetime(2026, 8, 7, 10, 0, tzinfo=UTC)
    received_at = datetime(2026, 8, 7, 10, 0, 5, tzinfo=UTC)
    cached = result(7, generated_at=generated_at, received_at=received_at)

    service = PiForgeSpotService(
        FakeClient(),
        FakeCache(cached),
        now=lambda: datetime(2026, 8, 7, 20, 0, tzinfo=UTC),
    )

    state = service.get_state()

    assert state.kind is PiForgeSpotStateKind.CACHED
    assert state.snapshot_revision == 7
    assert state.snapshot == cached.snapshot
    assert state.generated_at == generated_at
    assert state.last_success_at == received_at
    assert state.last_attempt_at is None
    assert state.has_usable_snapshot is True


def test_cache_read_failure_is_distinguishable_without_fabricating_attempt() -> None:
    service = PiForgeSpotService(
        FakeClient(),
        FakeCache(load_error=StorageError("database unreadable")),
    )

    state = service.get_state()

    assert state.kind is PiForgeSpotStateKind.EMPTY
    assert state.error_kind is PiForgeSpotErrorKind.CACHE_READ
    assert state.last_error == "database unreadable"
    assert state.last_attempt_at is None


def test_success_persists_complete_result_before_publishing() -> None:
    old = result(
        1,
        generated_at=datetime(2026, 8, 7, 12, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 12, 0, 5, tzinfo=UTC),
    )
    new = result(
        2,
        generated_at=datetime(2026, 8, 7, 12, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 12, 1, 5, tzinfo=UTC),
        callsign="W8NEW",
    )
    cache = FakeCache(old)
    service = PiForgeSpotService(
        FakeClient(new),
        cache,
        now=lambda: datetime(2026, 8, 7, 12, 1, 6, tzinfo=UTC),
    )

    def assert_old_state_during_persistence(candidate: ForgeSpotClientResult) -> None:
        assert candidate == new
        state = service.get_state()
        assert state.snapshot_revision == 1
        assert state.snapshot == old.snapshot
        assert state.kind is PiForgeSpotStateKind.CACHED

    cache.on_replace = assert_old_state_during_persistence

    state = service.refresh()

    assert cache.replacements == [new]
    assert state.kind is PiForgeSpotStateKind.LIVE
    assert state.snapshot_revision == 2
    assert state.snapshot == new.snapshot
    assert state.last_success_at == new.received_at
    assert state.last_attempt_at == datetime(2026, 8, 7, 12, 1, 6, tzinfo=UTC)
    assert state.error_kind is None


def test_client_failure_without_snapshot_publishes_truthful_empty_failure() -> None:
    attempted_at = datetime(2026, 8, 7, 13, 0, tzinfo=UTC)
    service = PiForgeSpotService(
        FakeClient(error=ForgeClientConnectionError("Forge offline")),
        FakeCache(),
        now=lambda: attempted_at,
    )

    state = service.refresh()

    assert state.kind is PiForgeSpotStateKind.EMPTY
    assert state.snapshot is None
    assert state.last_attempt_at == attempted_at
    assert state.error_kind is PiForgeSpotErrorKind.CLIENT
    assert state.last_error == "Forge offline"


def test_client_failure_retains_cached_snapshot_and_original_success_time() -> None:
    cached = result(
        5,
        generated_at=datetime(2026, 8, 7, 14, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 14, 0, 5, tzinfo=UTC),
    )
    attempted_at = datetime(2026, 8, 7, 15, 0, tzinfo=UTC)
    service = PiForgeSpotService(
        FakeClient(error=ForgeClientConnectionError("WireGuard unavailable")),
        FakeCache(cached),
        now=lambda: attempted_at,
    )

    state = service.refresh()

    assert state.kind is PiForgeSpotStateKind.RETAINED
    assert state.snapshot_revision == 5
    assert state.snapshot == cached.snapshot
    assert state.generated_at == cached.snapshot.generated_at
    assert state.last_success_at == cached.received_at
    assert state.last_attempt_at == attempted_at
    assert state.error_kind is PiForgeSpotErrorKind.CLIENT
    assert state.last_error == "WireGuard unavailable"


def test_cache_write_failure_never_publishes_newer_in_memory_snapshot() -> None:
    old = result(
        8,
        generated_at=datetime(2026, 8, 7, 16, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 16, 0, 5, tzinfo=UTC),
    )
    new = result(
        9,
        generated_at=datetime(2026, 8, 7, 16, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 16, 1, 5, tzinfo=UTC),
        callsign="K9NEW",
    )
    cache = FakeCache(old, replace_error=StorageError("disk full"))
    service = PiForgeSpotService(
        FakeClient(new),
        cache,
        now=lambda: datetime(2026, 8, 7, 16, 1, 6, tzinfo=UTC),
    )

    state = service.refresh()

    assert cache.replacements == [new]
    assert state.kind is PiForgeSpotStateKind.RETAINED
    assert state.snapshot_revision == 8
    assert state.snapshot == old.snapshot
    assert state.last_success_at == old.received_at
    assert state.error_kind is PiForgeSpotErrorKind.CACHE_WRITE
    assert state.last_error == "disk full"


def test_success_after_failure_clears_error_and_publishes_live_state() -> None:
    live = result(
        3,
        generated_at=datetime(2026, 8, 7, 17, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 17, 0, 5, tzinfo=UTC),
    )
    client = FakeClient(error=ForgeClientConnectionError("temporary outage"))
    cache = FakeCache()
    times = iter(
        (
            datetime(2026, 8, 7, 16, 59, tzinfo=UTC),
            datetime(2026, 8, 7, 17, 0, 6, tzinfo=UTC),
        )
    )
    service = PiForgeSpotService(client, cache, now=lambda: next(times))

    failed = service.refresh()
    assert failed.error_kind is PiForgeSpotErrorKind.CLIENT

    client.error = None
    client.result = live
    recovered = service.refresh()

    assert recovered.kind is PiForgeSpotStateKind.LIVE
    assert recovered.snapshot_revision == 3
    assert recovered.error_kind is None
    assert recovered.last_error is None


def test_overlapping_refresh_returns_current_state_without_second_fetch() -> None:
    current = result(
        4,
        generated_at=datetime(2026, 8, 7, 18, 0, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 18, 0, 5, tzinfo=UTC),
    )
    next_result = result(
        5,
        generated_at=datetime(2026, 8, 7, 18, 1, tzinfo=UTC),
        received_at=datetime(2026, 8, 7, 18, 1, 5, tzinfo=UTC),
        callsign="N5NEXT",
    )
    entered = Event()
    release = Event()
    client = FakeClient(next_result, entered=entered, release=release)
    service = PiForgeSpotService(
        client,
        FakeCache(current),
        now=lambda: datetime(2026, 8, 7, 18, 1, 6, tzinfo=UTC),
    )

    completed: list[object] = []
    thread = Thread(target=lambda: completed.append(service.refresh()))
    thread.start()
    assert entered.wait(timeout=2.0)
    assert service.is_refreshing is True

    overlapping = service.refresh()

    assert overlapping.kind is PiForgeSpotStateKind.CACHED
    assert overlapping.snapshot_revision == 4
    assert client.calls == 1

    release.set()
    thread.join(timeout=2.0)
    assert not thread.is_alive()
    assert service.is_refreshing is False
    assert service.get_state().kind is PiForgeSpotStateKind.LIVE
    assert service.get_state().snapshot_revision == 5


def test_naive_service_clock_releases_refresh_guard() -> None:
    naive_time = datetime(2026, 8, 7, 19, 0, tzinfo=UTC).replace(tzinfo=None)
    service = PiForgeSpotService(
        FakeClient(),
        FakeCache(),
        now=lambda: naive_time,
    )

    with pytest.raises(ValueError, match="aware datetime"):
        service.refresh()

    assert service.is_refreshing is False
