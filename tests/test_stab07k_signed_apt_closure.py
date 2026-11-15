"""STAB-07K cryptographic chain regression with private ephemeral GPG keys."""

from __future__ import annotations

import hashlib
import importlib.util
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-signed-apt-closure.py"
SPEC = importlib.util.spec_from_file_location("stab07k_signed_apt", SOURCE)
assert SPEC and SPEC.loader
apt = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(apt)


def _fixture(tmp_path: Path) -> tuple[dict[str, object], dict[str, Path]]:
    """Sign a minimal Debian-style Release using a throwaway test-only key."""
    home = tmp_path / "gpg"
    home.mkdir(mode=0o700)
    subprocess.run(
        [
            "gpg",
            "--batch",
            "--homedir",
            str(home),
            "--passphrase",
            "",
            "--quick-generate-key",
            "Disposable STAB07K test <test@example.invalid>",
            "ed25519",
            "sign",
            "0",
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=20,
    )
    keyring = tmp_path / "trusted-test-keyring.gpg"
    with keyring.open("wb") as stream:
        subprocess.run(
            ["gpg", "--batch", "--homedir", str(home), "--export"],
            stdout=stream,
            check=True,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    archive = b"non-executable test-only Debian package bytes"
    pool = tmp_path / "archives"
    target = pool / "pool/main/r/radio/libexample_1.0_arm64.deb"
    target.parent.mkdir(parents=True)
    target.write_bytes(archive)
    path = "pool/main/r/radio/libexample_1.0_arm64.deb"
    index_bytes = (
        "Package: libexample\nVersion: 1.0\nArchitecture: arm64\n"
        f"Filename: {path}\n"
        f"Size: {len(archive)}\n"
        f"SHA256: {hashlib.sha256(archive).hexdigest()}\n\n"
    ).encode()
    index = tmp_path / "Packages"
    index.write_bytes(index_bytes)
    release_text = (
        "Origin: Local disposable STAB-07K\n"
        "Suite: trixie\n"
        "Architectures: arm64\n"
        "Components: main\n"
        "SHA256:\n"
        f" {hashlib.sha256(index_bytes).hexdigest()} {len(index_bytes)}"
        " main/binary-arm64/Packages\n"
    )
    raw_release = tmp_path / "Release"
    raw_release.write_text(release_text)
    signed = tmp_path / "InRelease"
    subprocess.run(
        [
            "gpg",
            "--batch",
            "--homedir",
            str(home),
            "--yes",
            "--clearsign",
            "--output",
            str(signed),
            str(raw_release),
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=10,
    )
    args = {
        "release": signed,
        "package_index": index,
        "keyring": keyring,
        "trusted_key_sha256": hashlib.sha256(keyring.read_bytes()).hexdigest(),
        "index_component": "main/binary-arm64/Packages",
        "required": {"libexample": "1.0"},
        "archive_root": pool,
    }
    return args, {"release": signed, "index": index, "archive": target, "key": keyring}


def test_exact_signed_apt_to_archive_chain_never_approves_release(tmp_path: Path) -> None:
    args, _files = _fixture(tmp_path)
    result = apt.verify(**args)
    assert result["exact_versions_verified"] == 1
    assert result["release_decision"] == "NO_GO"
    assert result["production_ready"] is False
    assert result["complete_os_runtime_closure_proven"] is False
    assert result["loaded_python_bytes_independently_proven"] is False
    assert result["packages"]["libexample"]["version"] == "1.0"


def test_altered_archive_fails_even_when_signed_index_remains_good(tmp_path: Path) -> None:
    args, paths = _fixture(tmp_path)
    paths["archive"].write_bytes(b"tampered")
    with pytest.raises(apt.AptEvidenceError, match="hash"):
        apt.verify(**args)


def test_altered_index_fails_signed_release_hash(tmp_path: Path) -> None:
    args, paths = _fixture(tmp_path)
    with paths["index"].open("ab") as stream:
        stream.write(b"more untrusted packages\n")
    with pytest.raises(apt.AptEvidenceError, match="signed InRelease"):
        apt.verify(**args)


def test_altered_release_signature_refused(tmp_path: Path) -> None:
    args, paths = _fixture(tmp_path)
    text = paths["release"].read_text()
    paths["release"].write_text(text.replace("trixie", "trixiez", 1))
    with pytest.raises(apt.AptEvidenceError, match="signed release"):
        apt.verify(**args)


def test_untrusted_or_modified_key_refused(tmp_path: Path) -> None:
    args, paths = _fixture(tmp_path)
    paths["key"].write_bytes(b"forged public key")
    with pytest.raises(apt.AptEvidenceError, match="keyring"):
        apt.verify(**args)


def test_version_absent_from_signed_index_refuses(tmp_path: Path) -> None:
    args, _paths = _fixture(tmp_path)
    args["required"] = {"libexample": "2.0"}
    with pytest.raises(apt.AptEvidenceError, match="missing or ambiguous"):
        apt.verify(**args)


@pytest.mark.parametrize(
    "name",
    (
        "main/../../etc/passwd",
        "main/binary-amd64/Packages",
        "/main/binary-arm64/Packages",
        "main/binary-arm64/../Packages",
    ),
)
def test_untrusted_component_disallowed(tmp_path: Path, name: str) -> None:
    args, _files = _fixture(tmp_path)
    args["index_component"] = name
    with pytest.raises(apt.AptEvidenceError, match="component"):
        apt.verify(**args)


@pytest.mark.parametrize(
    "name",
    ("pool/../etc/passwd", "/etc/shadow", "pool//file.deb", "pool/pkg\\file.deb"),
)
def test_archive_paths_are_not_arbitrary(name: str) -> None:
    with pytest.raises(apt.AptEvidenceError):
        apt._archive_path(name)


def test_symlink_archive_escape_refuses_without_leaking(tmp_path: Path) -> None:
    args, paths = _fixture(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(paths["archive"].read_bytes())
    paths["archive"].unlink()
    paths["archive"].symlink_to(outside)
    with pytest.raises(apt.AptEvidenceError):
        apt.verify(**args)


def test_input_key_digest_is_not_self_attestation(tmp_path: Path) -> None:
    args, _paths = _fixture(tmp_path)
    args["trusted_key_sha256"] = "f" * 64
    with pytest.raises(apt.AptEvidenceError, match="keyring"):
        apt.verify(**args)


def test_missing_and_unbounded_requested_packages_refused(tmp_path: Path) -> None:
    args, _paths = _fixture(tmp_path)
    for required in ({}, {f"example{i}": "1.0" for i in range(130)}):
        args["required"] = required
        with pytest.raises(apt.AptEvidenceError, match="missing or oversized"):
            apt.verify(**args)
