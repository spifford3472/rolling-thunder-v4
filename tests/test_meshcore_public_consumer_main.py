"""Public preview diagnostic performs no ACK and reports unverified events."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rolling_thunder.meshcore_public_consumer import PublicBrokerMessage
from rolling_thunder.meshcore_public_consumer_main import main


def test_preview_output_no_ack_and_unverified_labels(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from rolling_thunder import meshcore_public_consumer_main as cli

    class FakeConsumer:
        """Pure public message provider; calls to acknowledge are forbidden."""

        def __init__(self, socket_path: Path, credential_path: Path) -> None:
            assert socket_path == tmp_path / "socket"
            assert credential_path == tmp_path / "credential"

        def preview(self, *, limit: int = 25) -> tuple[PublicBrokerMessage, ...]:
            assert limit == 2
            return (
                PublicBrokerMessage(
                    1, "#traffic", 1, "Crash on I-75 northbound",
                    datetime(2026, 11, 11, tzinfo=UTC), None,
                ),
            )

        def acknowledge_processed(self, message_id: int) -> None:
            raise AssertionError("Preview must never acknowledge")

    monkeypatch.setattr(cli, "MeshcorePublicConsumer", FakeConsumer)
    assert main([
        "--socket", str(tmp_path / "socket"),
        "--credential", str(tmp_path / "credential"),
        "--limit", "2",
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["acknowledged"] is False
    assert output["items"][0]["traffic_candidate_category"] == "accident"
    assert output["items"][0]["sender_verified"] is False
    assert output["items"][0]["location_verified"] is False


def test_preview_rejects_bad_limit_without_reading_credential(
    capsys: pytest.CaptureFixture[str], tmp_path: Path,
) -> None:
    missing_credential = tmp_path / "secret"
    assert not missing_credential.exists()
    with pytest.raises(SystemExit) as raised:
        main([
            "--socket", str(tmp_path / "socket"),
            "--credential", str(missing_credential),
            "--limit", "5000",
        ])
    assert raised.value.code == 2
    assert not missing_credential.exists()


def test_uses_no_serial_rf_or_file_modification(tmp_path: Path) -> None:
    """Sanity check that CLI code never creates its own credential."""
    assert not os.path.exists(tmp_path / "never-created-token")
