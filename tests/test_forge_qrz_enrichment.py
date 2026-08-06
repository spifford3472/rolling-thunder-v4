"""Tests for bounded best-effort Forge-side QRZ enrichment."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_config import ForgeQrzEnrichmentConfig
from rolling_thunder.forge_qrz_enrichment import ForgeQrzEnricher
from rolling_thunder.forge_spot_provider import ForgeProviderSlice
from rolling_thunder.qrz_xml import QrzCallsignProfile, QrzResponseError
from rolling_thunder.spot_domain import DxSpotIdentity, SpotProvider, SpotRecord
from rolling_thunder.value_types import Callsign

_FETCHED_AT = datetime(2026, 8, 6, 2, 5, tzinfo=UTC)


class FakeQrzLookup:
    """Deterministic QRZ profile lookup with recorded calls."""

    def __init__(
        self,
        responses: dict[str, QrzCallsignProfile | None | Exception],
    ) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def lookup_profile(self, callsign: Callsign | str) -> QrzCallsignProfile | None:
        key = str(callsign)
        self.calls.append(key)
        response = self.responses[key]
        if isinstance(response, Exception):
            raise response
        return response


class FakeClock:
    """Injected monotonic clock and sleeper without real waiting."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, duration: float) -> None:
        self.sleeps.append(duration)
        self.now += duration

    def advance(self, duration: float) -> None:
        self.now += duration


def qrz_config(**updates: object) -> ForgeQrzEnrichmentConfig:
    """Return enabled QRZ configuration with no default lookup delay."""
    values: dict[str, object] = {
        "enabled": True,
        "minimum_request_interval_s": 0,
        "max_lookups_per_refresh": 25,
        "positive_ttl_s": 100,
        "negative_ttl_s": 10,
        "max_cache_entries": 20,
    }
    values.update(updates)
    return ForgeQrzEnrichmentConfig.model_validate(values)


def dx_spot(
    callsign: str,
    frequency_hz: int,
    *,
    operator_name: str | None = None,
    grid: str | None = None,
) -> SpotRecord:
    """Build one immutable DX spot for enrichment tests."""
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=DxSpotIdentity(callsign=callsign, frequency=frequency),
        callsign=callsign,
        operator_name=operator_name,
        grid=grid,
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode="USB",
        spotted_at=_FETCHED_AT,
    )


def dx_slice(*spots: SpotRecord) -> ForgeProviderSlice:
    """Build one canonical complete DX provider slice."""
    return ForgeProviderSlice.from_spots(
        provider=SpotProvider.DX,
        fetched_at=_FETCHED_AT,
        spots=spots,
    )


def test_disabled_enrichment_is_a_noop() -> None:
    provider_slice = dx_slice(dx_spot("W1AW", 14_250_000))
    lookup = FakeQrzLookup({})
    enricher = ForgeQrzEnricher(ForgeQrzEnrichmentConfig(), lookup)

    result = enricher.enrich_slice(provider_slice)

    assert result.provider_slice == provider_slice
    assert result.diagnostics.enabled is False
    assert lookup.calls == []


def test_provider_values_take_precedence_over_qrz() -> None:
    original = dx_spot(
        "W1AW",
        14_250_000,
        operator_name="Provider Name",
    )
    lookup = FakeQrzLookup(
        {
            "W1AW": QrzCallsignProfile(
                callsign="W1AW",
                name="QRZ Name",
                image_url=None,
                grid="EM79xm",
            )
        }
    )
    enricher = ForgeQrzEnricher(qrz_config(), lookup)

    result = enricher.enrich_slice(dx_slice(original))
    enriched = result.provider_slice.spots[0]

    assert enriched.operator_name == "Provider Name"
    assert enriched.grid == "EM79xm"
    assert enriched.identity == original.identity
    assert enriched.frequency == original.frequency
    assert enriched.mode == original.mode
    assert enriched.display_mode == original.display_mode
    assert enriched.spotted_at == original.spotted_at
    assert result.diagnostics.enriched_spots == 1


def test_positive_cache_prevents_duplicate_live_lookup() -> None:
    provider_slice = dx_slice(dx_spot("W1AW", 14_250_000))
    lookup = FakeQrzLookup(
        {
            "W1AW": QrzCallsignProfile(
                callsign="W1AW",
                name="Hiram Percy Maxim",
                image_url=None,
                grid="FN31pr",
            )
        }
    )
    enricher = ForgeQrzEnricher(qrz_config(), lookup)

    first = enricher.enrich_slice(provider_slice)
    second = enricher.enrich_slice(provider_slice)

    assert first.diagnostics.live_lookups == 1
    assert second.diagnostics.live_lookups == 0
    assert second.diagnostics.cache_hits == 1
    assert lookup.calls == ["W1AW"]


