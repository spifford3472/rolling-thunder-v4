"""Tests for deterministic live-only MeshCore map notifications."""

import pytest

from rolling_thunder.meshcore_messages import (
    MeshCoreMessageOverlayService,
    bounded_message_lines,
)


class ManualClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


@pytest.mark.parametrize("channel", ["#hamradio", "#skywarn", "#traffic"])
def test_configured_channel_publishes_separate_header_and_message(channel: str) -> None:
    service = MeshCoreMessageOverlayService(
        ("#hamradio", "#skywarn", "#traffic"),
        clock=ManualClock(),
    )

    assert service.publish(channel, "  Useful human-readable text  ") is True

    state = service.latest_state
    assert state is not None
    assert state.channel == channel
    assert state.message == "Useful human-readable text"


def test_unconfigured_or_historical_message_does_not_publish() -> None:
    service = MeshCoreMessageOverlayService(("#skywarn",), clock=ManualClock())

    assert service.publish("#other", "not configured") is False
    assert service.publish("#skywarn", "stored message", historical=True) is False
    assert service.latest_state is None


def test_notification_expires_after_configured_twenty_seconds() -> None:
    clock = ManualClock()
    service = MeshCoreMessageOverlayService(
        ("#traffic",),
        display_seconds=20.0,
        clock=clock,
    )
    service.publish("#traffic", "Road closed")

    clock.now = 119.999
    assert service.latest_state is not None

    clock.now = 120.0
    assert service.latest_state is None


def test_newer_message_replaces_previous_and_restarts_duration() -> None:
    clock = ManualClock()
    service = MeshCoreMessageOverlayService(
        ("#hamradio", "#traffic"),
        display_seconds=20.0,
        clock=clock,
    )
    service.publish("#hamradio", "First")
    first = service.latest_state
    assert first is not None

    clock.now = 115.0
    service.publish("#traffic", "Second")
    second = service.latest_state
    assert second is not None
    assert second.channel == "#traffic"
    assert second.message == "Second"
    assert second.sequence == first.sequence + 1
    assert second.expires_at == 135.0

    clock.now = 120.0
    assert service.latest_state == second


def test_long_message_is_bounded_to_overlay_line_count() -> None:
    lines = bounded_message_lines(
        "A very long MeshCore message " * 20,
        width=24,
        maximum_lines=5,
    )

    assert len(lines) == 5
    assert all(len(line) <= 24 for line in lines)
    assert lines[-1].endswith("…")


def test_unbroken_text_wraps_without_damaging_layout() -> None:
    lines = bounded_message_lines("X" * 200, width=20, maximum_lines=5)

    assert len(lines) == 5
    assert all(len(line) <= 20 for line in lines)
