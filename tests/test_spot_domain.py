"""Tests for provider-neutral spot domain and canonical ordering."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from rolling_thunder.domain import Frequency, RadioMode
from rolling_thunder.spot_domain import (
    UNKNOWN_SPOT_VALUE,
    DxSpotIdentity,
    PotaSpotIdentity,
    PotaSpotMetadata,
    SpotProvider,
    SpotRecord,
    SpotSnapshot,
    SpotSourceMetadataItem,
    amateur_band_rank,
    canonicalize_spots,
    collapse_duplicate_spots,
    format_optional_spot_value,
)


def pota_spot(
    callsign: str,
    reference: str,
    frequency_hz: int,
    *,
    minute: int = 0,
    operator_name: str | None = None,
    grid: str | None = None,
    display_mode: str = "SSB",
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=PotaSpotIdentity(
            park_reference=reference,
            frequency=frequency,
        ),
        callsign=callsign,
        operator_name=operator_name,
        grid=grid,
        frequency=frequency,
        mode=RadioMode.USB,
        display_mode=display_mode,
        spotted_at=datetime(2026, 8, 5, 20, minute, tzinfo=UTC),
        pota=PotaSpotMetadata(
            park_reference=reference,
            park_name="Test Park",
        ),
    )


def dx_spot(
    callsign: str,
    frequency_hz: int,
    *,
    minute: int = 0,
) -> SpotRecord:
    frequency = Frequency(hz=frequency_hz)
    return SpotRecord(
        identity=DxSpotIdentity(callsign=callsign, frequency=frequency),
        callsign=callsign,
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=datetime(2026, 8, 5, 20, minute, tzinfo=UTC),
    )


def test_pota_identity_uses_provider_park_and_integer_frequency() -> None:
    identity = PotaSpotIdentity(
        park_reference=" us-1234 ",
        frequency=Frequency(hz=14_250_000),
    )

    assert identity.provider is SpotProvider.POTA
    assert identity.park_reference == "US-1234"
    assert identity.stable_key == "pota:US-1234:14250000"


def test_dx_identity_normalizes_callsign_and_frequency() -> None:
    identity = DxSpotIdentity(
        callsign=" k1abc ",
        frequency=Frequency(hz=7_025_000),
    )

    assert identity.provider is SpotProvider.DX
    assert identity.callsign == "K1ABC"
    assert identity.stable_key == "dx:K1ABC:7025000"


def test_record_normalizes_optional_and_presentation_fields() -> None:
    record = pota_spot(
        "ki5vnb",
        "US-1234",
        14_250_000,
        operator_name="  Geoff   Kline ",
        grid="em79XM",
        display_mode=" ssb ",
    )

    assert record.callsign == "KI5VNB"
    assert record.operator_name == "Geoff Kline"
    assert record.grid == "EM79xm"
    assert record.display_mode == "SSB"
    assert record.spotted_at.tzinfo is UTC


def test_record_is_immutable() -> None:
    record = dx_spot("K1ABC", 14_025_000)

    with pytest.raises(ValidationError):
        record.operator_name = "Changed"


def test_pota_record_requires_matching_pota_metadata() -> None:
    frequency = Frequency(hz=14_250_000)

    with pytest.raises(
        ValidationError,
        match="POTA metadata must match the stable identity",
    ):
        SpotRecord(
            identity=PotaSpotIdentity(
                park_reference="US-1234",
                frequency=frequency,
            ),
            callsign="KI5VNB",
            frequency=frequency,
            mode=RadioMode.USB,
            display_mode="SSB",
            spotted_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
            pota=PotaSpotMetadata(park_reference="US-9999"),
        )


def test_dx_record_requires_identity_callsign_match() -> None:
    frequency = Frequency(hz=14_025_000)

    with pytest.raises(
        ValidationError,
        match="DX callsign must match the stable identity",
    ):
        SpotRecord(
            identity=DxSpotIdentity(
                callsign="K1ABC",
                frequency=frequency,
            ),
            callsign="W8XYZ",
            frequency=frequency,
            mode=RadioMode.CW,
            display_mode="CW",
            spotted_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
        )


def test_source_metadata_is_sorted_and_keys_are_unique() -> None:
    frequency = Frequency(hz=14_025_000)
    record = SpotRecord(
        identity=DxSpotIdentity(callsign="K1ABC", frequency=frequency),
        callsign="K1ABC",
        frequency=frequency,
        mode=RadioMode.CW,
        display_mode="CW",
        spotted_at=datetime(2026, 8, 5, 20, 0, tzinfo=UTC),
        source_metadata=(
            SpotSourceMetadataItem(key="z", value="last"),
            SpotSourceMetadataItem(key="a", value="first"),
        ),
    )

    assert [item.key for item in record.source_metadata] == ["a", "z"]

    with pytest.raises(ValidationError, match="keys must be unique"):
        SpotRecord(
            identity=record.identity,
            callsign=record.callsign,
            frequency=record.frequency,
            mode=record.mode,
            display_mode=record.display_mode,
            spotted_at=record.spotted_at,
            source_metadata=(
                SpotSourceMetadataItem(key="same", value="one"),
                SpotSourceMetadataItem(key="same", value="two"),
            ),
        )


def test_unknown_values_are_formatted_only_at_presentation_boundary() -> None:
    assert format_optional_spot_value(None) == UNKNOWN_SPOT_VALUE
    assert format_optional_spot_value("Geoff") == "Geoff"


def test_explicit_amateur_band_rank_is_not_enum_or_arrival_order() -> None:
    assert amateur_band_rank(Frequency(hz=7_200_000)) < amateur_band_rank(Frequency(hz=14_200_000))
    assert amateur_band_rank(Frequency(hz=14_200_000)) < amateur_band_rank(Frequency(hz=50_100_000))


def test_canonical_order_uses_band_frequency_and_stable_tie_breakers() -> None:
    records = (
        dx_spot("W8XYZ", 14_025_000),
        pota_spot("KI5VNB", "US-2222", 7_255_000),
        pota_spot("K1ABC", "US-1111", 14_025_000),
    )

    ordered = canonicalize_spots(reversed(records))

    assert [record.stable_key for record in ordered] == [
        "pota:US-2222:7255000",
        "pota:US-1111:14025000",
        "dx:W8XYZ:14025000",
    ]


def test_duplicate_collapse_prefers_newest_independent_of_arrival_order() -> None:
    older = pota_spot(
        "K1OLD",
        "US-1234",
        14_250_000,
        minute=1,
    )
    newer = pota_spot(
        "K1NEW",
        "US-1234",
        14_250_000,
        minute=2,
    )

    first = collapse_duplicate_spots((older, newer))
    second = collapse_duplicate_spots((newer, older))

    assert first == second
    assert len(first) == 1
    assert first[0].callsign == "K1NEW"


def test_snapshot_factory_collapses_and_orders_input() -> None:
    duplicate_old = pota_spot(
        "K1OLD",
        "US-1234",
        14_250_000,
        minute=1,
    )
    duplicate_new = pota_spot(
        "K1NEW",
        "US-1234",
        14_250_000,
        minute=2,
    )
    forty = dx_spot("W8XYZ", 7_025_000)

    snapshot = SpotSnapshot.from_spots(
        generated_at=datetime(2026, 8, 5, 21, 0, tzinfo=UTC),
        spots=(duplicate_old, duplicate_new, forty),
    )

    assert [spot.stable_key for spot in snapshot.spots] == [
        "dx:W8XYZ:7025000",
        "pota:US-1234:14250000",
    ]
    assert snapshot.spots[1].callsign == "K1NEW"


def test_snapshot_rejects_noncanonical_direct_construction() -> None:
    twenty = dx_spot("W8XYZ", 14_025_000)
    forty = dx_spot("K1ABC", 7_025_000)

    with pytest.raises(ValidationError, match="canonical shared order"):
        SpotSnapshot(
            generated_at=datetime(2026, 8, 5, 21, 0, tzinfo=UTC),
            spots=(twenty, forty),
        )


def test_snapshot_index_and_get_use_stable_identity() -> None:
    first = dx_spot("K1ABC", 7_025_000)
    second = pota_spot("KI5VNB", "US-1234", 14_250_000)
    snapshot = SpotSnapshot.from_spots(
        generated_at=datetime(2026, 8, 5, 21, 0, tzinfo=UTC),
        spots=(second, first),
    )

    assert snapshot.index_of(second.identity) == 1
    assert snapshot.get(second.identity) == second


def test_snapshot_timestamp_is_normalized_to_utc() -> None:
    snapshot = SpotSnapshot.from_spots(
        generated_at=datetime(
            2026,
            8,
            5,
            17,
            0,
            tzinfo=timezone(-timedelta(hours=4)),
        ),
        spots=(),
    )

    assert snapshot.generated_at == datetime(2026, 8, 5, 21, 0, tzinfo=UTC)
