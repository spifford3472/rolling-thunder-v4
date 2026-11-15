"""Deterministic x86 checks for the hardware-neutral ARM64 Tk test harness."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

DEPLOY = Path(__file__).resolve().parents[1] / "deploy"
SPEC = importlib.util.spec_from_file_location(
    "rt_stab07h_runner", DEPLOY / "rolling-thunder-arm64-tk-runner.py"
)
assert SPEC and SPEC.loader
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def _valid_record(mode: str = "normal") -> dict[str, object]:
    errors = {
        "normal": [],
        "runtime-error": ["application runtime"],
        "peripheral-error": ["peripheral_one"],
        "delayed-cleanup": [],
    }
    return {
        "mode": mode,
        "readiness_fresh": True,
        "stale_heartbeat_rejected": True,
        "sigterm_received": True,
        "close_started": True,
        "close_finished": True,
        "close_worker_count": 1,
        "ordered_fake_steps": ["runtime", "peripheral_one", "peripheral_two"],
        "cleanup_errors": errors[mode],
        "post_shutdown_operator_commands": [],
        "native_arm64_display": ":95",
        "actual_tk_loop_entered": True,
        "no_real_dashboard_startup": True,
        "radio_or_ptt_tested": False,
        "production_ready": False,
        "loaded_python_bytes_independently_proven": False,
    }


@pytest.mark.parametrize("mode", ("normal", "runtime-error", "peripheral-error", "delayed-cleanup"))
def test_only_complete_mock_lifecycle_passes(mode: str) -> None:
    assert runner.validate_report(_valid_record(mode), mode)


@pytest.mark.parametrize(
    "mutation",
    [
        {"readiness_fresh": False},
        {"stale_heartbeat_rejected": False},
        {"sigterm_received": False},
        {"close_started": False},
        {"close_finished": False},
        {"close_worker_count": 2},
        {"ordered_fake_steps": ["peripheral_one", "runtime", "peripheral_two"]},
        {"cleanup_errors": ["suppressed"]},
        {"post_shutdown_operator_commands": ["accepted"]},
        {"native_arm64_display": ":0"},
        {"actual_tk_loop_entered": False},
        {"no_real_dashboard_startup": False},
        {"radio_or_ptt_tested": True},
        {"production_ready": True},
        {"loaded_python_bytes_independently_proven": True},
    ],
)
def test_forged_completion_or_safety_claim_refused(mutation: dict[str, object]) -> None:
    result = _valid_record()
    result.update(mutation)
    assert not runner.validate_report(result, "normal")


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setattr(runner, "WORKSPACES_PARENT", tmp_path)
    root = tmp_path / "arm64"
    root.mkdir(mode=0o700)
    display_parent = tmp_path / "display-root"
    display_parent.mkdir(mode=0o700)
    display = display_parent / "display"
    display.mkdir(mode=0o700)
    (display_parent / "scratch").mkdir(mode=0o700)
    binpath = display_parent / "tools/usr/bin/Xvfb"
    binpath.parent.mkdir(parents=True)
    binpath.write_bytes(b"isolated fake xvfb")
    monkeypatch.setattr(
        runner, "XVFB_EXECUTABLE_SHA256", hashlib.sha256(binpath.read_bytes()).hexdigest()
    )
    (root / "runtime").mkdir()
    test_script = root / "runtime/tk-lifecycle.py"
    test_script.write_bytes((DEPLOY / "rolling-thunder-arm64-tk-lifecycle.py").read_bytes())
    monkeypatch.setattr(
        runner,
        "_load_sandbox",
        lambda: SimpleNamespace(
            command=lambda *_a, **_kw: [
                "/usr/bin/bwrap",
                "--unshare-user",
                "--unshare-pid",
                "--unshare-net",
                "--die-with-parent",
                "--ro-bind",
                str(root / "sysroot"),
                "/",
                "--ro-bind",
                str(root / "runtime"),
                "/work",
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                "/tmp",
                "--clearenv",
                "--setenv",
                "PATH",
                "/usr/bin:/bin",
                "--chdir",
                "/work",
                "--",
                "/usr/bin/qemu-aarch64-static",
                "-L",
                "/",
                "/work/venv/bin/python3.13",
                "-I",
                "-B",
                "/work/native-smoke.py",
            ]
        ),
    )
    return root, display


def test_fixed_lifecycle_sandbox_mounts_and_private_xvfb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, display = _fixture(tmp_path, monkeypatch)
    cmd = runner.guest_command(root, display, "normal")
    assert "--unshare-net" in cmd
    assert "--share-net" not in cmd
    assert "--bind" in cmd and "--ro-bind" in cmd
    assert cmd[-5:] == ["--mode", "normal", "--scratch", "/test"][-5:] or cmd[-4:] == [
        "--mode",
        "normal",
        "--scratch",
        "/test",
    ]
    assert "/work/tk-lifecycle.py" in cmd
    assert "--setenv" in cmd and "DISPLAY" in cmd and "XAUTHORITY" in cmd
    assert "/home/geoff" not in " ".join(cmd)
    xvfb = runner.xvfb_command(display)
    assert "--unshare-net" in xvfb
    assert (
        xvfb[-7:] == ["-nolisten", "tcp", "-extension", "GLX", "-screen", "0", "1280x720x24"][-7:]
    )
    assert "-auth" in xvfb


def test_tampered_probe_and_unapproved_mode_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, display = _fixture(tmp_path, monkeypatch)
    (root / "runtime/tk-lifecycle.py").write_text("not the reviewed code")
    with pytest.raises(runner.TkLifecycleError, match="differs"):
        runner.guest_command(root, display, "normal")
    with pytest.raises(runner.TkLifecycleError, match="unsupported"):
        runner.guest_command(root, display, "actual-dashboard-startup")


def test_untrusted_display_and_executable_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _root, display = _fixture(tmp_path, monkeypatch)
    display.chmod(0o777)
    with pytest.raises(runner.TkLifecycleError, match="private"):
        runner.xvfb_command(display)
    display.chmod(0o700)
    (display.parent / "tools/usr/bin/Xvfb").write_bytes(b"replaced binary")
    with pytest.raises(runner.TkLifecycleError, match="unverified"):
        runner.xvfb_command(display)


def test_stalled_worker_is_never_mistaken_for_completed_shutdown() -> None:
    record = _valid_record()
    record.update(
        mode="stalled-worker",
        close_finished=False,
        ordered_fake_steps=["runtime", "peripheral_one"],
    )
    assert not runner.validate_report(record, "stalled-worker")
