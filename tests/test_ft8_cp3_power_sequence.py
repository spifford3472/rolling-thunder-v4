"""No-RF CP3 control invariants for bounded, opt-in, repeated-CQ power."""
from datetime import UTC, datetime
from uuid import uuid4

from rolling_thunder.domain import Frequency, RadioConnectionState, RadioMode, RadioState
from rolling_thunder.ft8.domain import FT8CQActivity, FT8Period
from rolling_thunder.ft8.performance_recording import build_ft8_attempt_seed
from rolling_thunder.ft8.power_advisor import FT8PowerPolicy


def test_new_ft8_attempt_baselines_at_twenty_watts_even_for_distant_dx():
    started = datetime(2026, 10, 10, 21, tzinfo=UTC)
    activity = FT8CQActivity(
        callsign="VK2ABC", last_period=FT8Period.from_utc(started),
        snr_db=-10, dt_seconds=0.1, audio_frequency_hz=1200,
        grid="QF56",
    )
    seed = build_ft8_attempt_seed(
        activity, radio_state=RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=14074000), mode=RadioMode.USB,
            updated_at=started,
        ), gps_state=None, home_grid="EM79xm", started_at_utc=started,
        attempt_id=uuid4(),
        power_policy=FT8PowerPolicy(initial_power_watts=20, adaptive_enabled=True),
    )
    assert seed.tx_power_target_watts == 20
