"""Tests for the application composition root."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import GPSFixState, RadioConnectionState
from rolling_thunder.ft8.decoder import FT8PcmPeriod
from rolling_thunder.ft8.domain import FT8Decode, FT8Period
from rolling_thunder.ft8.encoder import FT8Waveform
from rolling_thunder.ft8.hardware_transmit import RecordingFT8HardwareTransmitExecutor
from rolling_thunder.ft8.timing import FakeFT8Clock
from rolling_thunder.gps import (
    GPSConnectionError,
    GPSConnectionState,
    GPSReceiver,
    GPSState,
)
from rolling_thunder.mock_gps import MockGPSReceiver
from rolling_thunder.mock_radio import MockRadio
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.serial_gps import SerialGPSReceiver
from rolling_thunder.status_messages import StatusMessageService


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


class UnavailableGPSReceiver:
    def __init__(self) -> None:
        self.state = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
            updated_at=datetime(2026, 8, 2, 13, 0, tzinfo=UTC),
        )

    def connect(self) -> GPSState:
        raise GPSConnectionError("GPS device is unavailable")

    def disconnect(self) -> GPSState:
        self.state = GPSState(
            connection_state=GPSConnectionState.DISCONNECTED,
            position=None,
            updated_at=datetime(2026, 8, 2, 13, 1, tzinfo=UTC),
        )
        return self.state

    def get_state(self) -> GPSState:
        return self.state

    def refresh_state(self) -> GPSState:
        raise GPSConnectionError("GPS device is unavailable")


def mock_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
        }
    )


def hardware_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {
                "mock": False,
                "radio_device": "/dev/ttyUSB0",
                "gps_device": "/dev/ttyUSB1",
            },
        }
    )


def real_gps_mock_radio_config() -> ApplicationConfig:
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {
                "mock": True,
                "radio_mode": "mock",
                "gps_mode": "real",
                "gps_device": "/dev/serial/by-id/gps",
                "gps_baud_rate": 9_600,
                "gps_timeout_s": 0.75,
            },
        }
    )


def test_runtime_composes_and_starts_mock_hardware() -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
    )

    state = runtime.start()

    assert state.connection_state is RadioConnectionState.CONNECTED
    assert runtime.latest_radio_state.connection_state is RadioConnectionState.CONNECTED
    assert isinstance(runtime.gps, MockGPSReceiver)
    assert runtime.gps_polling is not None
    assert runtime.gps_polling.is_running is True
    assert runtime.pota_enrichment.is_running is True
    assert isinstance(runtime.status_messages, StatusMessageService)
    assert runtime.ft8_receive is None
    assert runtime.latest_ft8_receive_state is None
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.CONNECTED
    assert gps_state.position is not None
    assert gps_state.position.fix_state is GPSFixState.THREE_DIMENSIONAL
    assert radio_scheduler.poll is not None
    assert gps_scheduler.poll is not None


def test_runtime_stop_cancels_polling_and_disconnects_hardware() -> None:
    radio_scheduler = ManualScheduler()
    gps_scheduler = ManualScheduler()
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=radio_scheduler,
        gps_scheduler=gps_scheduler,
    )
    runtime.start()

    state = runtime.stop()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    assert runtime.pota_enrichment.is_running is False
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED
    assert gps_state.position is None
    assert radio_scheduler.poll is not None
    assert radio_scheduler.poll.cancelled is True
    assert gps_scheduler.poll is not None
    assert gps_scheduler.poll.cancelled is True
    assert runtime.gps is not None
    assert runtime.gps.get_state().connection_state is GPSConnectionState.DISCONNECTED


def test_non_mock_runtime_composes_serial_gps() -> None:
    runtime = ApplicationRuntime.from_config(
        hardware_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    assert isinstance(runtime.gps, SerialGPSReceiver)
    assert runtime.gps_polling is not None
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED


def test_non_mock_runtime_uses_configured_gps_settings_with_injected_factory() -> None:
    received: list[tuple[Path, int, float]] = []
    receiver = MockGPSReceiver()

    def gps_factory(
        device: Path,
        *,
        baud_rate: int,
        timeout_s: float,
    ) -> GPSReceiver:
        received.append((device, baud_rate, timeout_s))
        return receiver

    runtime = ApplicationRuntime.from_config(
        hardware_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        gps_factory=gps_factory,
    )

    assert received == [(Path("/dev/ttyUSB1"), 9_600, 2.0)]
    assert runtime.gps is receiver
    assert runtime.latest_gps_state is receiver.get_state()


def test_real_gps_can_run_with_mock_radio() -> None:
    received: list[tuple[Path, int, float]] = []
    receiver = MockGPSReceiver()

    def gps_factory(
        device: Path,
        *,
        baud_rate: int,
        timeout_s: float,
    ) -> GPSReceiver:
        received.append((device, baud_rate, timeout_s))
        return receiver

    runtime = ApplicationRuntime.from_config(
        real_gps_mock_radio_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        gps_factory=gps_factory,
    )

    assert isinstance(runtime.radio, MockRadio)
    assert runtime.gps is receiver
    assert received == [(Path("/dev/serial/by-id/gps"), 9_600, 0.75)]


def test_unavailable_real_gps_does_not_prevent_runtime_start() -> None:
    receiver = UnavailableGPSReceiver()

    def gps_factory(
        _device: Path,
        *,
        baud_rate: int,
        timeout_s: float,
    ) -> GPSReceiver:
        assert baud_rate == 9_600
        assert timeout_s == 0.75
        return receiver

    runtime = ApplicationRuntime.from_config(
        real_gps_mock_radio_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        gps_factory=gps_factory,
    )

    radio_state = runtime.start()

    assert radio_state.connection_state is RadioConnectionState.CONNECTED
    assert runtime.latest_radio_state.connection_state is RadioConnectionState.CONNECTED
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.ERROR
    assert gps_state.last_error == "GPS device is unavailable"
    assert runtime.contact_logging is not None


def test_runtime_rejects_repeated_start() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )
    runtime.start()

    with pytest.raises(RuntimeError, match="already started"):
        runtime.start()


def test_runtime_stop_before_start_is_safe() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )

    state = runtime.stop()

    assert state.connection_state is RadioConnectionState.DISCONNECTED
    assert runtime.pota_enrichment.is_running is False
    gps_state = runtime.latest_gps_state
    assert gps_state is not None
    assert gps_state.connection_state is GPSConnectionState.DISCONNECTED


def test_test_clock_reference_is_timezone_aware() -> None:
    assert datetime(2026, 7, 25, tzinfo=UTC).utcoffset() is not None



class _UnusedFT8AudioInput:
    def start(self) -> None:
        return

    def read_period(self) -> FT8PcmPeriod:
        raise RuntimeError("not used")

    def stop(self) -> None:
        return


class _UnusedFT8Decoder:
    def decode(self, pcm: FT8PcmPeriod) -> tuple[FT8Decode, ...]:
        _ = pcm
        return ()


class _UnusedFT8Encoder:
    def encode(self, message: str, *, base_frequency_hz: int) -> FT8Waveform:
        _ = (message, base_frequency_hz)
        raise RuntimeError("not used")


def _ft8_runtime_config(*, transmit_enabled: bool) -> ApplicationConfig:
    ft8: dict[str, object] = {
        "enabled": True,
        "receive": {
            "decoder_executable": "/opt/ft8_lib/decode_ft8",
        },
    }
    if transmit_enabled:
        ft8["transmit"] = {
            "enabled": True,
            "encoder_executable": "/opt/ft8_lib/gen_ft8",
        }
    return ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "ft8": ft8,
        }
    )


def test_runtime_ft8_receive_only_creates_no_transmit_authority() -> None:
    runtime = ApplicationRuntime.from_config(
        _ft8_runtime_config(transmit_enabled=False),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        ft8_audio_input=_UnusedFT8AudioInput(),
        ft8_decoder=_UnusedFT8Decoder(),
    )

    assert runtime.ft8_receive is not None
    assert runtime.ft8_qso is None
    assert runtime.ft8_hardware_transmit is None


def test_runtime_ft8_transmit_requires_explicit_gate() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()
    period = FT8Period(100)
    runtime = ApplicationRuntime.from_config(
        _ft8_runtime_config(transmit_enabled=True),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        ft8_audio_input=_UnusedFT8AudioInput(),
        ft8_decoder=_UnusedFT8Decoder(),
        ft8_encoder=_UnusedFT8Encoder(),
        ft8_clock=FakeFT8Clock(period.start_utc),
        ft8_hardware_executor=executor,
    )

    assert runtime.ft8_receive is not None
    assert runtime.ft8_qso is not None
    assert runtime.ft8_hardware_transmit is executor
