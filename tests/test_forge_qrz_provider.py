"""Tests for the QRZ-enriched Forge provider decorator."""

from datetime import UTC, datetime

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.forge_config import ForgeQrzEnrichmentConfig
from rolling_thunder.forge_qrz_enrichment import ForgeQrzEnricher
from rolling_thunder.forge_qrz_provider import ForgeQrzEnrichedSpotProvider
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProviderConnectionError,
    MockForgeSpotProvider,
)
from rolling_thunder.qrz_xml import QrzCallsignProfile
from rolling_thunder.spot_domain import DxSpotIdentity, SpotProvider, SpotRecord

_FETCHED_AT = datetime(2026, 8, 6, 2, 5, tzinfo=UTC)


class FakeQrzLookup:
    def __init__(self, profile: QrzCallsignProfile | None) -> None:
        self.profile = profile
        self.calls: list[str] = []

    def lookup_profile(self, callsign: str) -> QrzCallsignProfile | None:
        self.calls.append(str(callsign))
        return self.profile


def dx_slice() -> ForgeProviderSlice:
    frequency = Frequency(hz=14_250_000)
    return ForgeProviderSlice.from_spots(
        provider=SpotProvider.DX,
        fetched_at=_FETCHED_AT,
        spots=(
            SpotRecord(
                identity=DxSpotIdentity(
                    callsign="W1AW",
                    frequency=frequency,
                ),
                callsign="W1AW",
                frequency=frequency,
                mode=RadioMode.USB,
                display_mode="SSB",
                spotted_at=_FETCHED_AT,
            ),
        ),
    )


def enabled_config() -> ForgeQrzEnrichmentConfig:
    return ForgeQrzEnrichmentConfig(
        enabled=True,
        minimum_request_interval_s=0,
    )


def test_decorator_preserves_provider_and_enriches_complete_slice() -> None:
    underlying = MockForgeSpotProvider(dx_slice())
    lookup = FakeQrzLookup(
        QrzCallsignProfile(
            callsign="W1AW",
            name="ARRL",
            image_url=None,
            grid="FN31pr",
        )
    )
    provider = ForgeQrzEnrichedSpotProvider(
        underlying,
        ForgeQrzEnricher(enabled_config(), lookup),
    )

    provider_slice = provider.fetch_slice()

    assert provider.provider is SpotProvider.DX
    assert provider_slice.provider is SpotProvider.DX
    assert provider_slice.spots[0].operator_name == "ARRL"
    assert provider_slice.spots[0].grid == "FN31pr"
    assert provider.last_diagnostics.enriched_spots == 1
    assert lookup.calls == ["W1AW"]


def test_underlying_provider_failure_is_not_hidden_by_enrichment() -> None:
    underlying = MockForgeSpotProvider(dx_slice())
    underlying.set_error(ForgeSpotProviderConnectionError("cluster unavailable"))
    provider = ForgeQrzEnrichedSpotProvider(
        underlying,
        ForgeQrzEnricher(enabled_config(), FakeQrzLookup(None)),
    )

    try:
        provider.fetch_slice()
    except ForgeSpotProviderConnectionError as error:
        assert str(error) == "cluster unavailable"
    else:
        raise AssertionError("expected the wrapped provider failure")

    assert provider.last_diagnostics.enabled is False
