"""Dedicated bounded ALSA HDMI klaxon; never uses the FT8 DigiRig output."""

from __future__ import annotations

import math
import struct
import subprocess
from collections.abc import Callable
from threading import Event, Thread

from rolling_thunder.ft8.ptt_alarm import FT8PttAlarm

_RATE = 16000


def klaxon_pcm() -> bytes:
    """Distinctive repeating dual-frequency warning, 16-bit mono PCM."""
    samples = bytearray()
    for frequency in (740, 520, 740, 520):
        for i in range(_RATE // 4):
            phase = 2 * math.pi * frequency * i / _RATE
            samples.extend(struct.pack('<h', round(8000 * math.sin(phase))))
    return bytes(samples)


class PttKlaxon:
    """Play bounded 1-second pulses in a daemon; errors never hide visual alarm."""

    def __init__(
        self,
        alarm: FT8PttAlarm,
        *,
        device: str = 'default',
        runner: Callable[..., object] = subprocess.run,
    ) -> None:
        self._alarm = alarm
        self._device = device
        self._runner = runner
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, daemon=True, name='ft8-ptt-klaxon')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    def _run(self) -> None:
        payload = klaxon_pcm()
        while not self._stop.is_set():
            if not self._alarm.audible:
                self._stop.wait(0.2)
                continue
            try:
                self._runner(
                    ('aplay', '-q', '-D', self._device, '-f', 'S16_LE',
                     '-c', '1', '-r', str(_RATE), '-t', 'raw', '-'),
                    input=payload,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=2.0,
                )
            except (OSError, subprocess.TimeoutExpired):
                self._stop.wait(0.5)
