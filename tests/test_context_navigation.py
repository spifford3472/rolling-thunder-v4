"""Tests for persistent dashboard context selection."""

import pytest

from rolling_thunder.context_navigation import (
    CONTEXT_DEFINITIONS,
    ContextId,
    ContextNavigationController,
)


def test_defaults_to_pota_context() -> None:
    controller = ContextNavigationController()

    assert controller.state.selected is ContextId.POTA
    assert controller.state.definition.title == "POTA"


@pytest.mark.parametrize(
    ("shortcut", "expected"),
    [
        ("1", ContextId.POTA),
        ("2", ContextId.DX),
        ("b", ContextId.BROWSE),
        ("3", ContextId.REPEATERS),
        ("4", ContextId.AI),
        ("5", ContextId.SETTINGS),
        ("6", ContextId.WEATHER),
        ("7", ContextId.LOG),
        ("8", ContextId.DMR),
    ],
)
def test_selects_context_directly_by_shortcut(shortcut: str, expected: ContextId) -> None:
    controller = ContextNavigationController()

    changed = controller.select_shortcut(shortcut)

    assert changed is True
    assert controller.state.selected is expected


def test_unknown_shortcut_preserves_selection() -> None:
    controller = ContextNavigationController(ContextId.DX)

    changed = controller.select_shortcut("9")

    assert changed is False
    assert controller.state.selected is ContextId.DX


def test_context_selection_remains_until_explicitly_changed() -> None:
    controller = ContextNavigationController()
    controller.select(ContextId.SETTINGS)

    first_snapshot = controller.state
    second_snapshot = controller.state

    assert first_snapshot is second_snapshot
    assert second_snapshot.selected is ContextId.SETTINGS


def test_definitions_have_unique_ids_shortcuts_and_labels() -> None:
    ids = [definition.context_id for definition in CONTEXT_DEFINITIONS]
    shortcuts = [definition.shortcut for definition in CONTEXT_DEFINITIONS]
    labels = [definition.label for definition in CONTEXT_DEFINITIONS]

    assert len(ids) == len(set(ids))
    assert len(shortcuts) == len(set(shortcuts))
    assert len(labels) == len(set(labels))


def test_select_next_advances_through_contexts() -> None:
    controller = ContextNavigationController(ContextId.POTA)

    assert controller.select_next().selected is ContextId.DX
    assert controller.select_next().selected is ContextId.BROWSE
    assert controller.select_next().selected is ContextId.REPEATERS
    assert controller.select_next().selected is ContextId.AI
    assert controller.select_next().selected is ContextId.WEATHER
    assert controller.select_next().selected is ContextId.SETTINGS
    assert controller.select_next().selected is ContextId.LOG
    assert controller.select_next().selected is ContextId.DMR


def test_select_next_wraps_from_dmr_to_pota() -> None:
    controller = ContextNavigationController(ContextId.DMR)

    state = controller.select_next()

    assert state.selected is ContextId.POTA


def test_select_home_returns_to_pota() -> None:
    controller = ContextNavigationController(ContextId.AI)

    state = controller.select_home()

    assert state.selected is ContextId.POTA
