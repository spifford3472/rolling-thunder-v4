"""Tests for transport-independent physical-control primitives."""

import pytest

from rolling_thunder.physical_controls import (
    ControlAction,
    ControlActionMapper,
    ControlInputEvent,
    ControlMappingError,
    MockControlSource,
)


def event(input_id: str, event_id: str, occurred_at_s: float = 1.0) -> ControlInputEvent:
    """Build one concise test event."""
    return ControlInputEvent(
        input_id=input_id,
        event_id=event_id,
        occurred_at_s=occurred_at_s,
    )


def test_control_actions_exclude_radio_and_tuning_authority() -> None:
    """The first physical-control slice must expose only approved actions."""
    assert set(ControlAction) == {
        ControlAction.VOICE,
        ControlAction.COMMIT,
        ControlAction.DISCARD,
        ControlAction.SELECT_POTA,
        ControlAction.SELECT_DX,
        ControlAction.SELECT_REPEATERS,
        ControlAction.SELECT_AI,
        ControlAction.SELECT_SETTINGS,
    }


def test_input_event_rejects_blank_identifiers_and_negative_time() -> None:
    """Malformed transport events should fail before application dispatch."""
    with pytest.raises(ValueError, match="input_id"):
        event(" ", "event-1")
    with pytest.raises(ValueError, match="event_id"):
        event("voice-button", " ")
    with pytest.raises(ValueError, match="occurred_at_s"):
        event("voice-button", "event-1", occurred_at_s=-0.1)


def test_mapper_resolves_configured_input_to_typed_action() -> None:
    """Opaque hardware identifiers should resolve through configuration."""
    mapper = ControlActionMapper(
        {
            "voice-button": ControlAction.VOICE,
            "context-pota": ControlAction.SELECT_POTA,
        }
    )

    assert mapper.resolve(event("voice-button", "event-1")) is ControlAction.VOICE
    assert (
        mapper.resolve(event("context-pota", "event-2"))
        is ControlAction.SELECT_POTA
    )


def test_mapper_returns_none_for_unknown_input() -> None:
    """Unknown controls must not guess or fall back to another action."""
    mapper = ControlActionMapper({"commit-button": ControlAction.COMMIT})

    assert mapper.resolve(event("unknown-button", "event-1")) is None


def test_mapper_rejects_blank_and_normalized_duplicate_input_ids() -> None:
    """Ambiguous configuration should be rejected deterministically."""
    with pytest.raises(ControlMappingError, match="must not be blank"):
        ControlActionMapper({" ": ControlAction.DISCARD})

    with pytest.raises(ControlMappingError, match="Duplicate"):
        ControlActionMapper(
            {
                "voice-button": ControlAction.VOICE,
                " voice-button ": ControlAction.COMMIT,
            }
        )


def test_mock_source_is_inert_until_explicitly_stimulated() -> None:
    """Development controls must never create unattended actions."""
    source = MockControlSource()

    assert source.drain() == ()


def test_mock_source_drains_explicit_events_once_in_fifo_order() -> None:
    """Mock behavior should be deterministic and nonblocking."""
    first = event("voice-button", "event-1", occurred_at_s=1.0)
    second = event("discard-button", "event-2", occurred_at_s=2.0)
    source = MockControlSource((first,))
    source.emit(second)

    assert source.drain() == (first, second)
    assert source.drain() == ()
