"""Tests for physical-control transport lifecycle helpers."""

from rolling_thunder.control_source_lifecycle import (
    close_control_source,
    open_control_source,
)
from rolling_thunder.physical_controls import ControlInputEvent, MockControlSource
from rolling_thunder.serial_control_source import SerialControlError


class FakeLifecycleSource:
    def __init__(self) -> None:
        self.opened = False
        self.closed = False
        self.open_error: str | None = None
        self.close_error: str | None = None

    def open(self) -> None:
        if self.open_error is not None:
            raise SerialControlError(self.open_error)
        self.opened = True

    def close(self) -> None:
        if self.close_error is not None:
            raise SerialControlError(self.close_error)
        self.closed = True

    def drain(self) -> tuple[ControlInputEvent, ...]:
        return ()


def test_mock_source_requires_no_lifecycle_work() -> None:
    source = MockControlSource()

    assert open_control_source(source) is None
    assert close_control_source(source) is None


def test_lifecycle_source_opens_and_closes() -> None:
    source = FakeLifecycleSource()

    assert open_control_source(source) is None
    assert close_control_source(source) is None
    assert source.opened is True
    assert source.closed is True


def test_open_error_is_returned_without_raising() -> None:
    source = FakeLifecycleSource()
    source.open_error = "permission denied"

    assert open_control_source(source) == "permission denied"


def test_close_error_is_returned_without_raising() -> None:
    source = FakeLifecycleSource()
    source.close_error = "device vanished"

    assert close_control_source(source) == "device vanished"


def test_none_close_is_safe() -> None:
    assert close_control_source(None) is None
