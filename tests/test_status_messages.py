from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from threading import Barrier

import pytest

from rolling_thunder.status_messages import (
    StatusMessage,
    StatusMessageService,
    StatusPresentation,
)


class FakeMonotonicClock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def test_highest_priority_message_wins() -> None:
    service = StatusMessageService(clock=lambda: 100.0)
    service.publish(replacement_key="routine", text="Routine", priority=10)
    service.publish(replacement_key="warning", text="Warning", priority=100)

    snapshot = service.snapshot()

    assert snapshot.current is not None
    assert snapshot.current.replacement_key == "warning"
    assert tuple(message.replacement_key for message in snapshot.active_messages) == (
        "warning",
        "routine",
    )


def test_equal_priority_newest_message_wins_deterministically() -> None:
    service = StatusMessageService(clock=lambda: 100.0)
    first = service.publish(replacement_key="first", text="First", priority=10)
    second = service.publish(replacement_key="second", text="Second", priority=10)

    snapshot = service.snapshot()

    assert second.sequence > first.sequence
    assert snapshot.current == second


def test_replacement_key_update_replaces_only_matching_message() -> None:
    service = StatusMessageService(clock=lambda: 100.0)
    routine = service.publish(
        replacement_key="routine",
        text="Routine",
        priority=10,
    )
    replaced = service.publish(
        replacement_key="source",
        text="Old source value",
        priority=20,
    )
    replacement = service.publish(
        replacement_key="source",
        text="New source value",
        priority=20,
    )

    snapshot = service.snapshot()

    assert replaced not in snapshot.active_messages
    assert replacement in snapshot.active_messages
    assert routine in snapshot.active_messages
    assert len(snapshot.active_messages) == 2


def test_clear_reveals_next_eligible_message() -> None:
    service = StatusMessageService(clock=lambda: 100.0)
    routine = service.publish(
        replacement_key="routine",
        text="Routine",
        priority=10,
    )
    service.publish(replacement_key="warning", text="Warning", priority=100)

    assert service.clear("warning") is True
    assert service.clear("warning") is False
    assert service.snapshot().current == routine


def test_expiration_uses_injected_monotonic_clock() -> None:
    clock = FakeMonotonicClock()
    service = StatusMessageService(clock=clock)
    published = service.publish(
        replacement_key="temporary",
        text="Temporary",
        duration_s=10.0,
    )

    assert published.expires_at_monotonic == 110.0
    clock.advance(9.999)
    assert service.snapshot().current == published

    clock.advance(0.001)
    assert service.snapshot().current is None


def test_lower_priority_message_resumes_after_warning_expires() -> None:
    clock = FakeMonotonicClock()
    service = StatusMessageService(clock=clock)
    routine = service.publish(
        replacement_key="routine",
        text="Routine",
        priority=10,
    )
    warning = service.publish(
        replacement_key="warning",
        text="Warning",
        presentation=StatusPresentation.AMBER,
        priority=100,
        duration_s=10.0,
    )

    assert service.snapshot().current == warning

    clock.advance(10.0)

    assert service.snapshot().current == routine


def test_snapshot_and_messages_are_immutable() -> None:
    service = StatusMessageService(clock=lambda: 100.0)
    service.publish(replacement_key="routine", text="Routine")
    snapshot = service.snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.current = None  # type: ignore[misc]

    assert snapshot.current is not None
    with pytest.raises(FrozenInstanceError):
        snapshot.current.text = "Changed"  # type: ignore[misc]


def test_concurrent_publish_and_read_is_thread_safe_without_sleeps() -> None:
    service = StatusMessageService(clock=lambda: 100.0)
    barrier = Barrier(9)

    def publish(index: int) -> None:
        barrier.wait()
        service.publish(
            replacement_key=f"publisher-{index}",
            text=f"Message {index}",
            priority=index,
        )

    def read_snapshots() -> tuple[StatusMessage | None, ...]:
        barrier.wait()
        return tuple(service.snapshot().current for _ in range(200))

    with ThreadPoolExecutor(max_workers=9) as executor:
        publishers = [executor.submit(publish, index) for index in range(8)]
        reader = executor.submit(read_snapshots)
        for publisher in publishers:
            publisher.result()
        observations = reader.result()

    assert all(
        observation is None or isinstance(observation, StatusMessage)
        for observation in observations
    )
    final_snapshot = service.snapshot()
    assert final_snapshot.current is not None
    assert final_snapshot.current.replacement_key == "publisher-7"
    assert len(final_snapshot.active_messages) == 8


@pytest.mark.parametrize(
    ("replacement_key", "text", "duration_s"),
    [
        ("", "Message", None),
        ("key", "", None),
        ("key", "Message", 0.0),
        ("key", "Message", -1.0),
    ],
)
def test_publish_rejects_invalid_messages(
    replacement_key: str,
    text: str,
    duration_s: float | None,
) -> None:
    service = StatusMessageService(clock=lambda: 100.0)

    with pytest.raises(ValueError):
        service.publish(
            replacement_key=replacement_key,
            text=text,
            duration_s=duration_s,
        )
