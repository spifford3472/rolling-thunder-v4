"""Major UI timing aggregate contract (no production application required)."""

from rolling_thunder.ui_timing import UiTiming


def test_disabled_collector_never_uses_clock():
    def forbidden():
        raise AssertionError("disabled tracing called clock")
    sample = UiTiming(clock=forbidden)
    sample.begin_refresh()
    sample.observe("map", 0)
    sample.checkpoint("pre_controls")
    sample.end_refresh(0)


def test_enabled_collector_is_bounded_and_reports_only_aggregates(capsys):
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
    output = capsys.readouterr()
    assert "R1A_UI_TIMING" in output.err
    assert "p95_ms" in output.err
    assert output.out == ""


def test_invalid_limits_rejected():
    import pytest
    with pytest.raises(ValueError):
        UiTiming(enabled=True, capacity=0)
    with pytest.raises(ValueError):
        UiTiming(enabled=True, report_every=0)


def test_slow_refresh_reports_correlated_bounded_phase_durations(capsys):
    now = [0.0]
    timer = UiTiming(
        enabled=True,
        clock=lambda: now[0],
        report_every=99,
        slow_refresh_threshold_ms=100,
    )

    started = timer.begin_refresh()
    for name, elapsed in (
        ("pre_controls", 0.005),
        ("controls", 0.020),
        ("map_prepare", 0.015),
        ("map_update", 0.040),
        ("presentation", 0.030),
    ):
        now[0] += elapsed
        timer.checkpoint(name)
    now[0] += 0.040
    timer.end_refresh(started)

    lines = capsys.readouterr().err.splitlines()
    event = next(line for line in lines if line.startswith("R1C2_SLOW_REFRESH "))
    assert "id=1" in event
    assert "duration_ms=150.00" in event
    assert "pre_controls_ms=5.00" in event
    assert "controls_ms=20.00" in event
    assert "map_prepare_ms=15.00" in event
    assert "map_update_ms=40.00" in event
    assert "presentation_ms=30.00" in event
    assert "context_widgets_ms=40.00" in event
    assert len(timer._samples["refresh"]) == 1


def test_slow_refresh_output_is_rate_limited(capsys):
    now = [0.0]
    timer = UiTiming(
        enabled=True,
        clock=lambda: now[0],
        report_every=99,
        slow_refresh_threshold_ms=100,
        slow_report_interval_s=1.0,
    )
    for _ in range(2):
        started = timer.begin_refresh()
        now[0] += 0.150
        timer.end_refresh(started)

    assert capsys.readouterr().err.count("R1C2_SLOW_REFRESH") == 1


def test_invalid_slow_refresh_limits_rejected():
    import pytest

    with pytest.raises(ValueError):
        UiTiming(slow_refresh_threshold_ms=0)
    with pytest.raises(ValueError):
        UiTiming(slow_report_interval_s=0)
