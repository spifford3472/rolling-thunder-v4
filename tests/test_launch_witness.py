"""Offline signed process-identity observations; no trusted host changes."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

MODULE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-launch-witness.py"
SPEC = importlib.util.spec_from_file_location("rt_test_launch_witness", MODULE)
assert SPEC and SPEC.loader
witness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(witness)
SHA = "a" * 40
BOOT = "aabbccdd-1122-3344-5566-77889900aabb"


def _keys(parent: Path) -> tuple[Path, Path]:
    parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = parent / "private.pem"
    public = parent / "public.pem"
    subprocess.run(
        ["/usr/bin/openssl", "genpkey", "-algorithm", "ED25519", "-out", str(private)],
        check=True,
        capture_output=True,
        timeout=5,
    )
    subprocess.run(
        ["/usr/bin/openssl", "pkey", "-in", str(private), "-pubout", "-out", str(public)],
        check=True,
        capture_output=True,
        timeout=5,
    )
    public.chmod(0o600)
    return private, public


def _sign(document: dict[str, Any], key: Path, path: Path) -> None:
    content = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode()
    intermediate = path.parent / "message.bin"
    intermediate.write_bytes(content)
    signature = subprocess.run(
        [
            "/usr/bin/openssl",
            "pkeyutl",
            "-sign",
            "-rawin",
            "-inkey",
            str(key),
            "-in",
            str(intermediate),
        ],
        capture_output=True,
        check=True,
        timeout=5,
    ).stdout
    record = dict(document)
    record["signature_b64"] = base64.b64encode(signature).decode()
    path.write_text(json.dumps(record), encoding="utf-8")
    path.chmod(0o600)
    intermediate.unlink()


def _fixture(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Path]]:
    signer, public = _keys(tmp_path / "authority")
    directory = tmp_path / "receipts"
    directory.mkdir(mode=0o700)
    receipt = directory / "one.json"
    boot = tmp_path / "boot_id"
    boot.write_text(BOOT + "\n", encoding="ascii")
    root = tmp_path / "proc"
    proc = root / "1234"
    proc.mkdir(parents=True)
    # Linux /proc/PID/stat field 22 is twenty fields after closing comm.
    values = ["S", *("0" for _ in range(18)), "987654", "0"]
    (proc / "stat").write_text("1234 (dashboard operator) " + " ".join(values), encoding="ascii")
    doc: dict[str, Any] = {
        "schema": 1,
        "project": "spifford3472/rolling-thunder-v4",
        "host": "anvilmobile",
        "service": "rolling-thunder.service",
        "sha": SHA,
        "pid": 1234,
        "boot_id": BOOT,
        "start_ticks": 987654,
        "observed_utc": datetime.now(UTC).isoformat(),
    }
    _sign(doc, signer, receipt)
    return doc, {"signer": signer, "public": public, "receipt": receipt, "boot": boot, "proc": root}


def _inspect(paths: dict[str, Path], sha: str = SHA) -> dict[str, Any]:
    return witness.inspect(
        paths["receipt"],
        expected_sha=sha,
        public_key=paths["public"],
        process_root=paths["proc"],
        boot_id_path=paths["boot"],
        trusted_uid=os.geteuid(),
    )


def test_valid_signed_process_start_observation_is_not_loaded_code_proof(tmp_path: Path) -> None:
    _document, paths = _fixture(tmp_path)
    result = _inspect(paths)
    assert result["state"] == "signed_launch_observation_bound_to_live_process"
    assert result["loaded_python_bytes_independently_proven"] is False
    assert result["disposition"] == "blocked_manual_review"


@pytest.mark.parametrize(
    "attack",
    [
        "wrong_boot",
        "reused_pid",
        "wrong_sha",
        "forged_key",
        "corrupt_signature",
        "wrong_host",
        "wrong_project",
        "expired",
        "future",
        "symlink_receipt",
        "loose_receipt",
        "public_key_symlink",
        "key_world_writable",
        "missing_process",
    ],
)
def test_signed_observation_refuses_invalid_evidence(tmp_path: Path, attack: str) -> None:
    document, paths = _fixture(tmp_path)
    if attack == "wrong_boot":
        paths["boot"].write_text("00000000-1111-2222-3333-444444444444")
    elif attack == "reused_pid":
        (paths["proc"] / "1234/stat").write_text("1234 (dashboard) S " + "0 " * 18 + "777777 0")
    elif attack == "wrong_sha":
        document["sha"] = "b" * 40
        _sign(document, paths["signer"], paths["receipt"])
    elif attack == "forged_key":
        private, _public = _keys(tmp_path / "attacker")
        _sign(document, private, paths["receipt"])
    elif attack == "corrupt_signature":
        document["pid"] = 777
        paths["receipt"].write_text(json.dumps({**document, "signature_b64": "00"}))
    elif attack == "wrong_host":
        document["host"] = "forge"
        _sign(document, paths["signer"], paths["receipt"])
    elif attack == "wrong_project":
        document["project"] = "different/project"
        _sign(document, paths["signer"], paths["receipt"])
    elif attack == "expired":
        document["observed_utc"] = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        _sign(document, paths["signer"], paths["receipt"])
    elif attack == "future":
        document["observed_utc"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        _sign(document, paths["signer"], paths["receipt"])
    elif attack == "symlink_receipt":
        old = paths["receipt"].with_suffix(".original")
        paths["receipt"].rename(old)
        paths["receipt"].symlink_to(old)
    elif attack == "loose_receipt":
        paths["receipt"].chmod(0o644)
    elif attack == "public_key_symlink":
        old = paths["public"].with_suffix(".original")
        paths["public"].rename(old)
        paths["public"].symlink_to(old)
    elif attack == "key_world_writable":
        paths["public"].chmod(0o666)
    elif attack == "missing_process":
        (paths["proc"] / "1234/stat").unlink()
    result = _inspect(paths)
    assert result["state"] == "unverified"
    assert result["loaded_python_bytes_independently_proven"] is False


def test_start_tick_parser_handles_spaces_and_detects_invalid() -> None:
    assert witness._start_ticks(b"123 (name with spaces) " + b"S " + b"0 " * 18 + b"42 0") == 42
    with pytest.raises(witness.WitnessError):
        witness._start_ticks(b"invalid")
