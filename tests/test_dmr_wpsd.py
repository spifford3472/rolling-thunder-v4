"""Tests for WPSD DMR history and radio-info payload parsing."""

from datetime import UTC, datetime

import pytest

from rolling_thunder.dmr_activity import DmrActivitySource
from rolling_thunder.dmr_wpsd import (
    WpsdPayloadError,
    parse_wpsd_dmr_history,
    parse_wpsd_radio_info,
)

_HISTORY_JSON = """[
  {
    "time_utc": "2026-08-16 00:07:22",
    "mode": "DMR Slot 1",
    "callsign": "KC9KPJ",
    "name": "Michael",
    "country": "USA",
    "callsign_suffix": "",
    "target": "TG 3100",
    "src": "Net",
    "duration": "14.2",
    "loss": "0%"
  },
  {
    "time_utc": "2026-08-16 00:07:00",
    "mode": "DMR Slot 1",
    "callsign": "W3GSI",
    "name": "Raymond",
    "country": "USA",
    "callsign_suffix": "",
    "target": "TG 3100",
    "src": "Net",
    "duration": "8.8",
    "loss": "0%"
  }
]"""

_RADIO_INFO_HTML = """
<div class="divTable">
  <div class="divTableBody">
    <div class="divTableRow center">
      <div class="divTableHeadCell noMob" style="width:250px;">Radio Status</div>
      <div class="divTableHeadCell noMob">TX Freq.</div>
      <div class="divTableHeadCell noMob">RX Freq.</div>
      <div class="divTableHeadCell noMob">Radio Mode</div>
      <div class="divTableHeadCell noMob">Modem Port</div>
      <div class="divTableHeadCell noMob">Modem Speed</div>
      <div class="divTableHeadCell noMob">TCXO Freq.</div>
      <div class="divTableHeadCell noMob">Modem Type</div>
    </div>
    <div class="divTableRow center">
      <div class="divTableCell middle cell_content" style="font-weight:bold;padding:2px;">IDLE</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">434.537.500 MHz</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">439.537.500 MHz</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">Duplex</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">/dev/ttyAMA0</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">115,200 bps</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">14.7456 MHz</div>
      <div class="divTableCell cell_content middle noMob" style="background: #EFF2F5;">MMDVM_HS_Dual_Hat-v.1.5.2</div>
    </div>
  </div>
</div>
"""


def test_parse_wpsd_dmr_history_normalizes_observed_record() -> None:
    """The observed KC9KPJ history row should become a typed immutable record."""
    records = parse_wpsd_dmr_history(_HISTORY_JSON)

    assert len(records) == 2
    record = records[0]

    assert record.callsign == "KC9KPJ"
    assert record.name == "Michael"
    assert record.country == "USA"
    assert record.callsign_suffix is None
    assert record.occurred_at == datetime(2026, 8, 16, 0, 7, 22, tzinfo=UTC)
    assert record.slot == 1
    assert record.talkgroup == 3100
    assert record.target == "TG 3100"
    assert record.source is DmrActivitySource.NETWORK
    assert record.duration_s == 14.2
    assert record.packet_loss_percent == 0.0


def test_history_identity_ignores_optional_enrichment_fields() -> None:
    """Name/country refreshes must not destabilize selection identity."""
    original = parse_wpsd_dmr_history(_HISTORY_JSON)[0]
    enriched_payload = _HISTORY_JSON.replace('"Michael"', '"Mike"').replace('"USA"', '"United States"')
    refreshed = parse_wpsd_dmr_history(enriched_payload)[0]

    assert refreshed.identity == original.identity
    assert refreshed.name == "Mike"
    assert refreshed.country == "United States"


def test_history_parser_filters_non_dmr_rows() -> None:
    """Other WPSD modes should not appear in the DMR panel history."""
    payload = """[
      {
        "time_utc": "2026-08-16 00:08:00",
        "mode": "YSF",
        "callsign": "W8O",
        "target": "America-Link",
        "src": "Net",
        "duration": "5.0",
        "loss": "0%"
      }
    ]"""

    assert parse_wpsd_dmr_history(payload) == ()


def test_history_parser_supports_rf_source_and_ts_mode_label() -> None:
    """WPSD DMR aliases used by dashboard output should normalize consistently."""
    payload = """[
      {
        "time_utc": "2026-08-16 00:09:00",
        "mode": "DMR TS2",
        "callsign": "KI5VNB",
        "name": null,
        "country": null,
        "callsign_suffix": null,
        "target": "TG 9",
        "src": "RF",
        "duration": "3.5",
        "loss": "0.1%"
      }
    ]"""

    record = parse_wpsd_dmr_history(payload)[0]

    assert record.slot == 2
    assert record.talkgroup == 9
    assert record.source is DmrActivitySource.RF
    assert record.name is None
    assert record.country is None
    assert record.packet_loss_percent == 0.1


def test_history_parser_rejects_non_array_payload() -> None:
    """Unexpected API shapes should fail visibly rather than silently corrupt state."""
    with pytest.raises(WpsdPayloadError, match="JSON array"):
        parse_wpsd_dmr_history('{"callsign": "KC9KPJ"}')


def test_history_parser_rejects_dmr_row_without_talkgroup() -> None:
    """A DMR row without a numeric talkgroup cannot support staged logging."""
    payload = _HISTORY_JSON.replace('"TG 3100"', '"Private Call"', 1)

    with pytest.raises(WpsdPayloadError, match="does not contain a talkgroup"):
        parse_wpsd_dmr_history(payload)


def test_parse_wpsd_radio_info_preserves_both_rf_directions() -> None:
    """Hotspot TX/RX must be preserved before choosing a logging convention."""
    info = parse_wpsd_radio_info(_RADIO_INFO_HTML)

    assert info.status == "IDLE"
    assert info.mode == "Duplex"
    assert info.hotspot_tx_hz == 434_537_500
    assert info.hotspot_rx_hz == 439_537_500
    assert info.radio_rx_hz == 434_537_500
    assert info.radio_tx_hz == 439_537_500


def test_radio_info_parser_accepts_decimal_mhz_format() -> None:
    """The parser should also tolerate conventional decimal MHz formatting."""
    payload = _RADIO_INFO_HTML.replace("434.537.500 MHz", "434.537500 MHz").replace(
        "439.537.500 MHz",
        "439.537500 MHz",
    )

    info = parse_wpsd_radio_info(payload)

    assert info.hotspot_tx_hz == 434_537_500
    assert info.hotspot_rx_hz == 439_537_500


def test_radio_info_parser_rejects_missing_rx_frequency() -> None:
    """Incomplete RF configuration must not produce a plausible-looking snapshot."""
    payload = _RADIO_INFO_HTML.replace("RX Freq.", "Missing RX")

    with pytest.raises(WpsdPayloadError, match="missing field 'RX Freq.'"):
        parse_wpsd_radio_info(payload)
