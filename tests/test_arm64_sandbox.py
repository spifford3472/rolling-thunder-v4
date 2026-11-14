"""Prove the QEMU smoke command never exposes host/radio/network access."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-arm64-sandbox.py"
SPEC = importlib.util.spec_from_file_location("rt_arm64_sandbox_runner", SOURCE)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)
PROBE_SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-arm64-native-smoke.py"
PROBE_SPEC = importlib.util.spec_from_file_location("rt_arm64_probe_test", PROBE_SOURCE)
assert PROBE_SPEC and PROBE_SPEC.loader
probe = importlib.util.module_from_spec(PROBE_SPEC)
PROBE_SPEC.loader.exec_module(probe)


def _sandbox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "private-sandbox"
    root.mkdir(mode=0o700)
    qemu = root / "sysroot/usr/bin/qemu-aarch64-static"
    qemu.parent.mkdir(parents=True)
    qemu.write_bytes(b"fixture static qemu")
    python = root / "sysroot/usr/bin/python3.13"
    header = bytearray(20)
    header[:6] = b"\x7fELF\x02\x01"
    header[18:20] = (183).to_bytes(2, "little")
    python.write_bytes(header)
    venv = root / "runtime/venv/bin"
    venv.mkdir(parents=True)
    (venv / "python3.13").symlink_to("/usr/bin/python3.13")
    (root / "runtime/native-smoke.py").write_text("# harmless test script\n")
    monkeypatch.setattr(runner, "QEMU_SHA256", hashlib.sha256(qemu.read_bytes()).hexdigest())
    return root


def test_only_explicit_networkless_readonly_mounts_are_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    argv = runner.command(root, "native-smoke", allowed_parent=tmp_path)
    assert argv[:4] == ["/usr/bin/bwrap", "--unshare-user", "--unshare-pid", "--unshare-net"]
    assert ["--ro-bind", str(root / "sysroot"), "/"] == argv[5:8]
    assert str(root / "runtime") in argv
    assert "--dev" in argv and "/dev" in argv
    assert "--clearenv" in argv
    assert "--bind" not in argv and "--share-net" not in argv
    assert "sudo" not in " ".join(argv)
    assert "/home/geoff" not in " ".join(argv)
    assert argv[-4:] == ["-I", "-B", "/work/native-smoke.py"][-4:] or argv[-3:] == [
        "-I",
        "-B",
        "/work/native-smoke.py",
    ]


def test_wrong_qemu_hash_or_architecture_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    qemu = root / "sysroot/usr/bin/qemu-aarch64-static"
    qemu.write_bytes(b"modified qemu")
    with pytest.raises(runner.SandboxError, match="hash"):
        runner.command(root, "native-smoke", allowed_parent=tmp_path)
    monkeypatch.setattr(runner, "QEMU_SHA256", hashlib.sha256(qemu.read_bytes()).hexdigest())
    python = root / "sysroot/usr/bin/python3.13"
    header = bytearray(python.read_bytes())
    header[18:20] = (62).to_bytes(2, "little")
    python.write_bytes(header)
    with pytest.raises(runner.SandboxError, match="AArch64"):
        runner.command(root, "native-smoke", allowed_parent=tmp_path)


def test_private_root_and_action_allowlist_fail_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    root.chmod(0o755)
    with pytest.raises(runner.SandboxError, match="private"):
        runner.command(root, "native-smoke", allowed_parent=tmp_path)
    root.chmod(0o700)
    with pytest.raises(runner.SandboxError, match="unsupported"):
        runner.command(root, "shell", allowed_parent=tmp_path)
    alias = tmp_path / "shortcut"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(runner.SandboxError, match="unapproved"):
        runner.command(alias, "native-smoke", allowed_parent=tmp_path)


def test_guest_report_never_authorizes_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _sandbox(tmp_path, monkeypatch)
    safe = {
        "machine": "aarch64",
        "python": "3.13.5",
        "interfaces": ["lo"],
        "radio_or_audio_devices_visible": False,
        "import_tests_passed": True,
        "ui_started": False,
        "production_ready": False,
    }
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=json.dumps(safe)),
    )
    assert runner.run(root, "native-smoke", allowed_parent=tmp_path)["production_ready"] is False
    unsafe = dict(safe, production_ready=True)
    monkeypatch.setattr(
        runner.subprocess,
        "run",
        lambda *_a, **_kw: SimpleNamespace(returncode=0, stdout=json.dumps(unsafe)),
    )
    with pytest.raises(runner.SandboxError, match="did not establish"):
        runner.run(root, "native-smoke", allowed_parent=tmp_path)


def test_probe_imports_require_actual_distribution_modules() -> None:
    assert "serial_asyncio_fast" in probe.IMPORTS
    assert "cayennelpp" in probe.IMPORTS
    assert "vosk" in probe.IMPORTS
    assert "_tkinter" in probe.IMPORTS
    assert "rolling_thunder" in probe.IMPORTS
    assert "serial_asyncio" not in probe.IMPORTS
