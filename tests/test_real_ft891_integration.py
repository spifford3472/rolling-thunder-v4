"""Integration-boundary tests for configured real FT-891 composition."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig, HardwareConfig
from rolling_thunder.domain import (
    Frequency,
    RadioConnectionState,
    RadioMode,
    RadioState,
)
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.radio import Radio, RadioBand, RadioConnectionError
from rolling_thunder.radio_polling import PollCallback

_CAT_DEVICE = Path(
    "/dev/serial/by-id/"
    "usb-Silicon_Labs_CP2105_Dual_USB_to_UART_Bridge_Controller_011F42E9-"
    "if00-port0"
)


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class ManualScheduler:
    def __init__(self) -> None:
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        assert interval_s == 1.0
        self.poll = ManualScheduledPoll(callback)
        return self.poll


class FakePhysicalRadio:
    def __init__(self, *, connect_error: RadioConnectionError | None = None) -> None:
        self.connect_error = connect_error
        self.connect_count = 0
        self.state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            transmitting=False,
            updated_at=timestamp(),
        )

    def connect(self) -> RadioState:
        self.connect_count += 1
        if self.connect_error is not None:
            self.state = RadioState(
                connection_state=RadioConnectionState.ERROR,
                transmitting=False,
                updated_at=timestamp(),
                last_error=str(self.connect_error),
            )
            raise self.connect_error
        self.state = RadioState(
            connection_state=RadioConnectionState.CONNECTED,
            frequency=Frequency(hz=7_273_020),
            mode=RadioMode.LSB,
            transmitting=False,
            updated_at=timestamp(),
        )
        return self.state

    def disconnect(self) -> RadioState:
        self.state = RadioState(
            connection_state=RadioConnectionState.DISCONNECTED,
            transmitting=False,
            updated_at=timestamp(),
        )
        return self.state

    def get_state(self) -> RadioState:
        return self.state

    def refresh_state(self) -> RadioState:
        return self.state

    def set_frequency(self, frequency: Frequency) -> RadioState:
        self.state = self.state.model_copy(update={"frequency": frequency})
        return self.state

    def set_mode(self, mode: RadioMode) -> RadioState:
        self.state = self.state.model_copy(update={"mode": mode})
        return self.state

    def select_band(self, band: RadioBand) -> RadioState:
        del band
        return self.state


def timestamp() -> datetime:
    return datetime(2026, 8, 2, 17, 15, tzinfo=UTC)


def real_radio_config(tmp_path: Path) -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {
                "mock": True,
                "radio_mode": "real",
                "gps_mode": "mock",
                "radio_device": str(_CAT_DEVICE),
                "radio_baud_rate": 38_400,
                "radio_timeout_s": 1.75,
            },
            "storage": {"database_path": str(tmp_path / "rolling-thunder.db")},
        }
    )


def test_hardware_config_defaults_to_verified_ft891_serial_settings() -> None:
    config = HardwareConfig()

    assert config.radio_baud_rate == 38_400
    assert config.radio_timeout_s == 1.0


@pytest.mark.parametrize(
    ("field", "value"),
    [("radio_baud_rate", 0), ("radio_timeout_s", 0.0)],
)
def test_hardware_config_rejects_invalid_ft891_serial_settings(
    field: str,
    value: float,
) -> None:
    with pytest.raises(ValidationError):
        HardwareConfig.model_validate({field: value})


def test_real_radio_factory_receives_configured_cat_settings(tmp_path: Path) -> None:
    received: list[tuple[Path, int, float]] = []
    radio = FakePhysicalRadio()

    def radio_factory(
        device: Path,
        *,
        baud_rate: int,
        timeout_s: float,
    ) -> Radio:
        received.append((device, baud_rate, timeout_s))
        return radio

    runtime = ApplicationRuntime.from_config(
        real_radio_config(tmp_path),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        radio_factory=radio_factory,
    )

    assert runtime.radio is radio
    assert isinstance(runtime.gps, MockGPSReceiver)
    assert received == [(_CAT_DEVICE, 38_400, 1.75)]


def test_unavailable_real_radio_does_not_prevent_runtime_start(tmp_path: Path) -> None:
    radio = FakePhysicalRadio(
        connect_error=RadioConnectionError("FT-891 Enhanced CAT port unavailable")
    )

    def radio_factory(
        _device: Path,
        *,
        baud_rate: int,
        timeout_s: float,
    ) -> Radio:
        assert baud_rate == 38_400
        assert timeout_s == 1.75
        return radio

    runtime = ApplicationRuntime.from_config(
        real_radio_config(tmp_path),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        radio_factory=radio_factory,
    )

    state = runtime.start()

    assert state.connection_state is RadioConnectionState.ERROR
    assert state.last_error == "FT-891 Enhanced CAT port unavailable"
    assert state.transmitting is False
    assert runtime.polling.is_running is True
    assert runtime.contact_logging is not None
    assert runtime.gps_polling is not None
    assert runtime.gps_polling.is_running is True
