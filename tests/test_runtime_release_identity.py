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
    return proc


def _inspect(tmp_path: Path, release: Path, proc: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    monkeypatch.setattr(identity.pwd, "getpwnam", lambda _name: SimpleNamespace(pw_uid=os.getuid()))
    return identity.inspect(
        artifact=release,
        expected_sha=SHA,
        proc_root=proc,
        trusted_uid=os.getuid(),
        trusted_anchor=tmp_path,
        service={
            "ActiveState": "active",
            "MainPID": "1234",
            "User": "geoff",
            "ControlGroup": "/system.slice/rolling-thunder.service",
        },
    )


def test_protected_release_process_path_binding_is_not_loaded_code_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release, anchor = _artifact(tmp_path)
    proc = _proc(tmp_path, release)
    result = _inspect(anchor, release, proc, monkeypatch)
    assert result["state"] == "protected_release_and_process_path_bound"
    assert result["release"]["files_checked"] == 6
    assert result["loaded_python_bytes_independently_proven"] is False
    assert result["disposition"] == "blocked_manual_review"


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


def test_cli_never_returns_success_on_artifact_binding_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A green artifact check is not a release-ready or memory-proof signal."""
    release, _anchor = _artifact(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["identity", "--artifact", str(release), "--sha", SHA]
    )
    monkeypatch.setattr(
        identity,
        "inspect",
        lambda **_kwargs: {
            "state": "protected_release_and_process_path_bound",
            "loaded_python_bytes_independently_proven": False,
            "disposition": "blocked_manual_review",
        },
    )
    assert identity.main() == 75
    assert "blocked_manual_review" in capsys.readouterr().out
