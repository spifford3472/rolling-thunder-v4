"""Hardware-free ARM64 wheel compatibility and transport payload regression tests."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import subprocess
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
SHA = "a" * 40
PACKAGES = ("pillow", "pycountry", "pydantic", "pyserial", "pyyaml", "vosk")


def _module(name: str, file: str):
    spec = importlib.util.spec_from_file_location(name, DEPLOY / file)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wheels = _module("rt_test_wheels", "rolling-thunder-wheelhouse.py")
payload = _module("rt_test_payload", "rolling-thunder-release-payload.py")


def _fixture(tmp_path: Path, *, dependency: bool = False) -> tuple[Path, Path]:
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    items: dict[str, dict[str, str]] = {}
    for name in (*PACKAGES, *(("cffi",) if dependency else ())):
        filename = f"{name}-1.0-py3-none-any.whl"
        path = wheelhouse / filename
        with ZipFile(path, "w") as archive:
            meta = f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\nRequires-Python: >=3.13\n"
            if name == "vosk" and dependency:
                meta += "Requires-Dist: cffi>=1.0\n"
            archive.writestr(f"{name}-1.0.dist-info/METADATA", meta)
            archive.writestr(
                f"{name}-1.0.dist-info/WHEEL", "Wheel-Version: 1.0\nTag: py3-none-any\n"
            )
        items[name] = {
            "version": "1.0",
            "file": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    lock = tmp_path / "lock.json"
    lock.write_text(
        json.dumps({"schema": 1, "target": wheels.TARGET, "packages": items}), encoding="utf-8"
    )
    return wheelhouse, lock


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout.strip()


def _source(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    (repo / "src/rolling_thunder").mkdir(parents=True)
    (repo / "deploy").mkdir()
    (repo / "src/rolling_thunder/ui_main.py").write_text("# good code\n", encoding="utf-8")
    (repo / "deploy/rolling-thunder-autostart").write_text("#!/bin/sh\n", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='rolling-thunder'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=example@example.invalid",
        "commit",
        "-qm",
        "first",
    )
    return repo, _git(repo, "rev-parse", "HEAD")


def test_hash_pins_and_dependency_closure_accept_exact_target(tmp_path: Path) -> None:
    wheelhouse, lock = _fixture(tmp_path, dependency=True)
    status = wheels.verify(lock, wheelhouse)
    assert status["packages"] == 7
    assert status["interpreter_included"] is False
    assert status["release_installable"] is False


def test_missing_extra_tampered_or_symlinked_wheel_refused(tmp_path: Path) -> None:
    wheelhouse, lock = _fixture(tmp_path)
    one = wheelhouse / "pillow-1.0-py3-none-any.whl"
    one.write_bytes(one.read_bytes() + b"tampered")
    with pytest.raises(wheels.WheelhouseError, match="hash"):
        wheels.verify(lock, wheelhouse)
    one.unlink()
    with pytest.raises(wheels.WheelhouseError, match="missing"):
        wheels.verify(lock, wheelhouse)
    one.symlink_to(wheelhouse / "pycountry-1.0-py3-none-any.whl")
    with pytest.raises(wheels.WheelhouseError):
        wheels.verify(lock, wheelhouse)


def test_unknown_transitive_dependency_refused(tmp_path: Path) -> None:
    wheelhouse, lock = _fixture(tmp_path, dependency=True)
    records = json.loads(lock.read_text(encoding="utf-8"))
    del records["packages"]["cffi"]
    (wheelhouse / "cffi-1.0-py3-none-any.whl").unlink()
    lock.write_text(json.dumps(records), encoding="utf-8")
    with pytest.raises(wheels.WheelhouseError, match="transitive"):
        wheels.verify(lock, wheelhouse)


def test_incompatible_arm64_wheel_tag_refused(tmp_path: Path) -> None:
    wheelhouse, lock = _fixture(tmp_path)
    original = wheelhouse / "pillow-1.0-py3-none-any.whl"
    renamed = wheelhouse / "pillow-1.0-cp313-cp313-manylinux_2_17_x86_64.whl"
    original.rename(renamed)
    record = json.loads(lock.read_text(encoding="utf-8"))
    record["packages"]["pillow"]["file"] = renamed.name
    lock.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(wheels.WheelhouseError, match="not for CPython"):
        wheels.verify(lock, wheelhouse)


def test_repeated_release_transport_payload_is_identical_and_not_installable(
    tmp_path: Path,
) -> None:
    wheelhouse, lock = _fixture(tmp_path)
    repo, sha = _source(tmp_path)
    first, manifest = payload.build_payload(repo, sha, wheelhouse, lock)
    (repo / "src/rolling_thunder/ui_main.py").write_text(
        "tampered source worktree\n", encoding="utf-8"
    )
    second, unchanged = payload.build_payload(repo, sha, wheelhouse, lock)
    assert first == second
    assert manifest == unchanged
    assert manifest["production_ready"] is False
    assert manifest["interpreter_included"] is False
    with tarfile.open(fileobj=io.BytesIO(first), mode="r:") as archive:
        assert "source.tar" in archive.getnames()
        assert "dependency-lock.json" in archive.getnames()
        assert "release-payload.json" in archive.getnames()
        assert len([x for x in archive.getnames() if x.startswith("wheels/")]) == 6
        assert all(member.mtime == 0 and member.uid == 0 for member in archive.getmembers())


def test_wrong_architecture_elf_in_wheel_rejected(tmp_path: Path) -> None:
    """Wheel filename alone cannot authorize x86 native payloads."""
    wheelhouse, lock = _fixture(tmp_path)
    chosen = wheelhouse / "pillow-1.0-py3-none-any.whl"
    # x86-64 ELF machine (62) hidden inside a generic-tagged wheel.
    with ZipFile(chosen, "a") as archive:
        header = bytearray(20)
        header[:6] = b"\x7fELF\x02\x01"
        header[18:20] = (62).to_bytes(2, "little")
        archive.writestr("pillow/native.so", bytes(header))
    document = json.loads(lock.read_text(encoding="utf-8"))
    document["packages"]["pillow"]["sha256"] = hashlib.sha256(chosen.read_bytes()).hexdigest()
    lock.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(wheels.WheelhouseError, match="AArch64 ELF64"):
        wheels.verify(lock, wheelhouse)


def test_python_path_injection_file_rejected(tmp_path: Path) -> None:
    """A hashed wheel may still carry executable import-path injection."""
    wheelhouse, lock = _fixture(tmp_path)
    chosen = wheelhouse / "vosk-1.0-py3-none-any.whl"
    with ZipFile(chosen, "a") as archive:
        archive.writestr("hijack.pth", "/tmp/untrusted\n")
    document = json.loads(lock.read_text(encoding="utf-8"))
    document["packages"]["vosk"]["sha256"] = hashlib.sha256(chosen.read_bytes()).hexdigest()
    lock.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(wheels.WheelhouseError, match="unsafe wheel member"):
        wheels.verify(lock, wheelhouse)


def test_payload_refuses_tampered_wheel_and_preserves_absent_output(tmp_path: Path) -> None:
    """No transport artifact may be produced from incomplete or altered pins."""
    wheelhouse, lock = _fixture(tmp_path)
    repo, sha = _source(tmp_path)
    (wheelhouse / "vosk-1.0-py3-none-any.whl").write_bytes(b"not the reviewed wheel")
    # The payload loader imports a separate verifier module instance, so use
    # the public ValueError contract rather than private exception identity.
    with pytest.raises(ValueError, match="wheel hash"):
        payload.build_payload(repo, sha, wheelhouse, lock)
    assert not list(tmp_path.glob("*.tar"))
