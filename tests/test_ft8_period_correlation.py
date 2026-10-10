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
