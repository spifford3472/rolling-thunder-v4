#!/usr/bin/env python3
"""Apply the tracked Checkpoint 192 DMR dashboard integration edits exactly once."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(relative: str, old: str, new: str) -> None:
    path = ROOT / relative
    text = path.read_text(encoding="utf-8")
    if new in text:
        print(f"UNCHANGED {relative} (already patched)")
        return
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"FAIL: expected exactly one integration anchor in {relative}; found {count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print(f"PATCHED   {relative}")


def write_file(relative: str, content: str) -> None:
    path = ROOT / relative
    previous = path.read_text(encoding="utf-8") if path.exists() else None
    if previous == content:
        print(f"UNCHANGED {relative}")
        return
    path.write_text(content, encoding="utf-8")
    print(f"WROTE     {relative}")


def main() -> None:
    replace_once(
        "src/rolling_thunder/config.py",
        "from rolling_thunder.map_sources import (\n",
        "from rolling_thunder.dmr_dashboard_config import DmrHotspotConfig\n"
        "from rolling_thunder.map_sources import (\n",
    )
    replace_once(
        "src/rolling_thunder/config.py",
        "    network_keepalive: NetworkKeepaliveConfig = NetworkKeepaliveConfig()\n"
        "    pota_spots: PotaSpotsConfig = PotaSpotsConfig()\n",
        "    network_keepalive: NetworkKeepaliveConfig = NetworkKeepaliveConfig()\n"
        "    dmr: DmrHotspotConfig = DmrHotspotConfig()\n"
        "    pota_spots: PotaSpotsConfig = PotaSpotsConfig()\n",
    )
    replace_once(
        "src/rolling_thunder/config.py",
        "def resolve_speech_model_path(\n"
        "    config: ApplicationConfig,\n"
        "    config_path: Path,\n"
        ") -> Path | None:\n",
        "def resolve_dmr_private_key(\n"
        "    config: ApplicationConfig,\n"
        "    config_path: Path,\n"
        ") -> Path | None:\n"
        "    \"\"\"Resolve the optional restricted DMR SSH key path.\"\"\"\n"
        "    private_key = config.dmr.private_key\n"
        "    if private_key is None:\n"
        "        return None\n"
        "    expanded = private_key.expanduser()\n"
        "    if expanded.is_absolute():\n"
        "        return expanded\n"
        "    return (config_path.parent / expanded).resolve()\n\n\n"
        "def resolve_speech_model_path(\n"
        "    config: ApplicationConfig,\n"
        "    config_path: Path,\n"
        ") -> Path | None:\n",
    )
    replace_once(
        "src/rolling_thunder/config.py",
        "    resolved_speech = config.speech.model_copy(\n"
        "        update={\"model_path\": resolve_speech_model_path(config, path)}\n"
        "    )\n"
        "    resolved_map = config.map.model_copy(\n",
        "    resolved_speech = config.speech.model_copy(\n"
        "        update={\"model_path\": resolve_speech_model_path(config, path)}\n"
        "    )\n"
        "    resolved_dmr = config.dmr.model_copy(\n"
        "        update={\"private_key\": resolve_dmr_private_key(config, path)}\n"
        "    )\n"
        "    resolved_map = config.map.model_copy(\n",
    )
    replace_once(
        "src/rolling_thunder/config.py",
        "            \"storage\": resolved_storage,\n"
        "            \"speech\": resolved_speech,\n"
        "            \"map\": resolved_map,\n",
        "            \"storage\": resolved_storage,\n"
        "            \"speech\": resolved_speech,\n"
        "            \"dmr\": resolved_dmr,\n"
        "            \"map\": resolved_map,\n",
    )

    replace_once(
        "config/rolling-thunder.example.yaml",
        "network_keepalive:\n"
        "  enabled: false\n"
        "  target_url: null\n"
        "  interval_s: 30.0\n"
        "  timeout_s: 5.0\n\n"
        "# QRZ credentials are never stored in YAML. See docs/POTA_ENRICHMENT.md.\n",
        "network_keepalive:\n"
        "  enabled: false\n"
        "  target_url: null\n"
        "  interval_s: 30.0\n"
        "  timeout_s: 5.0\n\n"
        "dmr:\n"
        "  # Read-only WPSD/MMDVM monitoring. The restricted SSH key can only run\n"
        "  # the rollingthunder-dmr-feed forced command on the hotspot.\n"
        "  enabled: false\n"
        "  host: null\n"
        "  ssh_user: pi-star\n"
        "  private_key: null\n"
        "  http_timeout_s: 5.0\n"
        "  connect_timeout_s: 5\n"
        "  history_limit: 20\n"
        "  history_refresh_interval_s: 2.0\n"
        "  reconnect_delay_s: 2.0\n\n"
        "# QRZ credentials are never stored in YAML. See docs/POTA_ENRICHMENT.md.\n",
    )

    replace_once(
        "src/rolling_thunder/ui_main.py",
        "from rolling_thunder.dashboard_state import build_dashboard_state\n",
        "from rolling_thunder.dashboard_state import build_dashboard_state\n"
        "from rolling_thunder.dmr_active_panel_commands import DmrAwareActivePanelCommands\n"
        "from rolling_thunder.dmr_dashboard_runtime import build_dmr_panel_runtime\n"
        "from rolling_thunder.dmr_panel_runtime import DmrCommitEventKind\n"
        "from rolling_thunder.dmr_ui import build_dmr_viewport\n"
        "from rolling_thunder.dmr_widgets import DmrWidgets\n",
    )
    replace_once(
        "src/rolling_thunder/ui_main.py",
        "    active_panel_commands = LogAwareActivePanelCommands(\n"
        "        context_navigation,\n"
        "        base_active_panel_commands,\n"
        "        log_panel,\n"
        "    )\n"
        "    _ = pota_tune_executor\n",
        "    log_aware_active_panel_commands = LogAwareActivePanelCommands(\n"
        "        context_navigation,\n"
        "        base_active_panel_commands,\n"
        "        log_panel,\n"
        "    )\n"
        "    try:\n"
        "        dmr_panel_runtime = build_dmr_panel_runtime(\n"
        "            config.dmr,\n"
        "            database_path=config.storage.database_path,\n"
        "            gps_state_provider=lambda: runtime.latest_gps_state,\n"
        "        )\n"
        "        if dmr_panel_runtime is not None:\n"
        "            dmr_panel_runtime.start()\n"
        "    except (RuntimeError, ValueError) as error:\n"
        "        print(f\"Rolling Thunder DMR startup error: {error}\")\n"
        "        log_panel.stop()\n"
        "        runtime.stop()\n"
        "        return 3\n"
        "    active_panel_commands: (\n"
        "        LogAwareActivePanelCommands | DmrAwareActivePanelCommands\n"
        "    )\n"
        "    if dmr_panel_runtime is None:\n"
        "        active_panel_commands = log_aware_active_panel_commands\n"
        "    else:\n"
        "        active_panel_commands = DmrAwareActivePanelCommands(\n"
        "            context_navigation,\n"
        "            log_aware_active_panel_commands,\n"
        "            dmr_panel_runtime.commands,\n"
        "        )\n"
        "    _ = pota_tune_executor\n",
    )
    replace_once(
        "src/rolling_thunder/ui_main.py",
        "    repeater_widgets = RepeaterWidgets(context_content)\n"
        "    log_widgets = LogWidgets(context_content)\n",
        "    repeater_widgets = RepeaterWidgets(context_content)\n"
        "    log_widgets = LogWidgets(context_content)\n"
        "    dmr_widgets = DmrWidgets(context_content)\n",
    )

    old_show_helpers = '''    def show_standard_context_body() -> None:\n        \"\"\"Show the reusable text body and hide specialized context viewports.\"\"\"\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        context_body_label.grid()\n\n    def show_pota_context_body() -> None:\n        \"\"\"Show the POTA/DX card viewport and hide other context bodies.\"\"\"\n        context_body_label.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        pota_panel_frame.grid()\n\n    def show_repeater_context_body() -> None:\n        \"\"\"Show local repeaters and hide the generic/POTA/settings/weather bodies.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        repeater_widgets.show()\n\n    def show_settings_context_body() -> None:\n        \"\"\"Show Settings controls and hide the generic/POTA/repeater/weather bodies.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        settings_widgets.show()\n\n    def show_weather_context_body() -> None:\n        \"\"\"Show retained weather and hide other context bodies.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        log_widgets.hide()\n        weather_widgets.show()\n\n    def show_log_context_body() -> None:\n        \"\"\"Show the local Log snapshot and hide every unrelated context body.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.show()\n'''
    new_show_helpers = '''    def show_standard_context_body() -> None:\n        \"\"\"Show the reusable text body and hide specialized context viewports.\"\"\"\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        dmr_widgets.hide()\n        context_body_label.grid()\n\n    def show_pota_context_body() -> None:\n        \"\"\"Show the POTA/DX card viewport and hide other context bodies.\"\"\"\n        context_body_label.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        dmr_widgets.hide()\n        pota_panel_frame.grid()\n\n    def show_repeater_context_body() -> None:\n        \"\"\"Show local repeaters and hide the generic/POTA/settings/weather bodies.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        dmr_widgets.hide()\n        repeater_widgets.show()\n\n    def show_settings_context_body() -> None:\n        \"\"\"Show Settings controls and hide the generic/POTA/repeater/weather bodies.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        dmr_widgets.hide()\n        settings_widgets.show()\n\n    def show_weather_context_body() -> None:\n        \"\"\"Show retained weather and hide other context bodies.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        log_widgets.hide()\n        dmr_widgets.hide()\n        weather_widgets.show()\n\n    def show_log_context_body() -> None:\n        \"\"\"Show the local Log snapshot and hide every unrelated context body.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        dmr_widgets.hide()\n        log_widgets.show()\n\n    def show_dmr_context_body() -> None:\n        \"\"\"Show DMR activity and hide every unrelated context body.\"\"\"\n        context_body_label.grid_remove()\n        pota_panel_frame.grid_remove()\n        repeater_widgets.hide()\n        settings_widgets.hide()\n        weather_widgets.hide()\n        log_widgets.hide()\n        dmr_widgets.show()\n'''
    replace_once("src/rolling_thunder/ui_main.py", old_show_helpers, new_show_helpers)

    replace_once(
        "src/rolling_thunder/ui_main.py",
        "        repeater_persistence_status = (\n"
        "            repeater_panel_runtime.synchronize_completed_persistence()\n"
        "        )\n\n"
        "        weather_presentation = weather_panel.update(\n",
        "        repeater_persistence_status = (\n"
        "            repeater_panel_runtime.synchronize_completed_persistence()\n"
        "        )\n"
        "        if dmr_panel_runtime is not None:\n"
        "            for dmr_event in dmr_panel_runtime.synchronize_commit_events():\n"
        "                if dmr_event.kind is DmrCommitEventKind.SUCCEEDED:\n"
        "                    log_panel.request_sync()\n\n"
        "        weather_presentation = weather_panel.update(\n",
    )
    replace_once(
        "src/rolling_thunder/ui_main.py",
        "        elif selected_context.selected is ContextId.SETTINGS:\n"
        "            show_settings_context_body()\n",
        "        elif selected_context.selected is ContextId.DMR:\n"
        "            health_frame.grid_remove()\n"
        "            context_title_text.set(selected_context.definition.title)\n"
        "            context_title_label.configure(font=(\"DejaVu Sans\", 40, \"bold\"))\n"
        "            if dmr_panel_runtime is None:\n"
        "                show_standard_context_body()\n"
        "                context_body_text.set(\n"
        "                    \"DMR hotspot monitoring is disabled in configuration.\"\n"
        "                )\n"
        "            else:\n"
        "                show_dmr_context_body()\n"
        "                dmr_selection = dmr_panel_runtime.commands.refresh()\n"
        "                dmr_widgets.update(\n"
        "                    build_dmr_viewport(\n"
        "                        dmr_panel_runtime.latest_monitor_state,\n"
        "                        dmr_selection,\n"
        "                        dmr_panel_runtime.commit.status,\n"
        "                    )\n"
        "                )\n"
        "        elif selected_context.selected is ContextId.SETTINGS:\n"
        "            show_settings_context_body()\n",
    )
    replace_once(
        "src/rolling_thunder/ui_main.py",
        "        log_panel.stop()\n"
        "        runtime.stop()\n"
        "        root.destroy()\n",
        "        if dmr_panel_runtime is not None:\n"
        "            dmr_panel_runtime.stop()\n"
        "        log_panel.stop()\n"
        "        runtime.stop()\n"
        "        root.destroy()\n",
    )

    write_file(
        "tests/test_dmr_dashboard_wiring.py",
        '''"""Tests for DMR deployment configuration and dashboard composition wiring."""\n\nfrom datetime import UTC, datetime\nfrom pathlib import Path\n\nimport pytest\nfrom pydantic import ValidationError\n\nfrom rolling_thunder.config import ApplicationConfig, OperatorConfig, load_config\nfrom rolling_thunder.dmr_dashboard_config import DmrHotspotConfig\nfrom rolling_thunder.dmr_dashboard_runtime import (\n    build_dmr_panel_runtime,\n    dmr_grid_from_gps_state,\n)\nfrom rolling_thunder.domain import GPSFixState, GPSPosition\nfrom rolling_thunder.gps import GPSConnectionState, GPSState\nfrom rolling_thunder.maidenhead import maidenhead_grid\n\nNOW = datetime(2026, 8, 16, 4, 30, tzinfo=UTC)\n\n\ndef test_dmr_config_defaults_disabled() -> None:\n    config = ApplicationConfig(\n        operator=OperatorConfig(callsign="KI5VNB", home_grid="EM79xm")\n    )\n\n    assert config.dmr.enabled is False\n    assert config.dmr.host is None\n    assert config.dmr.private_key is None\n    assert config.dmr.history_limit == 20\n\n\ndef test_enabled_dmr_requires_host_and_private_key() -> None:\n    with pytest.raises(ValidationError):\n        DmrHotspotConfig(enabled=True)\n\n\ndef test_load_config_resolves_relative_dmr_key(tmp_path: Path) -> None:\n    path = tmp_path / "rolling-thunder.yaml"\n    path.write_text(\n        """\noperator:\n  callsign: KI5VNB\n  home_grid: EM79xm\ndmr:\n  enabled: true\n  host: 192.168.8.235\n  ssh_user: pi-star\n  private_key: keys/id_ed25519_rollingthunder_dmr\n""",\n        encoding="utf-8",\n    )\n\n    config = load_config(path)\n\n    assert config.dmr.enabled\n    assert config.dmr.host == "192.168.8.235"\n    assert config.dmr.private_key == (\n        tmp_path / "keys/id_ed25519_rollingthunder_dmr"\n    ).resolve()\n\n\ndef test_grid_provider_uses_only_connected_position_fix() -> None:\n    position = GPSPosition(\n        fix_state=GPSFixState.THREE_DIMENSIONAL,\n        latitude=39.75,\n        longitude=-84.20,\n        updated_at=NOW,\n    )\n    state = GPSState(\n        connection_state=GPSConnectionState.CONNECTED,\n        position=position,\n        updated_at=NOW,\n    )\n\n    assert dmr_grid_from_gps_state(state) == maidenhead_grid(39.75, -84.20)\n    assert dmr_grid_from_gps_state(None) is None\n\n\ndef test_disabled_dmr_builds_no_runtime(tmp_path: Path) -> None:\n    runtime = build_dmr_panel_runtime(\n        DmrHotspotConfig(),\n        database_path=tmp_path / "contacts.db",\n        gps_state_provider=lambda: None,\n    )\n\n    assert runtime is None\n\n\ndef test_ui_main_contains_complete_dmr_lifecycle_wiring() -> None:\n    source = Path("src/rolling_thunder/ui_main.py").read_text(encoding="utf-8")\n\n    for required in (\n        "build_dmr_panel_runtime(",\n        "dmr_panel_runtime.start()",\n        "DmrAwareActivePanelCommands(",\n        "DmrWidgets(context_content)",\n        "dmr_panel_runtime.synchronize_commit_events()",\n        "build_dmr_viewport(",\n        "dmr_panel_runtime.stop()",\n    ):\n        assert required in source\n''',
    )
    print("PASS: Checkpoint 192 DMR dashboard integration patch applied.")


if __name__ == "__main__":
    main()
