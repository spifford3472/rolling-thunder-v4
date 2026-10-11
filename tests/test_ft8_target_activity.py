"""One integrated radio-free decode session covers CQ, third-party exchange and aging."""
from rolling_thunder.ft8.domain import FT8Decode, FT8MessageKind, FT8Period
from rolling_thunder.ft8.status import target_activity_status
from rolling_thunder.ft8.target_activity import FT8TargetActivityTracker, TargetActivityKind


def decoded(index: int, kind: FT8MessageKind, source: str, destination: str | None = None) -> FT8Decode:
    return FT8Decode(
        period=FT8Period(index), snr_db=-10, dt_seconds=0.1,
        audio_frequency_hz=1000, raw_message=f"{destination or 'CQ'} {source} -10",
        kind=kind, source_callsign=source, destination_callsign=destination,
    )


def test_entire_selected_target_session() -> None:
    tracker = FT8TargetActivityTracker(freshness_periods=4, local_callsign="KI5VNB")
    tracker.select("K4TMR")
    assert tracker.snapshot().kind is TargetActivityKind.UNKNOWN
    tracker.observe((decoded(100, FT8MessageKind.CQ, "K4TMR"),), FT8Period(100))
    assert tracker.snapshot().kind is TargetActivityKind.CQ
    assert target_activity_status(tracker.snapshot()) == "K4TMR CALLING CQ"
    # Listening to someone calling the target must not be mistaken for the target's reply.
    tracker.observe((decoded(101, FT8MessageKind.REPORT, "W9XYZ", "K4TMR"),), FT8Period(101))
    assert tracker.snapshot().kind is TargetActivityKind.CQ
    tracker.observe((decoded(102, FT8MessageKind.REPORT, "K4TMR", "W9XYZ"),), FT8Period(102))
    state = tracker.snapshot()
    assert state.kind is TargetActivityKind.OTHER_QSO
    assert state.other_callsign == "W9XYZ"
    assert state.observed_source
    assert target_activity_status(state) == "K4TMR → W9XYZ REPORT"
    tracker.observe((decoded(103, FT8MessageKind.REPORT, "K4TMR", "KI5VNB"),), FT8Period(103))
    assert tracker.snapshot().other_callsign == "W9XYZ"
    tracker.observe((decoded(103, FT8MessageKind.R_REPORT, "K4TMR", "W9XYZ"),), FT8Period(103))
    assert tracker.snapshot().message_kind is FT8MessageKind.R_REPORT
    assert target_activity_status(tracker.snapshot()) == "K4TMR → W9XYZ R-REPORT"
    tracker.observe((decoded(104, FT8MessageKind.ACK_73, "K4TMR", "W9XYZ"),), FT8Period(104))
    assert tracker.snapshot().kind is TargetActivityKind.SIGNOFF
    assert target_activity_status(tracker.snapshot()) == "K4TMR → W9XYZ 73"
    tracker.observe((decoded(103, FT8MessageKind.REPORT, "K4TMR", "W9XYZ"),), FT8Period(105))
    assert tracker.snapshot().kind is TargetActivityKind.SIGNOFF
    tracker.observe((), FT8Period(108))
    assert tracker.snapshot().kind is TargetActivityKind.UNKNOWN
    assert target_activity_status(tracker.snapshot()) is None
    tracker.observe((decoded(109, FT8MessageKind.CQ, "K4TMR"),), FT8Period(109))
    assert tracker.snapshot().kind is TargetActivityKind.CQ
    tracker.select("WW5G")
    assert tracker.snapshot().kind is TargetActivityKind.UNKNOWN
    tracker.select(None)
    assert tracker.snapshot() is None
