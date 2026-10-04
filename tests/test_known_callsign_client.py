"""Bounded Pi cache, transport validation, and background-only polling tests."""

import json
from threading import Event, get_ident

import pytest

from rolling_thunder.http_home_platform import UrllibHttpResponse
from rolling_thunder.known_callsign_client import (
    HttpKnownCallsignClient,
    KnownCallsignCache,
    KnownCallsignClientError,
    KnownCallsignPollingService,
)


class Transport:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes | None]] = []
        self.body = b'{"entries":[{"callsign":"w1abc","known":true,"relationship":"friend"}]}'
        self.status = 200
        self.error: OSError | None = None
        self.threads: list[int] = []
        self.entered = Event()
        self.release: Event | None = None

    def request(self, method, url, *, headers, body, timeout_s):
        self.calls.append((method, url, body))
        self.threads.append(get_ident())
        self.entered.set()
        if self.release is not None:
            assert self.release.wait(timeout=2)
        if self.error:
            raise self.error
        return UrllibHttpResponse(self.status, self.body)


def test_batch_client_normalizes_and_deduplicates_reply_contract() -> None:
    transport = Transport()
    transport.body = b'{"results":[{"callsign":"W1ABC","known":true,"relationship":"friend"}]}'
    result = HttpKnownCallsignClient("http://forge:8788", transport=transport).lookup(
        ("w1abc", "W1ABC")
    )
    assert result.results[0].known
    method, url, body = transport.calls[0]
    assert method == "POST" and url.endswith("/api/v1/known-callsigns")
    assert json.loads(body)["callsigns"] == ["W1ABC", "W1ABC"]


def test_cache_refresh_replaces_data_expires_and_clears_on_failure() -> None:
    transport = Transport()
    clock = [1.0]
    cache = KnownCallsignCache(
        HttpKnownCallsignClient("http://forge", transport=transport),
        stale_after_s=30,
        clock=lambda: clock[0],
    )
    assert cache.friends == frozenset()
    cache.refresh()
    assert cache.friends == frozenset({"W1ABC"})
    for _ in range(100):
        assert "W1ABC" in cache.friends
    assert len(transport.calls) == 1
    clock[0] = 31
    assert cache.friends == frozenset()
    transport.body = b'{"entries":[{"callsign":"W2ABC","known":true,"relationship":"friend"}]}'
    cache.refresh()
    assert cache.friends == frozenset({"W2ABC"})
    transport.error = OSError("offline")
    cache.refresh()
    assert cache.friends == frozenset() and cache.error is not None


@pytest.mark.parametrize(
    "body",
    [
        b"bad",
        b"{}",
        b'{"entries":[{"callsign":"W1ABC","known":false}]}',
        b'{"entries":[{"callsign":"W1ABC","known":true,"relationship":"friend","comment":"private"}]}',
        b'{"entries":[{"callsign":"W1ABC","known":"true","relationship":"friend"}]}',
    ],
)
def test_malformed_snapshot_clears_indicator(body: bytes) -> None:
    transport = Transport()
    cache = KnownCallsignCache(HttpKnownCallsignClient("http://forge", transport=transport))
    cache.refresh()
    transport.body = body
    cache.refresh()
    assert cache.friends == frozenset() and cache.error is not None


def test_snapshot_size_and_duplicate_bounds() -> None:
    transport = Transport()
    entry = {"callsign": "W1ABC", "known": True, "relationship": "friend"}
    client = HttpKnownCallsignClient("http://forge", transport=transport)
    for body in (
        json.dumps({"entries": [entry] * 4097}).encode(),
        json.dumps({"entries": [entry, entry]}).encode(),
        b"x" * 524289,
    ):
        transport.body = body
        with pytest.raises(KnownCallsignClientError):
            client.snapshot()


def test_batch_client_rejects_wrong_or_missing_callsign() -> None:
    transport = Transport()
    transport.body = b'{"results":[]}'
    with pytest.raises(KnownCallsignClientError):
        HttpKnownCallsignClient("http://forge", transport=transport).lookup(("W1ABC",))


class Poll:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True


class Scheduler:
    def schedule_repeating(self, interval_s, callback):
        self.poll = Poll(callback)
        return self.poll


def test_polling_does_not_do_http_on_caller_and_bounds_pending_work() -> None:
    transport = Transport()
    transport.release = Event()
    cache = KnownCallsignCache(HttpKnownCallsignClient("http://forge", transport=transport))
    scheduler = Scheduler()
    polling = KnownCallsignPollingService(cache, scheduler)
    caller = get_ident()
    polling.start()
    assert transport.entered.wait(timeout=1)
    for _ in range(100):
        scheduler.poll.callback()
        assert cache.friends == frozenset()
    assert len(transport.calls) == 1 and transport.threads == [transport.threads[0]]
    assert transport.threads[0] != caller
    transport.release.set()
    polling.stop()
    assert scheduler.poll.cancelled
    assert cache.friends == frozenset()
    scheduler.poll.callback()
    assert len(transport.calls) == 1


def test_typed_config_requires_explicit_url_and_bounded_staleness() -> None:
    from pydantic import ValidationError

    from rolling_thunder.config import ForgeConfig, ForgeKnownCallsignClientConfig
    from rolling_thunder.forge_callsign_info_config import KnownCallsignDirectoryConfig

    assert not ForgeKnownCallsignClientConfig().enabled
    for payload in ({"enabled": True}, {"refresh_interval_s": 60, "stale_after_s": 30}):
        with pytest.raises(ValidationError):
            ForgeKnownCallsignClientConfig.model_validate(payload)
    with pytest.raises(ValidationError):
        KnownCallsignDirectoryConfig(database_path="relative.db")
    with pytest.raises(ValidationError):
        ForgeConfig(
            known_callsigns=ForgeKnownCallsignClientConfig(enabled=True, api_url="http://forge")
        )
