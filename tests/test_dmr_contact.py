"""Tests for converting immutable staged DMR activity into local contacts."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.dmr_activity import DmrActivitySource, DmrCallIdentity
from rolling_thunder.dmr_contact import DmrContactBuildError, build_dmr_contact
from rolling_thunder.dmr_selection import DmrStageOrigin, StagedDmrQso
from rolling_thunder.domain import RadioMode


def _stage(**overrides: object) -> StagedDmrQso:
    started_at = datetime(2026, 8, 16, 0, 7, 8, 120000, tzinfo=UTC)
    values: dict[str, object] = {
        "origin": DmrStageOrigin.CURRENT_AUDIO,
        "identity": DmrCallIdentity(
            started_at=started_at,
            slot=1,
            source=DmrActivitySource.NETWORK,
            callsign="KC9KPJ",
            target="TG 3100",
        ),
        "callsign": "KC9KPJ",
        "slot": 1,
        "target": "TG 3100",
        "talkgroup": 3100,
        "source": DmrActivitySource.NETWORK,
        "started_at": started_at,
        "ended_at": None,
        "name": None,
        "country": None,
        "talker_alias": "KC9KPJ KC9KPJ",
        "duration_s": None,
        "packet_loss_percent": None,
        "ber_percent": None,
        "radio_rx_hz": 434_537_500,
        "radio_tx_hz": 439_537_500,
        "my_grid": "EM79xm",
    }
    values.update(overrides)
    return StagedDmrQso(**values)  # type: ignore[arg-type]


def test_current_audio_builds_dmr_contact_from_frozen_stage() -> None:
    staged = _stage()

    contact = build_dmr_contact(staged)

    assert contact.callsign == "KC9KPJ"
    assert contact.frequency_hz == 439_537_500
    assert contact.mode is RadioMode.DMR
    assert contact.started_at == staged.started_at
    assert contact.rst_sent == "59"
    assert contact.rst_received == "59"
    assert contact.my_grid == "EM79xm"


def test_completed_history_derives_start_time_from_end_and_duration() -> None:
    ended_at = datetime(2026, 8, 16, 0, 7, 22, 84000, tzinfo=UTC)
    staged = _stage(
        origin=DmrStageOrigin.HISTORY,
        started_at=None,
        ended_at=ended_at,
        duration_s=14.2,
        talker_alias=None,
        name="Michael",
        country="USA",
        packet_loss_percent=0.0,
    )

    contact = build_dmr_contact(staged)

    assert contact.started_at == datetime(2026, 8, 16, 0, 7, 7, 884000, tzinfo=UTC)


def test_history_without_duration_uses_completion_timestamp() -> None:
    ended_at = datetime(2026, 8, 16, 0, 7, 22, tzinfo=UTC)
    staged = _stage(started_at=None, ended_at=ended_at, duration_s=None)

    assert build_dmr_contact(staged).started_at == ended_at


def test_contact_notes_preserve_dmr_metadata_and_both_rf_directions() -> None:
    staged = _stage(
        name="Michael",
        country="USA",
        duration_s=14.2,
        packet_loss_percent=0.0,
        ber_percent=0.0,
    )

    notes = build_dmr_contact(staged).notes

    assert notes is not None
    for expected in (
        "DMR",
        "TG 3100",
        "TS1",
        "source=network",
        "TX=439.537500 MHz",
        "RX=434.537500 MHz",
        "name=Michael",
        "country=USA",
        "alias=KC9KPJ KC9KPJ",
        "duration=14.2s",
        "loss=0.0%",
        "BER=0.0%",
    ):
        assert expected in notes


def test_unknown_talkgroup_preserves_original_target_text() -> None:
    staged = _stage(talkgroup=None, target="Private KC9KPJ")

    notes = build_dmr_contact(staged).notes

    assert notes is not None
    assert "Private KC9KPJ" in notes


def test_stage_without_any_timestamp_is_rejected() -> None:
    staged = _stage(started_at=None, ended_at=None, duration_s=None)

    with pytest.raises(DmrContactBuildError, match="no usable contact timestamp"):
        build_dmr_contact(staged)


def test_contact_uses_only_grid_frozen_in_stage() -> None:
    staged = _stage(my_grid="EM79xm")

    contact = build_dmr_contact(staged)

    assert staged.my_grid == "EM79xm"
    assert contact.my_grid == "EM79xm"


def test_non_3100_talkgroup_is_preserved_in_logged_contact() -> None:
    staged = _stage(talkgroup=91, target="TG 91")

    notes = build_dmr_contact(staged).notes

    assert notes is not None
    assert "TG 91" in notes
    assert "TG 3100" not in notes
