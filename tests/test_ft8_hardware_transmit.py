"""Checkpoint 6 tests for the isolated owner-test transmit boundary."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime

import pytest

import rolling_thunder.ft8.qso as qso_module
from rolling_thunder.ft8.encoder import (
    FT8_SAMPLE_RATE_HZ,
    FT8EncodedMessage,
    FT8Waveform,
)
from rolling_thunder.ft8.hardware_transmit import (
    FT8HardwareTestAuthorization,
    FT8HardwareTestRequest,
    RecordingFT8HardwareTransmitExecutor,
)
from rolling_thunder.ft8.transmit import RecordingDigitalTransmitSession


def _waveform(*, sample_rate_hz: int = FT8_SAMPLE_RATE_HZ) -> FT8Waveform:
    return FT8Waveform(
        encoded=FT8EncodedMessage(
            message="KI5VNB TEST",
            packed_payload=b"0123456789",
            tones=(0,) * 79,
        ),
        base_frequency_hz=1500,
        sample_rate_hz=sample_rate_hz,
        pcm_s16le=b"\x00\x00" * 180_000,
    )


def _authorization() -> FT8HardwareTestAuthorization:
    return FT8HardwareTestAuthorization(
        authorization_id="owner-test-1",
        approved_at_utc=datetime(2026, 9, 30, tzinfo=UTC),
    )


def test_hardware_test_boundary_is_structurally_separate_from_qso_session() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()
    qso_session = RecordingDigitalTransmitSession()

    assert hasattr(executor, "execute_test")
    assert not hasattr(executor, "request")
    assert hasattr(qso_session, "request")
    assert not hasattr(qso_session, "execute_test")
    assert "hardware_transmit" not in inspect.getsource(qso_module)


def test_recording_executor_accepts_only_explicit_test_request() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()
    request = FT8HardwareTestRequest(
        authorization=_authorization(),
        waveform=_waveform(),
        maximum_key_down_s=20.0,
        expected_radio_frequency_hz=14_074_000,
        expected_radio_mode="DATA",
    )

    executor.execute_test(request)

    assert executor.requests == [request]


def test_test_authorization_requires_identity_and_aware_time() -> None:
    with pytest.raises(ValueError, match="authorization_id"):
        FT8HardwareTestAuthorization(
            authorization_id=" ",
            approved_at_utc=datetime(2026, 9, 30, tzinfo=UTC),
        )

    with pytest.raises(ValueError, match="timezone-aware"):
        FT8HardwareTestAuthorization(
            authorization_id="owner-test-1",
            approved_at_utc=datetime(2026, 9, 30),
        )


@pytest.mark.parametrize(
    ("maximum_key_down_s", "frequency_hz", "mode", "match"),
    [
        (0.0, 14_074_000, "DATA", "maximum_key_down_s"),
        (20.0, 0, "DATA", "expected_radio_frequency_hz"),
        (20.0, 14_074_000, " ", "expected_radio_mode"),
    ],
)
def test_hardware_test_request_rejects_invalid_bounds(
    maximum_key_down_s: float,
    frequency_hz: int,
    mode: str,
    match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        FT8HardwareTestRequest(
            authorization=_authorization(),
            waveform=_waveform(),
            maximum_key_down_s=maximum_key_down_s,
            expected_radio_frequency_hz=frequency_hz,
            expected_radio_mode=mode,
        )


def test_hardware_test_request_rejects_wrong_sample_rate() -> None:
    with pytest.raises(ValueError, match="12000 Hz"):
        FT8HardwareTestRequest(
            authorization=_authorization(),
            waveform=_waveform(sample_rate_hz=48_000),
            maximum_key_down_s=20.0,
            expected_radio_frequency_hz=14_074_000,
            expected_radio_mode="DATA",
        )


def test_cancel_and_close_are_idempotent_in_hardware_free_fake() -> None:
    executor = RecordingFT8HardwareTransmitExecutor()

    executor.cancel_test()
    executor.cancel_test()
    executor.close()
    executor.close()

    assert executor.cancel_count == 2
    assert executor.close_count == 2
