"""Compare a bounded Pi native ELF observation with a private offline ARM64 sysroot.

This is *not* a trusted release attestation. The observed baseline is a
read-only operator-collected snapshot, not a root-signed or launch-bound
measurement. A successful comparison only describes sampled on-disk files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
PACKAGE_VERSION_MAX = 180
FILE_LIMIT = 256
PACKAGE_LIMIT = 128


class RuntimeProvenanceError(ValueError):
    """An observation, sysroot or comparison is unsafe or incomplete."""


def _native_path(value: object) -> PurePosixPath:
    """Accept only canonical absolute Linux paths with no traversal."""
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 512:
        raise RuntimeProvenanceError("invalid native file path")
    path = PurePosixPath(value)
    if any(part in (".", "..") for part in value.split("/")):
        raise RuntimeProvenanceError("noncanonical or traversal native path")
    if str(path) != value or not value.startswith(("/usr/", "/lib/")):
        raise RuntimeProvenanceError("native file path outside expected OS")
    return path


def _sha256(path: Path, *, byte_limit: int = 250_000_000) -> str:
    """Hash bounded regular files without following untrusted symlinks."""
    if not path.is_file() or path.is_symlink():
        raise RuntimeProvenanceError("missing or symlinked native file")
    if path.stat().st_size > byte_limit:
        raise RuntimeProvenanceError("native library size exceeds limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(131_072), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_observation(data: Any) -> dict[str, Any]:
    """Validate an explicitly non-authoritative, fixed-scope Pi observation."""
    if not isinstance(data, dict):
        raise RuntimeProvenanceError("native observation must be a JSON object")
    required = {
        "schema": 1,
        "host": "anvilmobile",
        "mode": "read_only_sample",
        "python": "3.13.5",
        "soabi": "cpython-313-aarch64-linux-gnu",
        "production_ready": False,
        "physical_radio_tested": False,
        "loaded_python_bytes_independently_proven": False,
    }
    for name, expected in required.items():
        if type(data.get(name)) is not type(expected) or data.get(name) != expected:
            raise RuntimeProvenanceError(f"unverified {name} in Pi native observation")
    files = data.get("files")
    packages = data.get("packages")
    unresolved = data.get("unresolved")
    if (
        not isinstance(files, dict)
        or not 1 <= len(files) <= FILE_LIMIT
        or not isinstance(packages, dict)
        or not 1 <= len(packages) <= PACKAGE_LIMIT
        or not isinstance(unresolved, list)
        or any(not isinstance(item, str) for item in unresolved)
    ):
        raise RuntimeProvenanceError("incomplete or oversized native inventory")
    if "/usr/bin/python3.13" not in files:
        raise RuntimeProvenanceError("Pi interpreter missing from native observation")
    for name, value in files.items():
        _native_path(name)
        if not isinstance(value, dict) or set(value) != {"resolved", "sha256", "size"}:
            raise RuntimeProvenanceError("invalid native library evidence")
        _native_path(value["resolved"])
        if (
            not isinstance(value["sha256"], str)
            or HEX_SHA256.fullmatch(value["sha256"]) is None
            or type(value["size"]) is not int
            or not 0 < value["size"] <= 250_000_000
        ):
            raise RuntimeProvenanceError("invalid file digest or size")
    for name, entry in packages.items():
        if (
            not isinstance(name, str)
            or re.fullmatch(r"[a-z0-9+.-]+(?::arm64)?", name) is None
            or not isinstance(entry, dict)
            or not isinstance(entry.get("version"), str)
            or not 0 < len(entry["version"]) <= PACKAGE_VERSION_MAX
            or entry.get("arch") not in {"arm64", "all"}
        ):
            raise RuntimeProvenanceError("incomplete Debian package version record")
    return data


def compare(
    observation: dict[str, Any],
    *,
    sysroot: Path,
    sysroot_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compare actual sampled hashes and declared package versions, never attest."""
    data = validate_observation(observation)
    if not sysroot.is_absolute() or sysroot.is_symlink() or not sysroot.is_dir():
        raise RuntimeProvenanceError("unsafe offline sysroot")
    if (
        not isinstance(sysroot_manifest, dict)
        or sysroot_manifest.get("target_architecture") != "aarch64"
        or sysroot_manifest.get("production_ready") is not False
        or not isinstance(sysroot_manifest.get("os_package_archives"), dict)
    ):
        raise RuntimeProvenanceError("invalid offline sysroot package manifest")
    root = sysroot.resolve()
    files: dict[str, str] = {}
    for raw, entry in sorted(data["files"].items()):
        _native_path(raw)
        guest_path = _native_path(entry["resolved"])
        candidate = root.joinpath(*guest_path.parts[1:])
        # symlinks are treated only as static, explicitly confined filesystem
        # paths. Unavailable/mismatched files never trigger mutation.
        try:
            resolved = candidate.resolve(strict=True)
            if not resolved.is_relative_to(root):
                status = "unsafe_path"
            elif not resolved.is_file():
                status = "missing"
            elif resolved.stat().st_size != entry["size"]:
                status = "mismatch"
            elif _sha256(resolved) == entry["sha256"]:
                status = "match"
            else:
                status = "mismatch"
        except (OSError, RuntimeError, ValueError):
            status = "missing"
        files[raw] = status

    os_packages = sysroot_manifest["os_package_archives"]
    packages: dict[str, str] = {}
    for package_name, entry in sorted(data["packages"].items()):
        short = package_name.split(":", 1)[0]
        present = os_packages.get(short)
        packages[package_name] = (
            "missing"
            if not isinstance(present, dict)
            else "match"
            if present.get("version") == entry["version"]
            else "mismatch"
        )
    file_summary = {
        name: sum(status == name for status in files.values())
        for name in ("match", "mismatch", "missing", "unsafe_path")
    }
    package_summary = {
        name: sum(status == name for status in packages.values())
        for name in ("match", "mismatch", "missing")
    }
    sampled_parity = (
        not data["unresolved"]
        and file_summary["match"] == len(files)
        and package_summary["match"] == len(packages)
    )
    return {
        "schema": 1,
        "purpose": "offline_sampled_native_comparison_only",
        "sampled_file_count": len(files),
        "sampled_package_count": len(packages),
        "files": files,
        "packages": packages,
        "file_summary": file_summary,
        "package_summary": package_summary,
        "unresolved_count": len(data["unresolved"]),
        "sampled_disk_parity": sampled_parity,
        "complete_runtime_closure_proven": False,
        "distribution_signature_verified": False,
        "loaded_python_bytes_independently_proven": False,
        "production_ready": False,
        "release_decision": "NO_GO",
    }


def main() -> int:
    """Refuse production release and return code 75 if sampled parity fails."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observation", type=Path, required=True)
    parser.add_argument("--sysroot", type=Path, required=True)
    parser.add_argument("--sysroot-manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        observation = json.loads(args.observation.read_text(encoding="utf-8"))
        manifest = json.loads(args.sysroot_manifest.read_text(encoding="utf-8"))
        result = compare(observation, sysroot=args.sysroot, sysroot_manifest=manifest)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.exit(75, f"OFFLINE NATIVE COMPARISON REFUSED: {type(exc).__name__}\n")
    print(json.dumps(result, sort_keys=True))
    return 0 if result["sampled_disk_parity"] else 75


if __name__ == "__main__":
    raise SystemExit(main())
