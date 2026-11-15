"""Verify exact Debian/Raspberry Pi package archives against signed APT metadata.

This verifies a *single component/architecture package index* and a list of
required exact versions. It is a read-only/offline validator, NOT an apt
installer, privileged host verifier, or production release authorization.

The expected signing-key SHA256 must be obtained through a separate trusted
channel; user-controlled keys cannot authenticate themselves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
PKG_RE = re.compile(r"[a-z0-9][a-z0-9+.-]{0,127}\Z")
MAX_BYTES = 256_000_000
MAX_STANZAS = 250_000


class AptEvidenceError(ValueError):
    """The signed index or its exact package-archive chain was not established."""


def _digest(path: Path, *, limit: int = MAX_BYTES) -> tuple[str, int]:
    """Stream bounded sha256, refusing symlinks and non-regular input files."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise AptEvidenceError("missing, unsafe or oversized signed APT input")
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as data:
        for chunk in iter(lambda: data.read(131072), b""):
            total += len(chunk)
            if total > limit:
                raise AptEvidenceError("APT input grew beyond limit")
            h.update(chunk)
    return h.hexdigest(), total


def _verified_release(release: Path, keyring: Path, trusted_key_sha256: str) -> str:
    """Require authentic InRelease signature under independently pinned keys."""
    if not SHA256_RE.fullmatch(trusted_key_sha256):
        raise AptEvidenceError("invalid pinned APT keyring SHA256")
    actual_key_sha, _size = _digest(keyring, limit=1_000_000)
    if actual_key_sha != trusted_key_sha256:
        raise AptEvidenceError("APT keyring differs from independently pinned key")
    _digest(release, limit=2_000_000)
    try:
        check = subprocess.run(
            ["gpgv", "--keyring", str(keyring), str(release)],
            capture_output=True,
            text=True,
            check=False,
            timeout=12,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AptEvidenceError("APT signature verification unavailable") from exc
    if check.returncode != 0 or "Good signature" not in check.stderr:
        raise AptEvidenceError("missing valid signed release")
    text = release.read_text(encoding="utf-8", errors="strict")
    if "-----BEGIN PGP SIGNED MESSAGE-----" not in text[:100]:
        raise AptEvidenceError("expected an InRelease clearsigned metadata file")
    # gpgv verifies cleartext signature. Never treat an unverified JSON field
    # or a repository filename alone as signed evidence.
    return text


def _signed_index_hash(release: str, component: str) -> tuple[str, int]:
    """Extract one SHA256 entry from InRelease for an uncompressed index."""
    if not re.fullmatch(r"[a-z0-9.-]+/binary-(?:arm64|all)/Packages", component):
        raise AptEvidenceError("invalid signed index component/architecture")
    section = False
    matches: list[tuple[str, int]] = []
    for line in release.splitlines():
        if line == "SHA256:":
            section = True
            continue
        if section and not line.startswith(" "):
            break
        if section:
            bits = line.split()
            if len(bits) == 3 and bits[2] == component:
                if not SHA256_RE.fullmatch(bits[0]) or not bits[1].isdigit():
                    raise AptEvidenceError("invalid index digest in signed Release")
                matches.append((bits[0], int(bits[1])))
    if len(matches) != 1:
        raise AptEvidenceError("expected exactly one signed index digest")
    return matches[0]


def _stanzas(index: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    """Parse bounded Debian Packages records without silently merging duplicates."""
    out: dict[tuple[str, str, str], dict[str, str]] = {}
    count = 0

    def consume(fields: dict[str, str]) -> None:
        nonlocal count
        if not fields:
            return
        count += 1
        if count > MAX_STANZAS:
            raise AptEvidenceError("oversized package index")
        name, version, arch = (
            fields.get(field, "") for field in ("Package", "Version", "Architecture")
        )
        if (
            not PKG_RE.fullmatch(name)
            or not 0 < len(version) <= 180
            or arch not in {"arm64", "all"}
        ):
            raise AptEvidenceError("invalid Debian Package/Version/Architecture metadata")
        key = (name, version, arch)
        if key in out:
            raise AptEvidenceError("duplicated package identity")
        out[key] = fields

    fields: dict[str, str] = {}
    with index.open(encoding="utf-8") as lines:
        for line in lines:
            if not line.strip():
                consume(fields)
                fields = {}
            elif line.startswith((" ", "\t")):
                continue  # Multiline descriptions do not affect identity/hash.
            elif ": " in line:
                key, value = line.rstrip("\n").split(": ", 1)
                fields[key] = value
        consume(fields)
    return out


def _archive_path(value: str) -> PurePosixPath:
    """Constrain Debian archive location relative to private archive root."""
    if not value.startswith("pool/") or len(value) > 512 or "\\" in value:
        raise AptEvidenceError("unsafe package archive filename")
    path = PurePosixPath(value)
    if any(s in {".", "..", ""} for s in value.split("/")) or str(path) != value:
        raise AptEvidenceError("noncanonical APT archive path")
    return path


def verify(
    *,
    release: Path,
    package_index: Path,
    keyring: Path,
    trusted_key_sha256: str,
    index_component: str,
    required: dict[str, str],
    archive_root: Path,
) -> dict[str, Any]:
    """Require cryptographic linkage from pinned key to each exact .deb."""
    if not required or len(required) > 128:
        raise AptEvidenceError("required package set missing or oversized")
    if not archive_root.is_dir() or archive_root.is_symlink():
        raise AptEvidenceError("unsafe private archive root")
    for name, version in required.items():
        if (
            not PKG_RE.fullmatch(name)
            or not isinstance(version, str)
            or not 0 < len(version) <= 180
        ):
            raise AptEvidenceError("invalid exact requested package revision")
    signed = _verified_release(release, keyring, trusted_key_sha256)
    signed_index_sha, signed_size = _signed_index_hash(signed, index_component)
    actual_sha, actual_size = _digest(package_index)
    if (actual_sha, actual_size) != (signed_index_sha, signed_size):
        raise AptEvidenceError("package index does not match signed InRelease")
    inventory = _stanzas(package_index)
    packages: dict[str, dict[str, Any]] = {}
    for name, version in sorted(required.items()):
        choices = [
            row
            for (pkg, ver, arch), row in inventory.items()
            if pkg == name and ver == version and arch in {"arm64", "all"}
        ]
        if len(choices) != 1:
            raise AptEvidenceError(f"missing or ambiguous installed revision: {name}")
        entry = choices[0]
        if not SHA256_RE.fullmatch(entry.get("SHA256", "")) or not entry.get("Size", "").isdigit():
            raise AptEvidenceError("missing archive hash/size in signed index")
        relative = _archive_path(entry.get("Filename", ""))
        path = archive_root.joinpath(*relative.parts)
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(archive_root.resolve()):
            raise AptEvidenceError("archive symlink escapes private root")
        archive_sha, archive_bytes = _digest(path)
        if archive_sha != entry["SHA256"] or archive_bytes != int(entry["Size"]):
            raise AptEvidenceError("package archive does not match signed index hash")
        packages[name] = {
            "version": version,
            "architecture": entry["Architecture"],
            "repository_path": str(relative),
            "sha256": archive_sha,
            "size": archive_bytes,
        }
    release_sha, _size = _digest(release)
    return {
        "state": "sampled_archives_verified_against_signed_apt_index",
        "release_sha256": release_sha,
        "index_sha256": actual_sha,
        "keyring_sha256": trusted_key_sha256,
        "index_component": index_component,
        "packages": packages,
        "exact_versions_verified": len(packages),
        "complete_os_runtime_closure_proven": False,
        "loaded_python_bytes_independently_proven": False,
        "root_owned_release_installed": False,
        "production_ready": False,
        "release_decision": "NO_GO",
    }


def main() -> int:
    """Never install a package or write outside the caller's own stdout."""
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ("release", "package-index", "keyring", "archive-root", "required-json"):
        parser.add_argument("--" + argument, type=Path, required=True)
    parser.add_argument("--keyring-sha256", required=True)
    parser.add_argument("--index-component", default="main/binary-arm64/Packages")
    args = parser.parse_args()
    try:
        required = json.loads(args.required_json.read_text())
        result = verify(
            release=args.release,
            package_index=args.package_index,
            keyring=args.keyring,
            trusted_key_sha256=args.keyring_sha256,
            index_component=args.index_component,
            required=required,
            archive_root=args.archive_root,
        )
    except (AptEvidenceError, ValueError, OSError, subprocess.SubprocessError) as exc:
        parser.exit(75, f"SIGNED APT ARCHIVE VERIFICATION REFUSED: {type(exc).__name__}: {exc}\n")
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
