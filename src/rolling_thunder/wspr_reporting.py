"""Single-attempt HTTPS WSPRnet reporting on a background worker."""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from math import isfinite
from threading import Event, Lock
from time import monotonic
from urllib.parse import urlencode

_ENDPOINT = "https://wsprnet.org/post/"
_TIMEOUT_S = 4.0
_CANCEL_POLL_S = 0.05
_REPORT_INTERVAL_S = 0.2  # The reference WSJT-X uploader spaces requests by 200 ms.
_MAX_RESPONSE_BYTES = 2048
_WSPR_CENTER_HZ = 1500
_CALLSIGN = re.compile(r"[A-Z0-9]{1,7}(?:/[A-Z0-9]{1,7})?")
_GRID4 = re.compile(r"[A-R]{2}[0-9]{2}")
_SPOT_GRID = re.compile(r"[A-R]{2}[0-9]{2}(?:[A-X]{2})?")
_ACKNOWLEDGED = re.compile(rb"\b(\d+)(?: out of (\d+))? spot\(s\) added\b")


class WsprUploadStatus(StrEnum):
    """Only provider-acknowledged spots qualify for retained station statistics."""

    ACCEPTED = "accepted"
    UNAVAILABLE = "unavailable"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    IN_FLIGHT_UNKNOWN = "in_flight_unknown"


@dataclass(frozen=True, slots=True, repr=False)
class WsprSpot:
    """A transient report for one completed WSPR receive slot."""

    receiver_callsign: str
    receiver_grid: str
    slot_utc: datetime
    dial_hz: int
    callsign: str
    grid: str | None
    frequency_hz: int
    snr_db: int
    dt_s: float
    drift_hz: int
    power_dbm: int


class WsprnetReporter:
    """Send one fresh report, without redirects, persistence, logging or retry."""

    def __init__(self) -> None:
        self._request_lock = Lock()
        self._last_request_started = -_REPORT_INTERVAL_S

    def report(self, spot: WsprSpot, *, cancel: Event) -> WsprUploadStatus:
        """Attempt one upload. A cancelled in-flight request may have reached WSPRnet."""
        if cancel.is_set():
            return WsprUploadStatus.CANCELLED
        body = _encode_spot(spot)
        if body is None:
            return WsprUploadStatus.REJECTED

        # A second caller must never enqueue a spot behind an in-flight upload.
        if not self._request_lock.acquire(blocking=False):
            return WsprUploadStatus.UNAVAILABLE
        try:
            delay = _REPORT_INTERVAL_S - (monotonic() - self._last_request_started)
            if cancel.wait(max(0.0, delay)):
                return WsprUploadStatus.CANCELLED
            self._last_request_started = monotonic()
            return _post_once(body, cancel)
        finally:
            self._request_lock.release()


def _encode_spot(spot: WsprSpot) -> bytes | None:
    """Validate the public form, limiting receiver location to four characters."""
    receiver_call = spot.receiver_callsign.upper()
    receiver_grid = spot.receiver_grid.upper()
    station_call = spot.callsign.upper()
    station_grid = "" if spot.grid is None else spot.grid.upper()
    if (
        not _CALLSIGN.fullmatch(receiver_call)
        or not _CALLSIGN.fullmatch(station_call)
        or not _GRID4.fullmatch(receiver_grid)
        or (station_grid and not _SPOT_GRID.fullmatch(station_grid))
        or spot.slot_utc.utcoffset() is None
        or spot.dial_hz <= 0
        or not isfinite(spot.dt_s)
        or abs(spot.frequency_hz - (spot.dial_hz + _WSPR_CENTER_HZ)) > 200
    ):
        return None
    utc = spot.slot_utc.astimezone(UTC)
    if utc.minute % 2 or utc.second or utc.microsecond:
        return None
    return urlencode(
        {
            "function": "wspr",
            "date": utc.strftime("%y%m%d"),
            "time": utc.strftime("%H%M"),
            "sig": spot.snr_db,
            "dt": f"{spot.dt_s:.1f}",
            "drift": spot.drift_hz,
            "tqrg": _mhz(spot.frequency_hz),
            "tcall": station_call,
            "tgrid": station_grid,
            "dbm": spot.power_dbm,
            "version": "Rolling Thunder v4",
            "rcall": receiver_call,
            "rgrid": receiver_grid,
            "rqrg": _mhz(spot.dial_hz + _WSPR_CENTER_HZ),
            "mode": "2",
        }
    ).encode("ascii")


def _mhz(frequency_hz: int) -> str:
    whole, fraction = divmod(frequency_hz, 1_000_000)
    return f"{whole}.{fraction:06d}"


def _post_once(body: bytes, cancel: Event) -> WsprUploadStatus:
    """Bound DNS, TLS and response time. Only pipes carry report content."""
    if cancel.is_set():
        return WsprUploadStatus.CANCELLED
    command = (
        "curl",
        "--disable",  # Must be first. Ignore ~/.curlrc, including trace or output settings.
        "--silent",
        "--noproxy", "*",
        "--proto", "=https",
        "--http1.1",  # Avoid automatic retransmission of refused HTTP/2 streams.
        "--max-time", str(_TIMEOUT_S),
        "--max-filesize", str(_MAX_RESPONSE_BYTES),
        "--header", "Content-Type: application/x-www-form-urlencoded",
        "--data-binary", "@-",
        "--write-out", "\n%{http_code}",
        _ENDPOINT,
    )
    # Preserve executable lookup. Exclude inherited curl/TLS tracing settings.
    environment = {"PATH": os.environ.get("PATH", os.defpath)}
    try:
        with subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=environment,
        ) as process:
            return _await_response(process, body, cancel)
    except OSError:
        return WsprUploadStatus.UNAVAILABLE


def _await_response(
    process: subprocess.Popen[bytes], body: bytes, cancel: Event
) -> WsprUploadStatus:
    if cancel.is_set():
        # The child was waiting for data on stdin, so the payload never reached it.
        process.kill()
        return WsprUploadStatus.CANCELLED

    deadline = monotonic() + _TIMEOUT_S + 0.25
    input_data: bytes | None = body
    while not cancel.is_set() and monotonic() < deadline:
        current_input, input_data = input_data, None
        try:
            output, _ = process.communicate(current_input, timeout=_CANCEL_POLL_S)
        except subprocess.TimeoutExpired:
            # communicate() retains its pipe state across a timeout. Never supply new input.
            continue
        except OSError:
            process.kill()
            return WsprUploadStatus.IN_FLIGHT_UNKNOWN
        if process.returncode in {6, 7, 35, 60}:  # DNS, connect and TLS handshake failures.
            return WsprUploadStatus.UNAVAILABLE
        if process.returncode != 0:
            return WsprUploadStatus.IN_FLIGHT_UNKNOWN
        response, _, status = output.rpartition(b"\n")
        if len(response) > _MAX_RESPONSE_BYTES:
            return WsprUploadStatus.IN_FLIGHT_UNKNOWN
        acknowledged = _ACKNOWLEDGED.search(response)
        if (
            status == b"200"
            and acknowledged is not None
            and acknowledged[1] == b"1"
            and acknowledged[2] in (None, b"1")
        ):
            return WsprUploadStatus.ACCEPTED
        return WsprUploadStatus.REJECTED

    process.kill()
    if input_data is not None and cancel.is_set():
        return WsprUploadStatus.CANCELLED
    return WsprUploadStatus.IN_FLIGHT_UNKNOWN
