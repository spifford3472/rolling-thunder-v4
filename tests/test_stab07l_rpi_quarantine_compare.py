"""STAB-07L regression: quarantined Pi bytes never become signed release proof."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-rpi-quarantine-compare.py"
SPEC = importlib.util.spec_from_file_location("rt_stab07l_quarantine", SOURCE)
assert SPEC and SPEC.loader
quarantine = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(quarantine)


def fixture(tmp_path: Path) -> tuple[dict[str, object], Path, dict[str, str], Path]:
    """Use inert byte fixtures, never execute actual ARM64/native code."""
    root = tmp_path / "quarantine"
    archive_dir = root / "archives"
    archive_dir.mkdir(parents=True)
    pins: dict[str, str] = {}
    for pkg, name in quarantine.ARCHIVES.items():
        data = f"inert test package {pkg}".encode()
        (archive_dir / name).write_bytes(data)
        pins[pkg] = hashlib.sha256(data).hexdigest()

    samples = {
        "/lib/aarch64-linux-gnu/libc.so.6": ("untrusted_libc6", b"fake libc"),
        "/lib/aarch64-linux-gnu/libssl.so.3": ("untrusted_openssl", b"fake ssl"),
        "/usr/bin/python3.13": ("separate_signed_14", b"fake interpreter"),
    }
    signed = tmp_path / "signed_overlay"
    signed.mkdir()
    for path, (origin, content) in samples.items():
        base = (
            root / "extracted/libc6"
            if origin == "untrusted_libc6"
            else root / "extracted/openssl"
            if origin == "untrusted_openssl"
            else signed
        )
        target = base / path.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    sample: dict[str, object] = {
        "host": "anvilmobile",
        "mode": "read_only_sample",
        "production_ready": False,
        "files": {
            path: {
                "resolved": path,
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, (_origin, content) in samples.items()
        },
    }
    return sample, root, pins, signed


def test_exact_content_match_is_not_authenticated_release(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    report = quarantine.compare(
        sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
    )
    assert report["observed_file_counts"] == {
        "untrusted_libc6": 1,
        "untrusted_openssl": 1,
        "separate_signed_14": 1,
        "absent": 0,
    }
    assert report["archive_release_authenticity_proven"] is False
    assert report["rpi_historical_signed_index_verified"] is False
    assert report["debs_authorized_for_execution"] is False
    assert report["production_ready"] is False
    assert report["release_decision"] == "NO_GO"


def test_missing_sample_counts_as_absent(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    (signed / "usr/bin/python3.13").unlink()
    report = quarantine.compare(
        sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
    )
    assert report["observed_file_counts"]["absent"] == 1
    assert report["complete_os_runtime_closure_proven"] is False


def test_archive_mutation_is_refused(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    (root / "archives" / quarantine.ARCHIVES["libc6"]).write_bytes(b"modified")
    with pytest.raises(quarantine.QuarantineEvidenceError, match="SHA256 changed"):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


@pytest.mark.parametrize(
    "bad_path",
    (
        "/etc/shadow",
        "/lib/../etc/shadow",
        "lib/aarch64-linux-gnu/libc.so.6",
        "/lib//libc.so.6",
        "/usr/./bin/python3.13",
    ),
)
def test_unsafe_pi_file_paths_rejected(tmp_path: Path, bad_path: str) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    entries = sample["files"]
    value = entries.pop("/lib/aarch64-linux-gnu/libc.so.6")
    entries[bad_path] = value
    with pytest.raises(quarantine.QuarantineEvidenceError):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


def test_extract_symlink_escape_never_read(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    path = root / "extracted/libc6/lib/aarch64-linux-gnu/libc.so.6"
    path.unlink()
    path.symlink_to(tmp_path / "outside")
    with pytest.raises(quarantine.QuarantineEvidenceError):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


def test_extracted_file_mutation_fails_closed(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    path = root / "extracted/openssl/lib/aarch64-linux-gnu/libssl.so.3"
    path.write_bytes(b"fake tampered ssl")
    with pytest.raises(quarantine.QuarantineEvidenceError, match="differs"):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


def test_same_native_file_from_multiple_roots_refused(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    duplicate = signed / "lib/aarch64-linux-gnu/libc.so.6"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(b"fake libc")
    with pytest.raises(quarantine.QuarantineEvidenceError, match="multiple"):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


@pytest.mark.parametrize("bad_flag", [{"production_ready": True}, {"mode": "approved"}])
def test_bad_pi_sample_authority_is_rejected(tmp_path: Path, bad_flag: dict[str, object]) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    sample.update(bad_flag)
    with pytest.raises(quarantine.QuarantineEvidenceError):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


def test_pin_replacement_cannot_authenticate_quarantined_archive(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    pins["libc6"] = "not a SHA256"
    with pytest.raises(quarantine.QuarantineEvidenceError):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


def test_symlink_archive_directory_refused(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    outside = tmp_path / "elsewhere"
    (root / "archives").rename(outside)
    (root / "archives").symlink_to(outside, target_is_directory=True)
    with pytest.raises(quarantine.QuarantineEvidenceError):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )


def test_symlink_extraction_parent_refused(tmp_path: Path) -> None:
    sample, root, pins, signed = fixture(tmp_path)
    original = root / "extracted/libc6"
    outside = tmp_path / "moved_libc6"
    original.rename(outside)
    original.symlink_to(outside, target_is_directory=True)
    with pytest.raises(quarantine.QuarantineEvidenceError):
        quarantine.compare(
            sample=sample, quarantine=root, archive_sha256=pins, trusted_overlay=signed
        )
