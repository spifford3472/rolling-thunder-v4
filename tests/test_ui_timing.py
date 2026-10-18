"""Major UI timing aggregate contract (no production application required)."""

from rolling_thunder.ui_timing import UiTiming


def test_disabled_collector_never_uses_clock():
    def forbidden():
        raise AssertionError("disabled tracing called clock")
    sample = UiTiming(clock=forbidden)
    sample.begin_refresh()
    sample.observe("map", 0)
    sample.end_refresh(0)


def test_enabled_collector_is_bounded_and_reports_only_aggregates(caplog):
    caplog.set_level("INFO")
    now = [0.0]
    timer = UiTiming(enabled=True, clock=lambda: now[0], report_every=2, capacity=2)
    for i in range(3):
        started = timer.begin_refresh()
        controls = timer.start()
        now[0] += 0.001
        timer.observe("controls", controls)
        map_started = timer.start()
        now[0] += 0.003
        timer.observe("map", map_started)
        now[0] += 0.002
        timer.end_refresh(started)
        now[0] += 0.25
    assert len(timer._samples["refresh"]) == 2
    assert len(timer._samples["controls"]) == 2
    assert len(timer._samples["map"]) == 2
    assert len(timer._samples["refresh_gap"]) == 2
    assert "R1A_UI_TIMING" in caplog.text
    assert "p95_ms" in caplog.text


def test_invalid_limits_rejected():
    import pytest
    with pytest.raises(ValueError):
        UiTiming(enabled=True, capacity=0)
    with pytest.raises(ValueError):
        UiTiming(enabled=True, report_every=0)
