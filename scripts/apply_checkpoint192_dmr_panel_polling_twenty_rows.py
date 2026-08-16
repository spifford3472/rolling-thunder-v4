"""Apply Checkpoint 192 DMR panel-scoped polling and twenty-row presentation.

This recovery/performance patch is designed for the installed-car feature-branch
state after the one-column DMR readability work. It deliberately tolerates the
last stale ten-row widget test whether or not the tiny #10F4C repair was run.

Changes:
- show all twenty retained WPSD history records in one full-width column,
- slightly enlarge the right-side history detail text,
- avoid reconfiguring Tk widgets when the immutable DMR viewport is unchanged,
- allow WPSD HTTP polling to be enabled/disabled without stopping the live SSH
  event stream or blocking the Tk thread,
- have the dashboard enable WPSD polling only while the DMR context is selected.

The live SSH feed remains event-driven and connected; it is not periodic polling.
The installed polling cadence is intentionally left to local YAML so the car can
be tested at 30 seconds before changing repository defaults.
"""

from __future__ import annotations

import re
from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one match in {path} but found {count}: {old[:110]!r}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED   {path}")


def regex_once(path: Path, pattern: str, replacement: str) -> None:
    text = path.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one regex match in {path} but found {count}: {pattern!r}"
        )
    path.write_text(updated, encoding="utf-8")
    print(f"PATCHED   {path}")


