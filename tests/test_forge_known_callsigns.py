"""Durability, privacy, admin safety, and reusable directory HTTP contracts."""

import json
import re
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

import pytest
from pydantic import ValidationError

from rolling_thunder.forge_callsign_info_api import ForgeCallsignInfoApiApplication
from rolling_thunder.forge_known_callsigns import ForgeKnownCallsignRepository
from rolling_thunder.known_callsigns import KnownCallsignBatch, KnownCallsignInput


@pytest.fixture
def repository(tmp_path: Path) -> ForgeKnownCallsignRepository:
    return ForgeKnownCallsignRepository(tmp_path / "state" / "friends.sqlite3")


def test_repository_crud_normalization_restart_and_timestamps(
    repository: ForgeKnownCallsignRepository,
) -> None:
    data = KnownCallsignInput(
        callsign=" w1abc ", comment="private\nsecond line", display_name="Friend"
    )
    repository.save(data)
    reopened = ForgeKnownCallsignRepository(repository.path)
    first = reopened.list_records()[0]
    assert first.data.callsign == "W1ABC"
    assert first.data.comment == "private\nsecond line"
    assert first.created_at == first.updated_at
    assert reopened.snapshot().entries[0].relationship == "friend"
    reopened.save(data.model_copy(update={"active": False}), original="w1abc")
    updated = reopened.list_records()[0]
    assert updated.created_at == first.created_at
    assert updated.updated_at >= first.updated_at
    assert reopened.snapshot().entries == ()
    reopened.save(KnownCallsignInput(callsign="W2ABC", comment="edited"), original="w1abc")
    assert reopened.list_records()[0].data.comment == "edited"
    reopened.delete("w2abc")
    assert reopened.list_records() == ()


def test_normalized_collision_does_not_overwrite_comment(
    repository: ForgeKnownCallsignRepository,
) -> None:
    repository.save(KnownCallsignInput(callsign="W1ABC", comment="preserve"))
    with pytest.raises(ValueError, match="already exists"):
        repository.save(KnownCallsignInput(callsign=" w1abc ", comment="overwrite"))
    assert repository.list_records()[0].data.comment == "preserve"


