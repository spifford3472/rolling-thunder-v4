"""Tests for bounded background vehicle status monitoring."""

from collections.abc import Callable, Mapping

from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.radio_polling import PollCallback
from rolling_thunder.status_monitor import (
    AlsaCaptureProbe,
    ForgeHealthProbe,
    InternetReachabilityProbe,
    ProbeResult,
    StatusMonitorService,
    StatusProbe,
    StatusState,
)


class ManualScheduledPoll:
    def __init__(self, callback: PollCallback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class ManualScheduler:
    def __init__(self) -> None:
        self.interval_s: float | None = None
        self.poll: ManualScheduledPoll | None = None

    def schedule_repeating(
        self,
        interval_s: float,
        callback: PollCallback,
    ) -> ManualScheduledPoll:
        self.interval_s = interval_s
        self.poll = ManualScheduledPoll(callback)
        return self.poll

    def fire(self) -> None:
        assert self.poll is not None
        self.poll.fire()


class FakeConnection:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeHttpTransport:
    def __init__(
        self,
        *,
        response: UrllibHttpResponse | None = None,
        error: OSError | None = None,
    ) -> None:
        self.response = response or UrllibHttpResponse(200, b'{"service_status":"healthy"}')
        self.error = error
        self.requests: list[tuple[str, str, float]] = []

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> UrllibHttpResponse:
        del headers, body
        self.requests.append((method, url, timeout_s))
        if self.error is not None:
            raise self.error
        return self.response


class ScriptedProbe(StatusProbe):
    def __init__(self, *results: ProbeResult | Exception) -> None:
        self.results = list(results)
        self.check_count = 0

    def check(self) -> ProbeResult:
        self.check_count += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def test_internet_probe_success_uses_direct_ip_and_closes_connection() -> None:
    connection = FakeConnection()
    calls: list[tuple[tuple[str, int], float]] = []

    def connect(address: tuple[str, int], timeout_s: float) -> FakeConnection:
        calls.append((address, timeout_s))
        return connection

    probe = InternetReachabilityProbe(
        host="8.8.8.8",
        port=53,
        timeout_s=2.0,
        connector=connect,  # type: ignore[arg-type]
    )

    assert probe.check().state is StatusState.HEALTHY
    assert calls == [(('8.8.8.8', 53), 2.0)]
    assert connection.closed


def test_internet_probe_timeout_is_unavailable() -> None:
    def timeout(_address: tuple[str, int], _timeout_s: float) -> FakeConnection:
        raise TimeoutError("timed out")

    result = InternetReachabilityProbe(
        connector=timeout,  # type: ignore[arg-type]
    ).check()

    assert result.state is StatusState.UNAVAILABLE
    assert "timed out" in (result.detail or "")


def test_forge_health_success_uses_existing_health_endpoint_and_timeout() -> None:
    transport = FakeHttpTransport()
    probe = ForgeHealthProbe(
        "http://192.168.10.10:8765",
        timeout_s=3.5,
        transport=transport,
    )

    assert probe.check().state is StatusState.HEALTHY
    assert transport.requests == [
        ("GET", "http://192.168.10.10:8765/api/v1/health", 3.5)
    ]


def test_forge_connection_failure_is_unavailable() -> None:
    result = ForgeHealthProbe(
        "http://forge.local:8765",
        timeout_s=2.0,
        transport=FakeHttpTransport(error=OSError("connection refused")),
    ).check()

    assert result.state is StatusState.UNAVAILABLE
    assert "connection refused" in (result.detail or "")


def test_forge_unhealthy_response_is_unavailable() -> None:
    result = ForgeHealthProbe(
        "http://forge.local:8765",
        timeout_s=2.0,
        transport=FakeHttpTransport(
            response=UrllibHttpResponse(200, b'{"service_status":"degraded"}')
        ),
    ).check()

    assert result.state is StatusState.UNAVAILABLE
    assert result.detail == "Forge is degraded"


def test_forge_starting_response_is_neutral() -> None:
    result = ForgeHealthProbe(
        "http://forge.local:8765",
        timeout_s=2.0,
        transport=FakeHttpTransport(
            response=UrllibHttpResponse(200, b'{"service_status":"starting"}')
        ),
    ).check()

    assert result.state is StatusState.STARTING


def test_microphone_present_by_stable_alsa_card_name() -> None:
    probe = AlsaCaptureProbe(
        "plughw:CARD=Array,DEV=0",
        cards_reader=lambda: " 2 [Array          ]: USB-Audio - ReSpeaker XVF3800\n",
        pcm_reader=lambda: "02-00: USB Audio : USB Audio : playback 0 : capture 1\n",
    )

    assert probe.check().state is StatusState.HEALTHY


def test_microphone_absent_when_configured_capture_pcm_is_missing() -> None:
    probe = AlsaCaptureProbe(
        "plughw:CARD=Array,DEV=0",
        cards_reader=lambda: " 2 [Array          ]: USB-Audio - ReSpeaker XVF3800\n",
        pcm_reader=lambda: "02-01: USB Audio : USB Audio : playback 1 : capture 0\n",
    )

    result = probe.check()

    assert result.state is StatusState.UNAVAILABLE
    assert "capture PCM" in (result.detail or "")


def test_start_schedules_without_running_blocking_probes_on_caller() -> None:
    internet = ScriptedProbe(ProbeResult(StatusState.HEALTHY))
    forge = ScriptedProbe(ProbeResult(StatusState.HEALTHY))
    microphone = ScriptedProbe(ProbeResult(StatusState.HEALTHY))
    scheduler = ManualScheduler()
    monitor = StatusMonitorService(
        internet,
        forge,
        microphone,
        scheduler,
        interval_s=15.0,
    )

    snapshot = monitor.start()

    assert snapshot.internet.state is StatusState.STARTING
    assert internet.check_count == 0
    assert forge.check_count == 0
    assert microphone.check_count == 0
    assert scheduler.interval_s == 15.0


def test_status_transitions_propagate_and_single_internet_failure_does_not_flicker() -> None:
    internet = ScriptedProbe(
        ProbeResult(StatusState.HEALTHY),
        ProbeResult(StatusState.UNAVAILABLE, "packet loss"),
        ProbeResult(StatusState.UNAVAILABLE, "offline"),
        ProbeResult(StatusState.HEALTHY),
    )
    forge = ScriptedProbe(*[ProbeResult(StatusState.HEALTHY)] * 4)
    microphone = ScriptedProbe(*[ProbeResult(StatusState.HEALTHY)] * 4)
    scheduler = ManualScheduler()
    monitor = StatusMonitorService(internet, forge, microphone, scheduler)
    monitor.start()

    scheduler.fire()
    assert monitor.latest_state.internet.state is StatusState.HEALTHY

    scheduler.fire()
    assert monitor.latest_state.internet.state is StatusState.HEALTHY

    scheduler.fire()
    assert monitor.latest_state.internet.state is StatusState.UNAVAILABLE

    scheduler.fire()
    assert monitor.latest_state.internet.state is StatusState.HEALTHY


def test_probe_exception_becomes_unavailable_without_stopping_monitor() -> None:
    scheduler = ManualScheduler()
    monitor = StatusMonitorService(
        ScriptedProbe(RuntimeError("probe exploded")),
        ScriptedProbe(ProbeResult(StatusState.HEALTHY)),
        ScriptedProbe(ProbeResult(StatusState.HEALTHY)),
        scheduler,
    )
    monitor.start()

    scheduler.fire()

    assert monitor.latest_state.internet.state is StatusState.UNAVAILABLE
    assert monitor.latest_state.internet.detail == "probe exploded"
    assert monitor.is_running


def test_stop_cancels_future_checks() -> None:
    internet = ScriptedProbe(ProbeResult(StatusState.HEALTHY))
    scheduler = ManualScheduler()
    monitor = StatusMonitorService(
        internet,
        ScriptedProbe(ProbeResult(StatusState.HEALTHY)),
        ScriptedProbe(ProbeResult(StatusState.HEALTHY)),
        scheduler,
    )
    monitor.start()

    monitor.stop()
    scheduler.fire()

    assert not monitor.is_running
    assert internet.check_count == 0
    assert scheduler.poll is not None
    assert scheduler.poll.cancelled
