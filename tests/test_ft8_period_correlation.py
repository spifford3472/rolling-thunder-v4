from datetime import UTC, datetime, timedelta
from uuid import uuid4

from rolling_thunder.ft8.hardware_transmit import FT8TransmitPeriodTelemetry
from rolling_thunder.ft8.period_correlation import FT8ReceptionObservation, attribute_reception


def test_unique_window_and_verified_cat_power():
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    qso = uuid4()
    emission = FT8TransmitPeriodTelemetry(qso, now, now + timedelta(seconds=12), 20, True, 14074000, True)
    reception = FT8ReceptionObservation(now + timedelta(seconds=2), 14074000, "W1XYZ")
    result = attribute_reception(reception, (emission,))
    assert result.transmission == emission
    assert result.reason == "unique_period_verified_setting"
    assert attribute_reception(reception, (emission, emission)).reason == "ambiguous"
    assert attribute_reception(FT8ReceptionObservation(now, 7074000, "W1XYZ"), (emission,)).reason == "no_matching_period"
    unverified = FT8TransmitPeriodTelemetry(qso, now, now + timedelta(seconds=12), None, False, 14074000, True)
    assert attribute_reception(reception, (unverified,)).reason == "power_unverified"


def test_rf_matches_only_own_transmit_waveform_offset():
    now = datetime(2026, 10, 10, 12, tzinfo=UTC)
    record = FT8TransmitPeriodTelemetry(uuid4(), now, now + timedelta(seconds=12), 20, True, 14074000, True, 1500)
    good = FT8ReceptionObservation(now, 14075507, "W1XYZ", frequency_is_rf=True)
    assert attribute_reception(good, (record,)).transmission == record
    assert attribute_reception(FT8ReceptionObservation(now, 14075511, "W1XYZ", frequency_is_rf=True), (record,)).reason == "no_matching_period"
    legacy = FT8TransmitPeriodTelemetry(uuid4(), now, now, 20, True, 14074000, True)
    assert attribute_reception(good, (legacy,)).reason == "missing_transmit_audio_offset"
    dubious = FT8ReceptionObservation(now, 14075500, "W1XYZ", audio_offset_hz=1500, frequency_is_rf=True)
    assert attribute_reception(dubious, (record,)).reason == "receiver_offset_not_trusted"
    assert attribute_reception(good, (record, record)).reason == "ambiguous"
    assert attribute_reception(FT8ReceptionObservation(now, 7075500, "W1XYZ", frequency_is_rf=True), (record,)).reason == "no_matching_period"
    assert attribute_reception(FT8ReceptionObservation(now + timedelta(minutes=1), 14075500, "W1XYZ", frequency_is_rf=True), (record,)).reason == "no_matching_period"


def test_rf_offset_midnight_and_unverified_power():
    now = datetime(2026, 10, 10, 23, 59, 55, tzinfo=UTC)
    record = FT8TransmitPeriodTelemetry(uuid4(), now, now + timedelta(seconds=12), None, False, 7074000, True, 1800)
    received = FT8ReceptionObservation(now + timedelta(seconds=8), 7075800, "W1XYZ", frequency_is_rf=True)
    assert attribute_reception(received, (record,)).reason == "power_unverified"
    assert attribute_reception(FT8ReceptionObservation(now, -1, "W1XYZ", frequency_is_rf=True), (record,)).reason == "invalid_reception_frequency"