def replace_geometry_test(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.index("def test_widget_adapter_limits_preallocated_card_slots")
    end = text.find("\ndef ", start + 4)
    if end == -1:
        end = len(text)
    old_block = text[start:end]
    new_block = '''def test_widget_adapter_limits_preallocated_card_slots(monkeypatch: Any) -> None:
    _install_fake_tk(monkeypatch)

    widgets = DmrWidgets(FakeWidget())

    assert len(widgets._audio_frames) == 2
    assert len(widgets._history_frames) == 20
    assert widgets._history_frames[0].options["grid_row"] == 8
    assert widgets._history_frames[0].options["grid_column"] == 0
    assert widgets._history_frames[0].options["grid_columnspan"] == 2
    assert widgets._history_frames[9].options["grid_row"] == 17
    assert widgets._history_frames[9].options["grid_column"] == 0
    assert widgets._history_frames[9].options["grid_columnspan"] == 2
    assert widgets._history_frames[19].options["grid_row"] == 27
    assert widgets._history_frames[19].options["grid_column"] == 0
    assert widgets._history_frames[19].options["grid_columnspan"] == 2
    assert widgets._history_frames[0].children[1].options["font"] == (
        "DejaVu Sans",
        21,
        "bold",
    )
'''
    path.write_text(text[:start] + new_block + text[end:], encoding="utf-8")
    print(f"PATCHED   {path}")


def main() -> None:
    dmr_ui = Path("src/rolling_thunder/dmr_ui.py")
    widgets = Path("src/rolling_thunder/dmr_widgets.py")
    monitor = Path("src/rolling_thunder/dmr_monitor.py")
    panel_runtime = Path("src/rolling_thunder/dmr_panel_runtime.py")
    ui_main = Path("src/rolling_thunder/ui_main.py")
    viewport_tests = Path("tests/test_dmr_ui.py")
    widget_tests = Path("tests/test_dmr_widgets.py")
    monitor_tests = Path("tests/test_dmr_monitor.py")
    runtime_tests = Path("tests/test_dmr_panel_runtime.py")
    wiring_tests = Path("tests/test_dmr_dashboard_wiring.py")

    # ----- Twenty visible history rows -----
    regex_once(
        dmr_ui,
        r"^_DEFAULT_MAX_HISTORY_ROWS = \d+$",
        "_DEFAULT_MAX_HISTORY_ROWS = 20",
    )
    regex_once(
        widgets,
        r"^_MAX_HISTORY_CARDS = \d+$",
        "_MAX_HISTORY_CARDS = 20",
    )

    # The one-column repair leaves the right-side detail at 19 pt. Increase it
    # slightly while preserving its same-row right alignment.
    regex_once(
        widgets,
        r'font=\("DejaVu Sans", 19, "bold"\),\n\s+anchor="e",\n\s+\)\.grid\(row=0, column=1, sticky="e", padx=\(4, 8\), pady=0\)',
        'font=("DejaVu Sans", 21, "bold"),\n                anchor="e",\n            ).grid(row=0, column=1, sticky="e", padx=(4, 8), pady=0)',
    )

    # Twenty cards occupy rows 8..27, so all footer rows must move below them.
    regex_once(
        widgets,
        r'\)\.grid\(row=18, column=0, columnspan=2, sticky="ew", padx=6, pady=\(1, 0\)\)',
        ').grid(row=28, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0))',
    )
    regex_once(
        widgets,
        r'\)\.grid\(row=19, column=0, columnspan=2, sticky="ew", padx=6, pady=\(2, 0\)\)',
        ').grid(row=29, column=0, columnspan=2, sticky="ew", padx=6, pady=(2, 0))',
    )
    regex_once(
        widgets,
        r'row=20, column=0, columnspan=2, sticky="ew", padx=6, pady=\(1, 0\)',
        'row=30, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0)',
    )

    # Avoid re-running dozens of Tk configure/grid operations every 250 ms when
    # neither monitor, selection, nor commit presentation has changed.
    replace_once(
        widgets,
        """        self._commit_label.grid(
            row=30, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0)
        )
        self.hide()
""",
        """        self._commit_label.grid(
            row=30, column=0, columnspan=2, sticky="ew", padx=6, pady=(1, 0)
        )
        self._last_viewport: DmrViewport | None = None
        self.hide()
""",
    )
    replace_once(
        widgets,
        """    def update(self, viewport: DmrViewport) -> None:
        \"\"\"Render one immutable viewport snapshot using only local widget operations.\"\"\"
        self._health.set(viewport.health_line)
""",
        """    def update(self, viewport: DmrViewport) -> None:
        \"\"\"Render a changed immutable viewport using only local widget operations.\"\"\"
        if viewport == self._last_viewport:
            return
        self._last_viewport = viewport
        self._health.set(viewport.health_line)
""",
    )

    # Update the 20-record viewport expectation. This pattern intentionally
    # matches either the current ten-row expectation or a previously repaired
    # equivalent location.
    regex_once(
        viewport_tests,
        r"assert len\(viewport\.history_cards\) == 10\n\s+assert viewport\.hidden_above_count == 0\n\s+assert viewport\.hidden_below_count == 10",
        "assert len(viewport.history_cards) == 20\n    assert viewport.hidden_above_count == 0\n    assert viewport.hidden_below_count == 0",
    )
    replace_geometry_test(widget_tests)

    # ----- Panel-scoped WPSD polling -----
    replace_once(
        monitor,
        """        self._stop_event = Event()
        self._snapshot = DmrMonitorSnapshot()
""",
        """        self._stop_event = Event()
        self._polling_enabled = Event()
        self._polling_enabled.set()
        self._polling_wake = Event()
        self._snapshot = DmrMonitorSnapshot()
""",
    )
    replace_once(
        monitor,
        """    @property
    def is_running(self) -> bool:
        \"\"\"Return whether monitor workers are currently owned by the service.\"\"\"
        with self._lock:
            return self._live_thread is not None or self._wpsd_thread is not None

    def start(self) -> DmrMonitorSnapshot:
""",
        """    @property
    def is_running(self) -> bool:
        \"\"\"Return whether monitor workers are currently owned by the service.\"\"\"
        with self._lock:
            return self._live_thread is not None or self._wpsd_thread is not None

    @property
    def polling_enabled(self) -> bool:
        \"\"\"Return whether periodic WPSD HTTP polling is currently enabled.\"\"\"
        return self._polling_enabled.is_set()

    def set_polling_enabled(self, enabled: bool) -> None:
        \"\"\"Enable or pause WPSD polling without blocking or touching the live feed.\"\"\"
        if self._polling_enabled.is_set() == enabled:
            return
        if enabled:
            self._polling_enabled.set()
        else:
            self._polling_enabled.clear()
        self._polling_wake.set()

    def start(self) -> DmrMonitorSnapshot:
""",
    )
    replace_once(
        monitor,
        """        self._stop_event.set()
        self._live_source.close()
""",
        """        self._stop_event.set()
        self._polling_wake.set()
        self._live_source.close()
""",
    )
    replace_once(
        monitor,
        """    def _run_wpsd(self) -> None:
        while not self._stop_event.is_set():
            self._refresh_history()
            if self._stop_event.is_set():
                return
            self._refresh_radio_info()
            if self._stop_event.wait(self._history_refresh_interval_s):
                return
""",
        """    def _run_wpsd(self) -> None:
        while not self._stop_event.is_set():
            if not self._polling_enabled.is_set():
                self._polling_wake.wait(timeout=0.5)
                self._polling_wake.clear()
                continue

            self._refresh_history()
            if self._stop_event.is_set():
                return
            if not self._polling_enabled.is_set():
                continue

            self._refresh_radio_info()
            if self._stop_event.is_set():
                return

            self._polling_wake.wait(timeout=self._history_refresh_interval_s)
            self._polling_wake.clear()
""",
    )

    replace_once(
        panel_runtime,
        """    @property
    def is_running(self) -> bool:
        \"\"\"Return whether the DMR monitor workers are currently owned.\"\"\"
        return self.monitor.is_running

    def start(self) -> DmrMonitorSnapshot:
""",
        """    @property
    def is_running(self) -> bool:
        \"\"\"Return whether the DMR monitor workers are currently owned.\"\"\"
        return self.monitor.is_running

    @property
    def polling_enabled(self) -> bool:
        \"\"\"Return whether WPSD HTTP polling is currently enabled.\"\"\"
        return self.monitor.polling_enabled

    def set_polling_enabled(self, enabled: bool) -> None:
        \"\"\"Enable WPSD polling only when the DMR panel needs fresh HTTP data.\"\"\"
        self.monitor.set_polling_enabled(enabled)

    def start(self) -> DmrMonitorSnapshot:
""",
    )

    # Dashboard starts the monitor with WPSD dormant, then toggles polling from
    # the current context. set_polling_enabled is idempotent and performs no I/O.
    replace_once(
        ui_main,
        """        if dmr_panel_runtime is not None:
            dmr_panel_runtime.start()
""",
        """        if dmr_panel_runtime is not None:
            dmr_panel_runtime.set_polling_enabled(False)
            dmr_panel_runtime.start()
""",
    )
    replace_once(
        ui_main,
        """        selected_context = context_navigation.state
        set_dmr_expanded_layout(
""",
        """        selected_context = context_navigation.state
        if dmr_panel_runtime is not None:
            dmr_panel_runtime.set_polling_enabled(
                selected_context.selected is ContextId.DMR
            )
        set_dmr_expanded_layout(
""",
    )

    polling_test = '''\n\ndef test_wpsd_polling_can_pause_and_resume_without_stopping_live_feed() -> None:
    live = ControlledLiveSource()
    wpsd = FakeWpsdSource()
    service = DmrMonitorService(
        live,
        wpsd,
        history_refresh_interval_s=0.03,
        reconnect_delay_s=0.05,
    )
    service.set_polling_enabled(False)
    service.start()
    assert live.started.wait(timeout=1)
    _wait_until(lambda: service.latest_state.live_available)

    time.sleep(0.08)
    assert wpsd.history_calls == 0
    assert wpsd.radio_calls == 0

    service.set_polling_enabled(True)
    _wait_until(lambda: wpsd.history_calls >= 1 and wpsd.radio_calls >= 1)

    service.set_polling_enabled(False)
    history_calls = wpsd.history_calls
    radio_calls = wpsd.radio_calls
    time.sleep(0.09)
    assert wpsd.history_calls == history_calls
    assert wpsd.radio_calls == radio_calls
    assert service.latest_state.live_available

    service.set_polling_enabled(True)
    _wait_until(
        lambda: wpsd.history_calls > history_calls and wpsd.radio_calls > radio_calls
    )
    service.stop()
'''
    monitor_text = monitor_tests.read_text(encoding="utf-8")
    if "test_wpsd_polling_can_pause_and_resume_without_stopping_live_feed" in monitor_text:
        raise RuntimeError("DMR polling gate test already exists unexpectedly")
    monitor_tests.write_text(monitor_text.rstrip() + polling_test + "\n", encoding="utf-8")
    print(f"PATCHED   {monitor_tests}")

    replace_once(
        runtime_tests,
        """    runtime.start()
    _wait_until(
        lambda: runtime.latest_monitor_state.health is DmrMonitorHealth.HEALTHY
    )
""",
        """    runtime.set_polling_enabled(False)
    assert not runtime.polling_enabled
    runtime.start()
    sleep(0.05)
    assert runtime.latest_monitor_state.live_available
    assert not runtime.latest_monitor_state.history_available
    assert not runtime.latest_monitor_state.radio_available

    runtime.set_polling_enabled(True)
    assert runtime.polling_enabled
    _wait_until(
        lambda: runtime.latest_monitor_state.health is DmrMonitorHealth.HEALTHY
    )
""",
    )

    # Add static lifecycle expectations to the existing wiring smoke test.
    wiring_text = wiring_tests.read_text(encoding="utf-8")
    required_marker = '        "set_dmr_expanded_layout(",\n'
    if required_marker not in wiring_text:
        raise RuntimeError("Expected DMR expanded-layout wiring marker was not found")
    wiring_text = wiring_text.replace(
        required_marker,
        required_marker
        + '        "dmr_panel_runtime.set_polling_enabled(False)",\n'
        + '        "dmr_panel_runtime.set_polling_enabled(",\n',
        1,
    )
    wiring_tests.write_text(wiring_text, encoding="utf-8")
    print(f"PATCHED   {wiring_tests}")

    print("PASS: Checkpoint 192 panel-scoped polling and twenty-row patch applied.")


if __name__ == "__main__":
    main()
