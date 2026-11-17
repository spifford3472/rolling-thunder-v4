"""Fail-closed pinned-release/process binding checks, without production access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-runtime-identity.py"
SPEC = importlib.util.spec_from_file_location("rt_runtime_identity", SOURCE)
assert SPEC and SPEC.loader
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)
SHA = "a" * 40


def _artifact(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "releases"
    root.mkdir(mode=0o700)
    release = root / SHA
    release.mkdir(mode=0o700)
    for name in ("src/rolling_thunder", "deploy", ".venv/bin", "config"):
        (release / name).mkdir(parents=True, mode=0o700)
    sources = {
        "src/rolling_thunder/ui_main.py": b"# trusted UI code\n",
        "deploy/rolling-thunder-autostart": b"#!/bin/sh\n",
        ".venv/bin/python": b"fixture binary",
        ".venv/bin/rolling-thunder-ui": b"#!/usr/bin/env python\n",
        "pyproject.toml": b"[project]\n",
        "config/rolling-thunder.yaml": b"station: test\n",
    }
    for name, content in sources.items():
        (release / name).write_bytes(content)
    manifest = {
        "sha": SHA,
        "files": {key: hashlib.sha256(content).hexdigest() for key, content in sources.items()},
    }
    (release / "release-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return release, tmp_path


def _proc(tmp_path: Path, release: Path) -> Path:
    proc = tmp_path / "proc"
    process = proc / "1234"
    process.mkdir(parents=True)
    (process / "cgroup").write_text("0::/system.slice/rolling-thunder.service\n", encoding="utf-8")
    (process / "cwd").symlink_to(release, target_is_directory=True)
    (process / "cmdline").write_bytes(
        (f"{release}/.venv/bin/python\0-I\0-B\0{release}/.venv/bin/rolling-thunder-ui\0").encode()
    )
    (process / "exe").symlink_to(release / ".venv/bin/python")
    (process / "stat").write_bytes(b"1234 (python with spaces) S " + b"0 " * 18 + b"987654 0\n")
    boot = proc / "sys/kernel/random/boot_id"
    boot.parent.mkdir(parents=True)
    boot.write_text("01234567-89ab-cdef-0123-456789abcdef\n", encoding="ascii")
    return proc


def _inspect(tmp_path: Path, release: Path, proc: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(identity.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.getuid()))
    heartbeat = tmp_path / "runtime/ready.json"
    heartbeat.parent.mkdir(mode=0o700)
    heartbeat.write_text(
        json.dumps(
            {
                "pid": 1234,
                "time": 1000.0,
                "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
                "start_ticks": 987654,
                "release_sha": SHA,
            }
        ),
        encoding="utf-8",
    )
    heartbeat.chmod(0o600)
    return identity.inspect(
        artifact=release,
        expected_sha=SHA,
        proc_root=proc,
        trusted_uid=os.getuid(),
        trusted_anchor=tmp_path,
        heartbeat_path=heartbeat,
        boot_id_path=proc / "sys/kernel/random/boot_id",
        now=1001.0,
        service={
            "ActiveState": "active",
            "MainPID": "1234",
            "User": "geoff",
            "ControlGroup": "/system.slice/rolling-thunder.service",
        },
    )


def test_protected_release_process_identity_binds_tk_readiness_without_memory_claim(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, anchor = _artifact(tmp_path)
    proc = _proc(tmp_path, release)
    result = _inspect(anchor, release, proc, monkeypatch)
    assert result["state"] == "protected_release_process_and_readiness_verified"
    assert result["release"]["files_checked"] == 6
    assert result["loaded_python_bytes_independently_proven"] is False
    assert result["protected_release_process_identity_verified"] is True
    assert result["verification_method"] == (
        "protected_release_hashes_exact_exec_path_pid_boot_start_ticks_and_tk_heartbeat"
    )
    assert result["disposition"] == "protected_release_identity_verified"


@pytest.mark.parametrize(
    "scenario",
    [
        "modified_source",
        "untracked_python",
        "symlink_import",
        "writable_release",
        "wrong_sha",
        "wrong_cgroup",
        "wrong_entrypoint",
        "wrong_executable",
        "no_isolation",
        "wrong_cwd",
        "wrong_pid",
        "extra_venv_file",
        "missing_manifest",
    ],
)
def test_untrusted_release_or_process_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    release, anchor = _artifact(tmp_path)
    proc = _proc(tmp_path, release)
    if scenario == "modified_source":
        (release / "src/rolling_thunder/ui_main.py").write_text("malicious", encoding="utf-8")
    elif scenario == "untracked_python":
        (release / "src/rolling_thunder/rogue.py").write_text("raise Exception", encoding="utf-8")
    elif scenario == "symlink_import":
        source = release / "src/rolling_thunder/ui_main.py"
        source.unlink()
        source.symlink_to(release / "pyproject.toml")
    elif scenario == "writable_release":
        release.chmod(0o770)
    elif scenario == "wrong_sha":
        release.rename(release.parent / ("b" * 40))
        release = release.parent / ("b" * 40)
    elif scenario == "wrong_cgroup":
        (proc / "1234/cgroup").write_text("0::/user.slice/other\n", encoding="utf-8")
    elif scenario == "wrong_entrypoint":
        (proc / "1234/cmdline").write_bytes(b"/bin/true\0")
    elif scenario == "wrong_executable":
        (proc / "1234/exe").unlink()
        (proc / "1234/exe").symlink_to("/bin/true")
    elif scenario == "no_isolation":
        (proc / "1234/cmdline").write_bytes(
            f"{release}/.venv/bin/python\0{release}/.venv/bin/rolling-thunder-ui\0".encode()
        )
    elif scenario == "wrong_cwd":
        (proc / "1234/cwd").unlink()
        (proc / "1234/cwd").symlink_to(tmp_path, target_is_directory=True)
    elif scenario == "wrong_pid":
        (proc / "1234").rename(proc / "9999")
    elif scenario == "extra_venv_file":
        (release / ".venv/bin/injected.pth").write_text("/tmp/rogue", encoding="utf-8")
    elif scenario == "missing_manifest":
        (release / "release-manifest.json").unlink()
    report = _inspect(anchor, release, proc, monkeypatch)
    assert report["state"] == "unverified"
    assert report["loaded_python_bytes_independently_proven"] is False
    assert report["protected_release_process_identity_verified"] is False
    assert report["disposition"] == "blocked_manual_review"


def test_protected_release_checks_full_inventory_and_sha(
    tmp_path: Path,
) -> None:
    release, anchor = _artifact(tmp_path)
    assert (
        identity.protected_release(release, expected_sha=SHA, uid=os.getuid(), anchor=anchor)[
            "state"
        ]
        == "protected_artifact_matches_manifest"
    )
    manifest = release / "release-manifest.json"
    record = json.loads(manifest.read_text(encoding="utf-8"))
    record["sha"] = "b" * 40
    manifest.write_text(json.dumps(record), encoding="utf-8")
    assert (
        identity.protected_release(release, expected_sha=SHA, uid=os.getuid(), anchor=anchor)[
            "state"
        ]
        == "unverified"
    )


def test_cli_returns_success_only_when_protected_process_identity_is_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI accepts only complete disk, process and UI identity evidence."""
    release, _anchor = _artifact(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["identity", "--artifact", str(release), "--sha", SHA]
    )
    monkeypatch.setattr(
        identity,
        "inspect",
        lambda **_kwargs: {
            "state": "protected_release_process_and_readiness_verified",
            "loaded_python_bytes_independently_proven": False,
            "protected_release_process_identity_verified": True,
            "disposition": "protected_release_identity_verified",
        },
    )
    assert identity.main() == 0
    assert "protected_release_identity_verified" in capsys.readouterr().out


@pytest.mark.parametrize(
    "field,value",
    [
        ("start_ticks", 1),
        ("boot_id", "fedcba98-7654-3210-fedc-ba9876543210"),
        ("release_sha", "b" * 40),
        ("time", 900.0),
    ],
)
def test_stale_or_mismatched_process_heartbeat_refuses_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    release, _anchor = _artifact(tmp_path)
    proc = _proc(tmp_path, release)
    heartbeat = tmp_path / "runtime/ready.json"
    heartbeat.parent.mkdir(mode=0o700)
    record = {
        "pid": 1234,
        "time": 1000.0,
        "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
        "start_ticks": 987654,
        "release_sha": SHA,
    }
    record[field] = value
    heartbeat.write_text(json.dumps(record), encoding="utf-8")
    heartbeat.chmod(0o600)
    monkeypatch.setattr(identity.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.getuid()))
    result = identity.inspect(
        artifact=release,
        expected_sha=SHA,
        proc_root=proc,
        trusted_uid=os.getuid(),
        operator_user="geoff",
        trusted_anchor=tmp_path,
        heartbeat_path=heartbeat,
        boot_id_path=proc / "sys/kernel/random/boot_id",
        now=1001.0,
    )
    assert result["protected_release_process_identity_verified"] is False
