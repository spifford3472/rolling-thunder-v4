"""Tests for the application composition root."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from json import dumps
from pathlib import Path
from uuid import UUID

import pytest
from pydantic import SecretStr

from rolling_thunder.application_runtime import ApplicationRuntime
from rolling_thunder.application_secrets import (
    ApplicationSecrets,
    CompletedQsoDeliveryCredentials,
)
from rolling_thunder.completed_qso_producer import (
    CompletedQsoDeliveryState,
    CompletedQsoDestination,
    CompletedQsoProducerRepository,
)
from rolling_thunder.config import ApplicationConfig
from rolling_thunder.domain import GPSFixState, RadioConnectionState
from rolling_thunder.ft8.audio import FT8AudioInputError
from rolling_thunder.ft8.coordinator import FT8QsoResult
from rolling_thunder.ft8.decoder import ComparingFT8Decoder, FT8PcmPeriod
from rolling_thunder.ft8.domain import (
    FT8CQActivity,
    FT8Decode,
    FT8IncomingCall,
    FT8MessageKind,
    FT8Period,
    FT8PeriodParity,
    FT8QsoContext,
    FT8QsoState,
)
from rolling_thunder.ft8.encoder import FT8Waveform
from rolling_thunder.ft8.hardware_transmit import RecordingFT8HardwareTransmitExecutor
from rolling_thunder.ft8.performance import FT8AttemptSeed
from rolling_thunder.ft8.receive import FT8ReceiveState
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


class DeliveryScheduler:
    def __init__(self) -> None:
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        assert interval_s == 30
        self.poll = ManualScheduledPoll(callback)
        return self.poll


class CompletedQsoReceiverTransport:
    def __init__(self, *, wrong_psk_ack: bool = False) -> None:
        self.wrong_psk_ack = wrong_psk_ack
        self.calls: list[tuple[str, Mapping[str, str], bytes | None]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> "_HttpResponse":
        _ = timeout_s
        self.calls.append((url, headers, body))
        contact_id = headers["Idempotency-Key"]
        if self.wrong_psk_ack and url.endswith("/api/v1/completed-ft8-events"):
            contact_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        payload: dict[str, str] = {
            "schema_version": "1",
            "contact_id": contact_id,
            "disposition": "accepted",
        }
        if url.endswith("/api/v1/completed-qsos"):
            payload["received_at_utc"] = "2026-10-09T12:00:00Z"
        return _HttpResponse(202, dumps(payload).encode())


class _HttpResponse:
    def __init__(self, status_code: int, body: bytes) -> None:
        self.status_code = status_code
        self.body = body


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
    runtime.stop()


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
        raise FT8AudioInputError("test capture intentionally unavailable")

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


def test_runtime_shares_packaged_jurisdiction_resolver_with_ft8() -> None:
    runtime = ApplicationRuntime.from_config(
        _ft8_runtime_config(transmit_enabled=False),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        ft8_audio_input=_UnusedFT8AudioInput(),
        ft8_decoder=_UnusedFT8Decoder(),
    )

    resolver = runtime.contact_logging._jurisdiction_resolver
    assert resolver is not None
    assert runtime.ft8_authorization is not None
    assert runtime.ft8_authorization.jurisdiction_resolver is resolver
    jurisdiction = resolver.resolve(39.5290, -84.0870)
    assert jurisdiction is not None
    assert (jurisdiction.state, jurisdiction.cq_zone, jurisdiction.itu_zone) == (
        "OH",
        4,
        8,
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
    assert runtime.ft8_panel is not None
    assert runtime.ft8_qso is None
    assert runtime.ft8_hardware_transmit is None


def test_runtime_composes_bounded_same_pcm_diagnostic_session() -> None:
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "ft8": {
                "enabled": True,
                "receive": {
                    "decoder_backend": "ft8_lib",
                    "decoder_executable": "/opt/ft8_lib/decode_ft8",
                    "comparison_backend": "ft8mon",
                    "comparison_decoder_executable": "/opt/ft8mon/ft8mon",
                    "diagnostic_session_end_local": "05:15",
                },
            },
        }
    )
    clock = FakeFT8Clock(datetime(2026, 10, 6, 5, 0, tzinfo=UTC))

    runtime = ApplicationRuntime.from_config(
        config,
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        ft8_audio_input=_UnusedFT8AudioInput(),
        ft8_clock=clock,
    )

    assert runtime.ft8_receive is not None
    assert isinstance(runtime.ft8_receive._decoder, ComparingFT8Decoder)
    session = runtime.ft8_receive.latest_state.diagnostic_session
    assert session is not None
    assert session.active is True
    assert session.ends_at == datetime(2026, 10, 6, 9, 15, tzinfo=UTC)


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
    assert runtime.ft8_panel is not None
    assert runtime.ft8_qso is not None
    assert runtime.ft8_hardware_transmit is executor


def test_completed_qso_delivery_is_scheduled_provider_free_and_ack_safe(
    tmp_path: Path,
) -> None:
    qso_id = UUID("00000000-0000-4000-8000-000000000901")
    outbox_path = tmp_path / "completed-qso.db"
    config = ApplicationConfig.model_validate(
        {
            "operator": {"callsign": "KI5VNB", "home_grid": "EM79xm"},
            "hardware": {"mock": True},
            "storage": {"database_path": tmp_path / "contacts.db"},
            "ft8": {
                "enabled": True,
                "receive": {"decoder_executable": "/unused/decode_ft8"},
                "transmit": {
                    "enabled": True,
                    "encoder_executable": "/unused/gen_ft8",
                },
                "completed_qso_delivery": {
                    "enabled": True,
                    "database_path": outbox_path,
                    "voacap": {
                        "enabled": True,
                        "base_url": "http://forge.test:8790",
                    },
                    "psk_reporter": {
                        "enabled": True,
                        "base_url": "http://forge.test:8789",
                    },
                },
            },
        }
    )
    tokens = CompletedQsoDeliveryCredentials(
        voacap_token=SecretStr("v" * 32),
        psk_reporter_token=SecretStr("p" * 32),
    )
    voacap_transport = CompletedQsoReceiverTransport()
    psk_transport = CompletedQsoReceiverTransport(wrong_psk_ack=True)
    delivery_scheduler = DeliveryScheduler()
    period = FT8Period(100)
    runtime = ApplicationRuntime.from_config(
        config,
        secrets=ApplicationSecrets(completed_qso_delivery=tokens),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
        ft8_completed_qso_delivery_scheduler=delivery_scheduler,
        ft8_completed_qso_voacap_transport=voacap_transport,
        ft8_completed_qso_psk_transport=psk_transport,
        ft8_audio_input=_UnusedFT8AudioInput(),
        ft8_decoder=_UnusedFT8Decoder(),
        ft8_encoder=_UnusedFT8Encoder(),
        ft8_clock=FakeFT8Clock(period.start_utc),
        ft8_hardware_executor=RecordingFT8HardwareTransmitExecutor(),
    )
    assert runtime.ft8_qso is not None
    terminal_handler = runtime.ft8_qso._terminal_result_handler
    assert terminal_handler is not None
    terminal_handler(
        FT8QsoResult(
            status=FT8QsoState.COMPLETED,
            context=FT8QsoContext(
                local_callsign="KI5VNB",
                remote_callsign="K1ABC",
                target_audio_frequency_hz=1500,
                radio_frequency_hz=14_074_000,
                radio_band="20m",
                radio_mode="USB",
                local_grid="EM79xm",
                remote_grid="FN31pr",
                tx_parity=FT8PeriodParity.ODD,
                authorized_period=period,
                authorized_utc=period.start_utc,
                signal_report_db=-10,
                qso_id=qso_id,
            ),
            sent_report_db=-10,
            received_report_db=-12,
            started_utc=period.start_utc,
            ended_utc=period.start_utc + timedelta(seconds=75),
            terminal_reason=None,
        )
    )

    assert voacap_transport.calls == []
    assert psk_transport.calls == []
    runtime.start()
    assert delivery_scheduler.poll is not None
    delivery_scheduler.poll.callback()
    repository = CompletedQsoProducerRepository(outbox_path)

    assert len(voacap_transport.calls) == 1
    assert len(psk_transport.calls) == 1
    assert repository.state_for(qso_id, CompletedQsoDestination.VOACAP) is (
        CompletedQsoDeliveryState.DELIVERED
    )
    assert repository.state_for(qso_id, CompletedQsoDestination.PSK_REPORTER) is (
        CompletedQsoDeliveryState.RETRY
    )
    runtime.ft8_completed_qso_delivery.stop()
    runtime.stop()



def test_runtime_stop_closes_ft8_executor_even_before_start() -> None:
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

    runtime.stop()
    runtime.stop()

    assert executor.requests == []
    assert executor.qso_requests == []
    assert executor.close_count == 1


class _RecordingLifecycleService:
    def __init__(self) -> None:
        self.start_count = 0
        self.stop_count = 0

    def start(self) -> None:
        self.start_count += 1

    def stop(self) -> None:
        self.stop_count += 1


class _FailingStartService:
    def start(self) -> None:
        raise RuntimeError("injected startup failure")

    def stop(self) -> None:
        return


def test_runtime_start_failure_rolls_back_ft8_service() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )
    ft8 = _RecordingLifecycleService()
    runtime.ft8_receive = ft8  # type: ignore[assignment]
    assert runtime.gps_polling is not None
    runtime.gps_polling = _FailingStartService()  # type: ignore[assignment]

    with pytest.raises(RuntimeError, match="injected startup failure"):
        runtime.start()

    assert ft8.start_count == 1
    assert ft8.stop_count == 1


class _TerminalQso:
    def __init__(self) -> None:
        self.return_count = 0

    def return_to_browser(self) -> object:
        self.return_count += 1
        return object()


class _StartStatusReset:
    def __init__(self) -> None:
        self.reset_count = 0

    def reset_to_idle(self) -> bool:
        self.reset_count += 1
        return True


def test_return_ft8_to_browser_clears_stale_start_status() -> None:
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )
    qso = _TerminalQso()
    starter = _StartStatusReset()
    runtime.ft8_qso = qso  # type: ignore[assignment]
    runtime.ft8_qso_start = starter  # type: ignore[assignment]

    result = runtime.return_ft8_to_browser()

    assert result is not None
    assert qso.return_count == 1
    assert starter.reset_count == 1


class _ResponderAuthorization:
    def __init__(self, clock: FakeFT8Clock) -> None:
        self.clock = clock
        self.home_grid = "EM79xm"
        self.validated: list[FT8IncomingCall] = []

    def validate_incoming_freshness(
        self,
        incoming: FT8IncomingCall,
        *,
        selection_period: FT8Period,
        current_period: FT8Period,
    ) -> None:
        assert selection_period == self.clock.current_period()
        assert current_period == self.clock.current_period()
        self.validated.append(incoming)


class _PublishedFT8Receive:
    def __init__(self, state: FT8ReceiveState) -> None:
        self.latest_state = state


class _IncomingStartRecorder:
    def __init__(self) -> None:
        self.started: list[tuple[FT8IncomingCall, FT8AttemptSeed]] = []

    def start_incoming(
        self,
        incoming: FT8IncomingCall,
        *,
        attempt_seed: FT8AttemptSeed,
    ) -> bool:
        self.started.append((incoming, attempt_seed))
        return True


class _SelectionAuthorization:
    def __init__(self, clock: FakeFT8Clock) -> None:
        self.clock = clock
        self.home_grid = "EM79xm"
        self.validated: list[tuple[FT8CQActivity, FT8Period, FT8Period]] = []

    def validate_selection_freshness(
        self,
        activity: FT8CQActivity,
        *,
        selection_period: FT8Period,
        current_period: FT8Period,
    ) -> None:
        self.validated.append((activity, selection_period, current_period))


class _SelectionStartRecorder:
    def __init__(self) -> None:
        self.started: list[tuple[FT8CQActivity, FT8AttemptSeed]] = []

    def start(
        self,
        activity: FT8CQActivity,
        *,
        attempt_seed: FT8AttemptSeed,
    ) -> bool:
        self.started.append((activity, attempt_seed))
        return True


def test_runtime_validates_selection_against_one_period_lagged_receive_snapshot() -> None:
    current_period = FT8Period(101)
    receive_period = FT8Period(100)
    activity = FT8CQActivity(
        callsign="K1ABC",
        last_period=FT8Period(95),
        snr_db=-10,
        dt_seconds=0.1,
        audio_frequency_hz=1500,
        grid="FN31",
    )
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )
    authorization = _SelectionAuthorization(
        FakeFT8Clock(current_period.start_utc)
    )
    starter = _SelectionStartRecorder()
    runtime.ft8_authorization = authorization  # type: ignore[assignment]
    runtime.ft8_qso = object()  # type: ignore[assignment]
    runtime.ft8_qso_start = starter  # type: ignore[assignment]
    runtime.ft8_receive = _PublishedFT8Receive(
        FT8ReceiveState(last_period=receive_period, cq_activity=(activity,))
    )  # type: ignore[assignment]

    assert runtime.request_ft8_qso(activity) is True
    assert authorization.validated == [
        (activity, receive_period, current_period)
    ]
    assert starter.started[0][0] is activity


@pytest.mark.parametrize(
    ("incoming", "expected_report"),
    [
        (
            FT8IncomingCall(
                callsign="W4YRL",
                period=FT8Period(100),
                snr_db=-9,
                dt_seconds=0.1,
                audio_frequency_hz=1500,
                kind=FT8MessageKind.ADDRESSED_GRID,
                grid="EL99",
                raw_message="KI5VNB W4YRL EL99",
            ),
            None,
        ),
        (
            FT8IncomingCall(
                callsign="K0BQB",
                period=FT8Period(100),
                snr_db=-3,
                dt_seconds=0.1,
                audio_frequency_hz=1600,
                kind=FT8MessageKind.REPORT,
                report_db=-3,
                raw_message="KI5VNB K0BQB -03",
            ),
            -3,
        ),
    ],
)
def test_runtime_routes_explicit_incoming_acceptance_to_responder_start(
    incoming: FT8IncomingCall,
    expected_report: int | None,
) -> None:
    clock = FakeFT8Clock(incoming.period.start_utc)
    runtime = ApplicationRuntime.from_config(
        mock_config(),
        scheduler=ManualScheduler(),
        gps_scheduler=ManualScheduler(),
    )
    authorization = _ResponderAuthorization(clock)
    starter = _IncomingStartRecorder()
    runtime.ft8_authorization = authorization  # type: ignore[assignment]
    runtime.ft8_qso = object()  # type: ignore[assignment]
    runtime.ft8_qso_start = starter  # type: ignore[assignment]
    runtime.ft8_receive = _PublishedFT8Receive(
        FT8ReceiveState(last_period=incoming.period, incoming_call=incoming)
    )  # type: ignore[assignment]

    assert runtime.request_ft8_response(incoming) is True

    assert authorization.validated == [incoming]
    assert len(starter.started) == 1
    started_call, seed = starter.started[0]
    assert started_call is incoming
    assert seed.callsign == incoming.callsign
    assert seed.remote_grid == incoming.grid
    assert seed.received_report_db == expected_report