def test_negative_cache_uses_independent_shorter_ttl() -> None:
    provider_slice = dx_slice(
        dx_spot("W1AW", 14_250_000),
        dx_spot("K1ABC", 14_251_000),
    )
    lookup = FakeQrzLookup(
        {
            "W1AW": QrzCallsignProfile(
                callsign="W1AW",
                name="ARRL",
                image_url=None,
            ),
            "K1ABC": None,
        }
    )
    clock = FakeClock()
    enricher = ForgeQrzEnricher(
        qrz_config(positive_ttl_s=10, negative_ttl_s=3),
        lookup,
        clock=clock,
        sleeper=clock.sleep,
    )

    first = enricher.enrich_slice(provider_slice)
    clock.advance(4)
    second = enricher.enrich_slice(provider_slice)

    assert first.diagnostics.live_lookups == 2
    assert second.diagnostics.cache_hits == 1
    assert second.diagnostics.live_lookups == 1
    assert lookup.calls == ["W1AW", "K1ABC", "K1ABC"]


def test_lru_eviction_is_deterministic() -> None:
    lookup = FakeQrzLookup(
        {
            callsign: QrzCallsignProfile(
                callsign=callsign,
                name=callsign,
                image_url=None,
            )
            for callsign in ("W1AAA", "W1BBB", "W1CCC")
        }
    )
    enricher = ForgeQrzEnricher(qrz_config(max_cache_entries=2), lookup)

    enricher.enrich_slice(dx_slice(dx_spot("W1AAA", 14_250_000)))
    enricher.enrich_slice(dx_slice(dx_spot("W1BBB", 14_251_000)))
    enricher.enrich_slice(dx_slice(dx_spot("W1AAA", 14_252_000)))
    enricher.enrich_slice(dx_slice(dx_spot("W1CCC", 14_253_000)))
    enricher.enrich_slice(dx_slice(dx_spot("W1BBB", 14_254_000)))

    assert lookup.calls == ["W1AAA", "W1BBB", "W1CCC", "W1BBB"]
    assert enricher.cache_size == 2


def test_minimum_live_lookup_interval_uses_injected_sleep() -> None:
    lookup = FakeQrzLookup(
        {
            "W1AAA": None,
            "W1BBB": None,
        }
    )
    clock = FakeClock()
    enricher = ForgeQrzEnricher(
        qrz_config(minimum_request_interval_s=2),
        lookup,
        clock=clock,
        sleeper=clock.sleep,
    )

    result = enricher.enrich_slice(
        dx_slice(
            dx_spot("W1AAA", 14_250_000),
            dx_spot("W1BBB", 14_251_000),
        )
    )

    assert result.diagnostics.live_lookups == 2
    assert clock.sleeps == [2]


def test_refresh_lookup_budget_leaves_remaining_spots_valid() -> None:
    provider_slice = dx_slice(
        dx_spot("W1AAA", 14_250_000),
        dx_spot("W1BBB", 14_251_000),
    )
    lookup = FakeQrzLookup(
        {
            "W1AAA": QrzCallsignProfile(
                callsign="W1AAA",
                name="Alpha",
                image_url=None,
            ),
            "W1BBB": QrzCallsignProfile(
                callsign="W1BBB",
                name="Bravo",
                image_url=None,
            ),
        }
    )
    enricher = ForgeQrzEnricher(
        qrz_config(max_lookups_per_refresh=1),
        lookup,
    )

    result = enricher.enrich_slice(provider_slice)

    assert result.diagnostics.requested_callsigns == 2
    assert result.diagnostics.live_lookups == 1
    assert result.diagnostics.budget_exhausted is True
    assert result.provider_slice.spots[0].operator_name == "Alpha"
    assert result.provider_slice.spots[1].operator_name is None


def test_duplicate_callsign_is_looked_up_once_and_enriches_all_rows() -> None:
    lookup = FakeQrzLookup(
        {
            "W1AW": QrzCallsignProfile(
                callsign="W1AW",
                name="ARRL",
                image_url=None,
                grid="FN31pr",
            )
        }
    )
    enricher = ForgeQrzEnricher(qrz_config(), lookup)

    result = enricher.enrich_slice(
        dx_slice(
            dx_spot("W1AW", 14_250_000),
            dx_spot("W1AW", 21_300_000),
        )
    )

    assert lookup.calls == ["W1AW"]
    assert result.diagnostics.requested_callsigns == 1
    assert result.diagnostics.enriched_spots == 2
    assert all(spot.operator_name == "ARRL" for spot in result.provider_slice.spots)


def test_qrz_failure_preserves_original_provider_slice() -> None:
    provider_slice = dx_slice(dx_spot("W1AW", 14_250_000))
    lookup = FakeQrzLookup({"W1AW": QrzResponseError("temporary QRZ failure")})
    enricher = ForgeQrzEnricher(qrz_config(), lookup)

    result = enricher.enrich_slice(provider_slice)

    assert result.provider_slice == provider_slice
    assert result.diagnostics.live_lookups == 1
    assert result.diagnostics.enriched_spots == 0
    assert result.diagnostics.last_error == "temporary QRZ failure"


def test_mismatched_profile_is_rejected_without_provider_failure() -> None:
    provider_slice = dx_slice(dx_spot("W1AW", 14_250_000))
    lookup = FakeQrzLookup(
        {
            "W1AW": QrzCallsignProfile(
                callsign="K1ABC",
                name="Wrong Station",
                image_url=None,
            )
        }
    )
    enricher = ForgeQrzEnricher(qrz_config(), lookup)

    result = enricher.enrich_slice(provider_slice)

    assert result.provider_slice == provider_slice
    assert result.diagnostics.last_error == (
        "QRZ returned a profile for a different callsign."
    )
