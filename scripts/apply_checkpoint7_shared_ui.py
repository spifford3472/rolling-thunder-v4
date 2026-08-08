"""Apply the checkpoint-7 shared POTA/DX dashboard migration deterministically.

This helper exists only to make the large ui_main.py edit reviewable and guarded.
It is intended to be run once from the repository root and then removed before
checkpoint 7 is merged.
"""

from __future__ import annotations

from pathlib import Path

UI_PATH = Path("src/rolling_thunder/ui_main.py")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_between(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    *,
    label: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: start marker not found")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: end marker not found")
    return text[:start] + replacement + text[end:]


def main() -> None:
    text = UI_PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        "from rolling_thunder.active_panel_commands import ActivePanelCommandController\n",
        "from rolling_thunder.active_panel_commands import (\n"
        "    SharedSpotActivePanelCommandController,\n"
        ")\n",
        label="active-panel import",
    )

    legacy_imports = (
        "from rolling_thunder.pota_dashboard_controller import PotaDashboardController\n"
        "from rolling_thunder.pota_dashboard_filters import PotaDashboardFilterController\n"
        "from rolling_thunder.pota_dashboard_panel import build_pota_dashboard_panel\n"
        "from rolling_thunder.pota_enrichment_ui import format_enriched_callsign\n"
    )
    shared_imports = (
        "from rolling_thunder.shared_pota_contact import shared_pota_spots_for_contact\n"
        "from rolling_thunder.shared_spot_panel import SharedSpotPanelController\n"
        "from rolling_thunder.shared_spot_ui import build_shared_spot_viewport\n"
    )
    text = replace_once(
        text,
        legacy_imports,
        shared_imports,
        label="shared spot imports",
    )
    text = replace_once(
        text,
        "from rolling_thunder.pota_tune_ui_controller import PotaTuneUiController\n",
        "",
        label="legacy tune UI import",
    )

    old_controller = '''    context_navigation = ContextNavigationController()\n    pota_dashboard = PotaDashboardController(runtime)\n    pota_filters = PotaDashboardFilterController(pota_dashboard)\n    pota_tune_ui = PotaTuneUiController(\n        pota_dashboard,\n        pota_tune_executor or runtime.pota_receive_tune_executor,\n        status_messages=runtime.status_messages,\n    )\n    active_panel_commands = ActivePanelCommandController(\n        context_navigation,\n        pota_dashboard,\n        pota_filters,\n        pota_tune_ui,\n    )\n'''
    new_controller = '''    context_navigation = ContextNavigationController()\n    shared_spot_panel = SharedSpotPanelController(runtime)\n    active_panel_commands = SharedSpotActivePanelCommandController(\n        context_navigation,\n        shared_spot_panel,\n        current_frequency=lambda: runtime.latest_radio_state.frequency,\n    )\n    # Kept only for run_dashboard API compatibility during checkpoint 7.\n    # Shared receive tuning is intentionally deferred to checkpoint 8.\n    _ = pota_tune_executor\n'''
    text = replace_once(
        text,
        old_controller,
        new_controller,
        label="shared panel composition",
    )

    text = replace_once(
        text,
        "        pota_spots_provider=lambda: pota_dashboard.visible_spots,\n",
        "        pota_spots_provider=lambda: shared_pota_spots_for_contact(\n"
        "            shared_spot_panel.visible_spots\n"
        "        ),\n",
        label="contact POTA provider",
    )

    text = replace_once(
        text,
        "    previous_context: ContextId | None = None\n\n",
        "",
        label="legacy previous-context state",
    )
    text = replace_once(
        text,
        "    def refresh() -> None:\n        nonlocal previous_context\n\n",
        "    def refresh() -> None:\n",
        label="refresh nonlocal",
    )

    old_context_start = "        selected_context = context_navigation.state\n"
    old_settings_marker = "        elif selected_context.selected is ContextId.SETTINGS:\n"
    new_shared_context = '''        selected_context = context_navigation.state\n\n        if selected_context.selected in {ContextId.POTA, ContextId.DX}:\n            health_frame.grid_remove()\n            show_pota_context_body()\n            panel_state = shared_spot_panel.state\n            panel = build_shared_spot_viewport(panel_state)\n            context_title_text.set(panel.title)\n            context_title_label.configure(\n                font=("DejaVu Sans", _POTA_HEADER_FONT_SIZE, "bold")\n            )\n\n            available_wrap_width = max(480, pota_panel_frame.winfo_width() - 36)\n            pota_status_label.configure(wraplength=available_wrap_width)\n            pota_footer_label.configure(wraplength=available_wrap_width)\n            for labels in pota_card_labels:\n                labels[0].configure(wraplength=available_wrap_width)\n                labels[2].configure(wraplength=available_wrap_width)\n\n            if not panel.has_cards:\n                pota_cards_container.grid_remove()\n                pota_status_label.grid()\n                status_lines = [panel.detail_line, panel.status_line]\n                if panel.error_line:\n                    status_lines.append(f"ERROR: {panel.error_line}")\n                pota_status_text.set("\\n".join(status_lines))\n                pota_more_above_text.set("")\n                pota_more_below_text.set("")\n                for card_frame in pota_card_frames:\n                    card_frame.grid_remove()\n            else:\n                pota_status_label.grid_remove()\n                pota_cards_container.grid()\n                pota_more_above_text.set(\n                    "▲ MORE ▲" if panel.hidden_above_count else ""\n                )\n                pota_more_below_text.set(\n                    "▼ MORE ▼" if panel.hidden_below_count else ""\n                )\n\n                for card_index, card_frame in enumerate(pota_card_frames):\n                    if card_index >= len(panel.cards):\n                        card_frame.grid_remove()\n                        continue\n\n                    card = panel.cards[card_index]\n                    card_frame.grid()\n                    line1_var, line2_var, line3_var, line4_var = pota_card_texts[\n                        card_index\n                    ]\n                    line1_var.set(card.line1)\n                    line2_var.set(card.line2)\n                    line3_var.set(card.line3)\n                    line4_var.set(card.line4)\n\n                    selected_background = (\n                        _CONTEXT_SELECTED if card.selected else _PANEL_BACKGROUND\n                    )\n                    visible_border_width = (\n                        _POTA_CARD_SELECTED_BORDER_PX\n                        if card.selected\n                        else _POTA_CARD_NORMAL_BORDER_PX\n                    )\n                    invisible_border_width = (\n                        _POTA_CARD_OUTER_PAD_PX - visible_border_width\n                    )\n                    border_color = _BRIGHT if card.selected else _BORDER\n                    card_frame.configure(\n                        bg=selected_background,\n                        highlightbackground=border_color,\n                        highlightcolor=border_color,\n                        highlightthickness=visible_border_width,\n                        padx=invisible_border_width,\n                        pady=invisible_border_width,\n                    )\n                    for card_label in pota_card_labels[card_index]:\n                        card_label.configure(bg=selected_background)\n\n            footer_lines = [panel.status_line]\n            if panel.error_line:\n                footer_lines.append(panel.error_line)\n            if panel_state.staged_identity is not None:\n                footer_lines.append(\n                    "STAGED — BACK CANCELS — RECEIVE TUNING ENABLED IN CHECKPOINT 8"\n                )\n            else:\n                footer_lines.append("SELECT A SPOT — ACTIVATE STAGES ONLY")\n            pota_footer_text.set("\\n".join(footer_lines))\n'''
    text = replace_between(
        text,
        old_context_start,
        old_settings_marker,
        new_shared_context,
        label="shared POTA/DX refresh branch",
    )

    key_start = "    def handle_pota_filter_key(event: tk.Event[tk.Misc]) -> None:\n"
    key_end = "    context_shortcut_actions = {\n"
    new_keys = '''    def execute_panel_action(action: ControlAction) -> None:\n        operator_commands.execute(action)\n\n    root.bind(\n        "<Up>",\n        lambda _event: execute_panel_action(ControlAction.MOVE_PREVIOUS),\n    )\n    root.bind(\n        "<Down>",\n        lambda _event: execute_panel_action(ControlAction.MOVE_NEXT),\n    )\n    root.bind(\n        "<Return>",\n        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),\n    )\n    root.bind(\n        "<KP_Enter>",\n        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),\n    )\n    root.bind(\n        "<t>",\n        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),\n    )\n    root.bind(\n        "<T>",\n        lambda _event: execute_panel_action(ControlAction.ACTIVATE_SELECTION),\n    )\n    root.bind(\n        "<x>",\n        lambda _event: execute_panel_action(ControlAction.BACK),\n    )\n    root.bind(\n        "<X>",\n        lambda _event: execute_panel_action(ControlAction.BACK),\n    )\n    root.bind(\n        "]",\n        lambda _event: execute_panel_action(ControlAction.PANEL_PRIMARY),\n    )\n    root.bind(\n        ".",\n        lambda _event: execute_panel_action(ControlAction.PANEL_SECONDARY),\n    )\n\n'''
    text = replace_between(
        text,
        key_start,
        key_end,
        new_keys,
        label="shared keyboard routing",
    )

    forbidden = (
        "PotaDashboardController(",
        "PotaDashboardFilterController(",
        "PotaTuneUiController(",
        "build_pota_dashboard_panel(",
        "format_enriched_callsign(",
        "pota_tune_ui.",
    )
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"legacy live-panel token remains after migration: {token}")

    required = (
        "SharedSpotPanelController(runtime)",
        "SharedSpotActivePanelCommandController(",
        "build_shared_spot_viewport(panel_state)",
        "shared_pota_spots_for_contact(",
        "ContextId.POTA, ContextId.DX",
    )
    for token in required:
        if token not in text:
            raise RuntimeError(f"required shared-panel token missing: {token}")

    UI_PATH.write_text(text, encoding="utf-8")
    print(f"PASS: migrated {UI_PATH} to the shared POTA/DX panel path")


if __name__ == "__main__":
    main()