@pytest.mark.parametrize(
    "data",
    [
        {"callsign": ""},
        {"callsign": "not a call"},
        {"callsign": "W1ABC", "active": "yes"},
        {"callsign": "W1ABC", "comment": "x" * 4001},
    ],
)
def test_invalid_record_data_rejected(data: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        KnownCallsignInput.model_validate(data)


def test_schema_initialization_and_future_version_rejection(
    repository: ForgeKnownCallsignRepository,
) -> None:
    with sqlite3.connect(repository.path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
        connection.execute("PRAGMA user_version=99")
    with pytest.raises(ValueError, match="schema"):
        ForgeKnownCallsignRepository(repository.path)


def app(repository: ForgeKnownCallsignRepository) -> ForgeCallsignInfoApiApplication:
    # Directory routes must never invoke QRZ/Wavelog providers.
    return ForgeCallsignInfoApiApplication(object(), known_callsigns=repository)  # type: ignore[arg-type]


def form_session(application: ForgeCallsignInfoApiApplication) -> tuple[str, dict[str, str]]:
    response = application.handle("GET", "/admin/known-callsigns")
    assert response.status_code == 200
    token = re.search(r'name="csrf" value="([^"]+)"', response.body.decode()).group(1)
    cookie = dict(response.headers)["Set-Cookie"].split(";")[0]
    return token, {"Cookie": cookie, "Host": "forge:8788", "Origin": "http://forge:8788"}


def test_admin_add_edit_deactivate_reactivate_delete_and_private_comments(
    repository: ForgeKnownCallsignRepository,
) -> None:
    application = app(repository)
    token, headers = form_session(application)

    def post(fields: dict[str, str], target: str = "/admin/known-callsigns") -> int:
        return application.handle(
            "POST", target, headers=headers, body=urlencode({"csrf": token, **fields}).encode()
        ).status_code

    fields = {
        "callsign": "w1abc",
        "display_name": "<Friend>",
        "comment": "<script>private</script>\nline",
        "active": "true",
    }
    assert post(fields) == 303
    html = application.handle("GET", "/admin/known-callsigns", headers=headers).body.decode()
    assert "&lt;script&gt;private&lt;/script&gt;" in html
    assert "<script>" not in html
    assert "&lt;Friend&gt;" in html
    assert post({**fields, "original": "W1ABC", "active": ""}) == 303
    assert repository.snapshot().entries == ()
    assert post({**fields, "original": "W1ABC", "comment": "edited", "display_name": "Name"}) == 303
    assert len(repository.snapshot().entries) == 1
    assert repository.list_records()[0].data.comment == "edited"
    confirmation = application.handle(
        "GET", "/admin/known-callsigns/delete?callsign=W1ABC", headers=headers
    )
    assert b"Confirm deletion" in confirmation.body
    assert len(repository.list_records()) == 1
    assert post({"callsign": "W1ABC"}, "/admin/known-callsigns/delete") == 400
    assert post({"callsign": "W1ABC", "confirm": "delete"}, "/admin/known-callsigns/delete") == 303
    assert repository.list_records() == ()


def test_admin_rejects_missing_token_cross_origin_and_malformed_fields(
    repository: ForgeKnownCallsignRepository,
) -> None:
    application = app(repository)
    assert (
        application.handle("POST", "/admin/known-callsigns", body=b"callsign=W1ABC").status_code
        == 403
    )
    token, headers = form_session(application)
    body = urlencode({"csrf": token, "callsign": "W1ABC"}).encode()
    assert (
        application.handle(
            "POST",
            "/admin/known-callsigns",
            body=body,
            headers={**headers, "Origin": "http://attacker"},
        ).status_code
        == 403
    )
    assert (
        application.handle(
            "POST", "/admin/known-callsigns", body=body + b"&callsign=W2ABC", headers=headers
        ).status_code
        == 400
    )
    assert (
        application.handle(
            "POST", "/admin/known-callsigns", body=b"x" * 32769, headers=headers
        ).status_code
        == 413
    )
    assert repository.list_records() == ()


def test_batch_normalizes_deduplicates_and_never_exposes_admin_data(
    repository: ForgeKnownCallsignRepository,
) -> None:
    repository.save(
        KnownCallsignInput(callsign="W1ABC", comment="TOP-PRIVATE", display_name="Private label")
    )
    repository.save(KnownCallsignInput(callsign="W2ABC", active=False))
    application = app(repository)
    response = application.handle(
        "POST", "/api/v1/known-callsigns", body=b'{"callsigns":["w1abc","W3ABC","W2ABC"," W1ABC "]}'
    )
    assert response.status_code == 200
    assert json.loads(response.body)["results"] == [
        {"callsign": "W1ABC", "known": True, "relationship": "friend"},
        {"callsign": "W3ABC", "known": False, "relationship": None},
        {"callsign": "W2ABC", "known": False, "relationship": None},
    ]
    snapshot = application.handle("GET", "/api/v1/known-callsigns")
    assert len(json.loads(snapshot.body)["entries"]) == 1
    for result in (response, snapshot):
        assert b"TOP-PRIVATE" not in result.body and b"Private label" not in result.body
        assert b"comment" not in result.body and b"created_at" not in result.body


@pytest.mark.parametrize(
    "body",
    [
        b"[]",
        b"{}",
        b"not json",
        b'{"callsigns":[]}',
        b'{"callsigns":["bad"]}',
        b'{"callsigns":["W1ABC"],"comment":"x"}',
    ],
)
def test_batch_rejects_malformed_request(
    repository: ForgeKnownCallsignRepository, body: bytes
) -> None:
    assert app(repository).handle("POST", "/api/v1/known-callsigns", body=body).status_code == 400


def test_batch_limit(repository: ForgeKnownCallsignRepository) -> None:
    with pytest.raises(ValidationError):
        KnownCallsignBatch(callsigns=tuple("W1ABC" for _ in range(129)))
    assert (
        app(repository)
        .handle(
            "POST",
            "/api/v1/known-callsigns",
            body=json.dumps({"callsigns": ["W1ABC"] * 129}).encode(),
        )
        .status_code
        == 400
    )


def test_admin_search_and_edit_escape(repository: ForgeKnownCallsignRepository) -> None:
    repository.save(KnownCallsignInput(callsign="W1ABC", comment="</textarea><script>x</script>"))
    repository.save(KnownCallsignInput(callsign="W2ABC"))
    application = app(repository)
    html = application.handle("GET", "/admin/known-callsigns?callsign=W1ABC&search=W1").body
    assert b"W2ABC" not in html
    assert b"&lt;/textarea&gt;&lt;script&gt;" in html
    assert b"</textarea><script>" not in html


def test_disabled_directory_keeps_existing_health() -> None:
    application = ForgeCallsignInfoApiApplication(object())  # type: ignore[arg-type]
    assert application.handle("GET", "/health").status_code == 200
    assert application.handle("GET", "/api/v1/known-callsigns").status_code == 503


def test_directory_limit_does_not_truncate_public_snapshot(
    repository: ForgeKnownCallsignRepository, monkeypatch
) -> None:
    monkeypatch.setattr("rolling_thunder.forge_known_callsigns.MAX_KNOWN_CALLSIGNS", 1)
    repository.save(KnownCallsignInput(callsign="W1ABC"))
    with pytest.raises(ValueError, match="full"):
        repository.save(KnownCallsignInput(callsign="W2ABC"))
    repository.save(KnownCallsignInput(callsign="W2ABC"), original="W1ABC")
    assert repository.snapshot().entries[0].callsign == "W2ABC"


def test_directory_error_is_503_and_does_not_break_health(
    repository: ForgeKnownCallsignRepository,
) -> None:
    application = app(repository)
    repository.path.unlink()
    assert application.handle("GET", "/api/v1/known-callsigns").status_code == 503
    assert application.handle("GET", "/health").status_code == 200


def test_live_http_handler_reads_bounded_post_body(
    repository: ForgeKnownCallsignRepository,
) -> None:
    from http.client import HTTPConnection
    from http.server import ThreadingHTTPServer
    from threading import Thread

    from rolling_thunder.forge_callsign_info_api import make_forge_callsign_info_handler

    repository.save(KnownCallsignInput(callsign="W1ABC", comment="private"))
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_forge_callsign_info_handler(app(repository))
    )
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        connection = HTTPConnection(*server.server_address, timeout=2)
        connection.request(
            "POST",
            "/api/v1/known-callsigns",
            body=b'{"callsigns":["W1ABC"]}',
            headers={"Content-Type": "application/json"},
        )
        response = connection.getresponse()
        assert response.status == 200
        assert b"private" not in response.read()
        connection.close()
        connection = HTTPConnection(*server.server_address, timeout=2)
        connection.request(
            "POST", "/api/v1/known-callsigns", body=b"", headers={"Content-Length": "40000"}
        )
        response = connection.getresponse()
        assert response.status == 413
        response.read()
        connection.close()
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_admin_rejects_nonascii_form_token_and_cookie_without_crashing(
    repository: ForgeKnownCallsignRepository,
) -> None:
    application = app(repository)
    _, headers = form_session(application)
    assert (
        application.handle(
            "POST",
            "/admin/known-callsigns",
            headers=headers,
            body=urlencode({"csrf": "é", "callsign": "W1ABC"}).encode(),
        ).status_code
        == 403
    )
    assert (
        application.handle(
            "GET", "/admin/known-callsigns", headers={"Cookie": "known_csrf=" + "a" * 64 + ".é"}
        ).status_code
        == 200
    )
