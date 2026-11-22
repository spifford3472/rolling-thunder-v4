"""Read WSPR PCM from the shared ALSA capture command into bounded memory."""

from collections.abc import Callable
from datetime import datetime
from os import read
from selectors import EVENT_READ, DefaultSelector
from subprocess import DEVNULL, PIPE, Popen

from rolling_thunder.ft8.audio import AlsaCaptureCommand


class WsprAudioError(RuntimeError):
    """The capture device did not provide a complete, aligned receive window."""


class WsprAudio:
    """Capture one mono 12 kHz signed 16-bit window, with a fresh UTC anchor."""

    def __init__(self, device: str) -> None:
        self._command = AlsaCaptureCommand(device)

    def capture(
        self,
        start_utc: datetime,
        byte_count: int,
        now_utc: Callable[[], datetime],
        check: Callable[[], None],
    ) -> bytes:
        # Small ALSA periods limit the lag between sampling and arrival at the pipe.
        args = (*self._command.argv()[:-1], "--period-time=50000", "--buffer-time=200000", "-")
        process = Popen(args, stdin=DEVNULL, stdout=PIPE, stderr=DEVNULL)
        try:
            assert process.stdout is not None
            with DefaultSelector() as selector:
                selector.register(process.stdout, EVENT_READ)
                pcm = bytearray()
                while len(pcm) < byte_count:
                    check()
                    if (now_utc() - start_utc).total_seconds() > 116.0:
                        raise WsprAudioError("ALSA did not complete the receive window")
                    if not selector.select(timeout=0.2):
                        continue
                    chunk = read(process.stdout.fileno(), 1200)
                    if not chunk or len(chunk) % 2:
                        raise WsprAudioError("ALSA capture ended or returned invalid PCM")
                    delta = (now_utc() - start_utc).total_seconds()
                    if delta < 0:
                        continue
                    if not pcm:
                        if delta > 0.25:
                            raise WsprAudioError("ALSA missed the UTC receive boundary")
                        # The chunk ends at its estimated arrival time. Keep only
                        # samples on or after the UTC boundary.
                        keep = min(len(chunk), max(2, round(delta * 12_000) * 2))
                        chunk = chunk[-keep:]
                    pcm.extend(chunk[:byte_count - len(pcm)])
                return bytes(pcm)
        finally:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=1)
            if process.stdout is not None:
                process.stdout.close()
