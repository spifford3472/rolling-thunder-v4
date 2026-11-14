"""Deterministic exact-commit source bundles: no live checkout or radio use."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-release-build.py"
SPEC = importlib.util.spec_from_file_location("rt_release_builder", SOURCE)
assert SPEC and SPEC.loader
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        check=True,
        text=True,
        capture_output=True,
        timeout=5,
    ).stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "src/rolling_thunder").mkdir(parents=True)
    (repo / "deploy").mkdir()
    (repo / "config").mkdir()
    (repo / "src/rolling_thunder/ui_main.py").write_text("# tested source\n")
    (repo / "deploy/rolling-thunder-autostart").write_text("#!/bin/sh\n")
    (repo / "pyproject.toml").write_text("[project]\nname='test'\n")
    (repo / "config/private-token").write_text("NEVER EXPORT THIS SECRET")
    _git(repo, "add", "-A")
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "initial",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    return repo, _git(repo, "rev-parse", "HEAD")


def test_reproducible_source_tar_ignores_worktree_edits_and_secrets(tmp_path: Path) -> None:
    repo, sha = _fixture(tmp_path)
    first, manifest = builder.build_bytes(repo, sha)
    # Worktree edits, even to selected files, cannot change exact Git blob.
    (repo / "src/rolling_thunder/ui_main.py").write_text("malicious, not committed")
    second, other = builder.build_bytes(repo, sha)
    assert first == second
    assert manifest == other
    assert manifest["git_commit"] == sha
    assert manifest["dependencies_pinned"] is False
    assert manifest["runtime_proven"] is False
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(member.name for member in members)
        assert all(member.uid == 0 and member.gid == 0 and member.mtime == 0 for member in members)
        assert "config/private-token" not in archive.getnames()
        assert archive.extractfile("src/rolling_thunder/ui_main.py").read() == b"# tested source\n"
        manifest_file = json.load(archive.extractfile("source-manifest.json"))
        assert manifest_file["source_files"] == manifest["source_files"]
    assert b"NEVER EXPORT THIS SECRET" not in first
    assert hashlib.sha256(first).hexdigest() == hashlib.sha256(second).hexdigest()


def test_wrong_commit_and_invalid_sha_refuse(tmp_path: Path) -> None:
    repo, sha = _fixture(tmp_path)
    with pytest.raises(builder.BuildError):
        builder.build_bytes(repo, "not-a-sha")
    with pytest.raises(builder.BuildError):
        builder.build_bytes(repo, "f" * 40)
    assert len(builder.build_bytes(repo, sha)[0]) > 0


def test_tracked_symlink_under_protected_source_refused(tmp_path: Path) -> None:
    repo, _ = _fixture(tmp_path)
    (repo / "src/rolling_thunder/unsafe.py").symlink_to("../../config/private-token")
    _git(repo, "add", "-A")
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "unsafe",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    with pytest.raises(builder.BuildError, match="symlink"):
        builder.build_bytes(repo, _git(repo, "rev-parse", "HEAD"))


def test_extra_source_file_changes_source_manifest(tmp_path: Path) -> None:
    repo, old = _fixture(tmp_path)
    _, original = builder.build_bytes(repo, old)
    (repo / "src/rolling_thunder/new.py").write_text("print('added')\n")
    _git(repo, "add", "-A")
    subprocess.run(
        [
            "/usr/bin/git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "next",
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    data, changed = builder.build_bytes(repo, _git(repo, "rev-parse", "HEAD"))
    assert changed["source_files"] != original["source_files"]
    assert b"src/rolling_thunder/new.py" in data
