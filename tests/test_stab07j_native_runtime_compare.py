"""STAB-07J: comparison is bounded, read-only and never runtime attestation."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-native-runtime-compare.py"
SPEC = importlib.util.spec_from_file_location("rt_native_provenance", SOURCE)
assert SPEC and SPEC.loader
native = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(native)


def _evidence(data: bytes) -> dict[str, object]:
    """Small deliberately non-authoritative Pi file/dpkg observation."""
    return {
        "schema": 1,
        "host": "anvilmobile",
        "mode": "read_only_sample",
        "python": "3.13.5",
        "soabi": "cpython-313-aarch64-linux-gnu",
        "files": {
            "/usr/bin/python3.13": {
                "sha256": hashlib.sha256(data).hexdigest(),
                "resolved": "/usr/bin/python3.13",
                "size": len(data),
            }
        },
        "packages": {"python3.13": {"version": "3.13.5-2+deb13u4", "arch": "arm64"}},
        "unresolved": [],
        "physical_radio_tested": False,
        "loaded_python_bytes_independently_proven": False,
        "production_ready": False,
    }


def _sysroot(tmp_path: Path, content: bytes) -> tuple[Path, dict[str, object]]:
    root = tmp_path / "guest"
    path = root / "usr/bin/python3.13"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    return root, {
        "target_architecture": "aarch64",
        "production_ready": False,
        "os_package_archives": {"python3.13": {"version": "3.13.5-2+deb13u4"}},
    }


def test_sampled_disk_match_still_never_authorizes_release(tmp_path: Path) -> None:
    evidence = _evidence(b"simulated AArch64 interpreter")
    root, manifest = _sysroot(tmp_path, b"simulated AArch64 interpreter")
    report = native.compare(evidence, sysroot=root, sysroot_manifest=manifest)
    assert report["sampled_disk_parity"] is True
    assert report["file_summary"]["match"] == 1
    assert report["package_summary"]["match"] == 1
    assert report["complete_runtime_closure_proven"] is False
    assert report["distribution_signature_verified"] is False
    assert report["loaded_python_bytes_independently_proven"] is False
    assert report["production_ready"] is False
    assert report["release_decision"] == "NO_GO"


def test_missing_or_changed_binary_refused(tmp_path: Path) -> None:
    evidence = _evidence(b"pi interpreter")
    root, manifest = _sysroot(tmp_path, b"modified interpreter")
    report = native.compare(evidence, sysroot=root, sysroot_manifest=manifest)
    assert report["file_summary"]["mismatch"] == 1
    assert report["sampled_disk_parity"] is False
    (root / "usr/bin/python3.13").unlink()
    report = native.compare(evidence, sysroot=root, sysroot_manifest=manifest)
    assert report["file_summary"]["missing"] == 1
    assert report["sampled_disk_parity"] is False


def test_installed_package_revision_mismatch_is_not_bitwise_parity(tmp_path: Path) -> None:
    evidence = _evidence(b"same bytes")
    root, manifest = _sysroot(tmp_path, b"same bytes")
    manifest["os_package_archives"]["python3.13"]["version"] = "3.13.5-2+deb13u5"
    result = native.compare(evidence, sysroot=root, sysroot_manifest=manifest)
    assert result["file_summary"]["match"] == 1
    assert result["package_summary"]["mismatch"] == 1
    assert result["sampled_disk_parity"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        {"production_ready": True},
        {"loaded_python_bytes_independently_proven": True},
        {"physical_radio_tested": True},
        {"host": "forge"},
        {"schema": "1"},
        {"mode": "approved_release"},
        {"python": "3.13.6"},
        {"unresolved": "untrusted string"},
        {"packages": {}},
        {"files": {}},
    ],
)
def test_forged_or_incomplete_observation_rejected(mutation: dict[str, object]) -> None:
    evidence = _evidence(b"interpreter")
    evidence.update(mutation)
    with pytest.raises(native.RuntimeProvenanceError):
        native.validate_observation(evidence)


@pytest.mark.parametrize(
    "bad_path",
    (
        "/etc/passwd",
        "/usr/bin/../bin/python3.13",
        "/usr//bin/python3.13",
        "/lib/../../etc/shadow",
        "usr/bin/python3.13",
        "//usr/bin/python3.13",
    ),
)
def test_native_observation_path_confined(bad_path: str) -> None:
    evidence = _evidence(b"interpreter")
    entry = evidence["files"].pop("/usr/bin/python3.13")
    evidence["files"][bad_path] = entry
    with pytest.raises(native.RuntimeProvenanceError):
        native.validate_observation(evidence)


def test_symlink_escape_never_reads_outside_private_sysroot(tmp_path: Path) -> None:
    evidence = _evidence(b"pi")
    root, manifest = _sysroot(tmp_path, b"pi")
    target = tmp_path / "outside"
    target.write_bytes(b"pi")
    (root / "usr/bin/python3.13").unlink()
    (root / "usr/bin/python3.13").symlink_to(target)
    result = native.compare(evidence, sysroot=root, sysroot_manifest=manifest)
    assert result["file_summary"]["unsafe_path"] == 1
    assert result["sampled_disk_parity"] is False


def test_invalid_digest_or_unsigned_manifest_rejected(tmp_path: Path) -> None:
    evidence = _evidence(b"pi")
    entry = evidence["files"]["/usr/bin/python3.13"]
    entry["sha256"] = "zzz"
    with pytest.raises(native.RuntimeProvenanceError):
        native.validate_observation(evidence)
    evidence = _evidence(b"pi")
    root, manifest = _sysroot(tmp_path, b"pi")
    manifest["production_ready"] = True
    with pytest.raises(native.RuntimeProvenanceError):
        native.compare(evidence, sysroot=root, sysroot_manifest=manifest)


def test_unresolved_native_dependencies_force_refusal(tmp_path: Path) -> None:
    evidence = _evidence(b"pi")
    evidence["unresolved"] = ["/usr/lib/liboptional.so:not found"]
    root, manifest = _sysroot(tmp_path, b"pi")
    assert not native.compare(evidence, sysroot=root, sysroot_manifest=manifest)[
        "sampled_disk_parity"
    ]
