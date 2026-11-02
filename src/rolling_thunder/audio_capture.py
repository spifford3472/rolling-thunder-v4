"""Bounded, cancellable ALSA PCM capture for offline speech recognition."""

from __future__ import annotations

import os
import select
import signal
import subprocess
from threading import Event
from time import monotonic


class AudioCaptureError(RuntimeError):
    """Raised when ALSA capture cannot produce a valid bounded recording."""


class AudioCaptureCancelled(AudioCaptureError):
    """Raised when an operator request cancels an active recording."""


def capture_alsa_pcm(
    *,
    audio_device: str,
    duration_s: int,
    sample_rate: int,
    channels: int,
    stop_event: Event,
    max_bytes: int | None = None,
) -> bytes:
    """Capture one bounded raw S16_LE recording and reap arecord on every path.

    Reading is polled with select so cancellation never depends on a blocking
    subprocess timeout. The byte limit is derived from the requested duration.
    """
    if not audio_device.strip():
        raise ValueError("audio_device must not be blank")
    if duration_s < 1 or sample_rate < 8_000 or channels < 1:
        raise ValueError("invalid ALSA capture format or duration")
    expected_bytes = duration_s * sample_rate * channels * 2
    byte_limit = expected_bytes if max_bytes is None else min(expected_bytes, max_bytes)
    if byte_limit < 2:
        raise ValueError("max_bytes must allow at least one sample")
    if stop_event.is_set():
        raise AudioCaptureCancelled("audio capture cancelled before startup")

    command = (
        "arecord",
        "--quiet",
        f"--device={audio_device}",
        "--file-type=raw",
        "--format=S16_LE",
        f"--rate={sample_rate}",
        f"--channels={channels}",
        f"--duration={duration_s}",
    )
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as error:
        raise AudioCaptureError("ALSA arecord was not found") from error
    except OSError as error:
        raise AudioCaptureError(f"could not start ALSA capture: {error}") from error

    captured = bytearray()
    deadline = monotonic() + duration_s + 3.0
    try:
        output = process.stdout
        if output is None:
            raise AudioCaptureError("ALSA capture has no output pipe")
        descriptor = output.fileno()
        while True:
            if stop_event.is_set():
                raise AudioCaptureCancelled("audio capture cancelled")
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise AudioCaptureError("ALSA capture timed out")
            readable, _, _ = select.select([descriptor], [], [], min(0.05, remaining))
            if not readable:
                if process.poll() is not None:
                    break
                continue
            chunk = os.read(descriptor, min(4_096, byte_limit - len(captured) + 1))
            if not chunk:
                break
            captured.extend(chunk)
            if len(captured) > byte_limit:
                raise AudioCaptureError("ALSA capture exceeded its configured byte limit")

        if stop_event.is_set():
            raise AudioCaptureCancelled("audio capture cancelled")
        try:
            return_code = process.wait(timeout=max(0.0, deadline - monotonic()))
        except subprocess.TimeoutExpired as error:
            raise AudioCaptureError("ALSA capture did not exit after its recording period") from error
        if return_code != 0:
            raise AudioCaptureError(f"arecord exited with status {return_code}")
        if not captured:
            raise AudioCaptureError("ALSA capture returned no audio")
        if len(captured) % (channels * 2):
            raise AudioCaptureError("ALSA capture ended on an incomplete audio frame")
        return bytes(captured)
    except AudioCaptureError:
        raise
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise AudioCaptureError(f"ALSA capture failed: {error}") from error
    finally:
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=0.5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                # Keep the gate held until the child is certainly reaped.
                process.wait()
        if process.stdout is not None:
            process.stdout.close()
