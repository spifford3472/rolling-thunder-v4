"""Stage a verified, nonexecuting ARM64 candidate into a private sandbox.

This is NOT an installer: it never writes into a system service, active checkout,
or radio configuration. It does not claim an ARM64 runtime has been executed.
"""

from __future__ import annotations

import argparse
import ctypes
import ctypes.util
import hashlib
import io
import json
import os
import re
import shutil
import stat
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_MAX_ARCHIVE = 150 * 1024 * 1024
_MAX_FILES = 40000
_MAX_FILE = 80 * 1024 * 1024


class StageError(ValueError):
    """Untrusted artifact or unsafe staging destination."""


def _digest(data: bytes) -> str:
    """Compute an immutable source/component digest."""
    return hashlib.sha256(data).hexdigest()


def _read_archive(blob: bytes) -> dict[str, bytes]:
    """Read only bounded, ordinary tar files with canonical paths; no extraction."""
    output: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(blob), mode="r:") as archive:
        for member in archive:
            if (
                not member.isfile()
                or member.size > _MAX_FILE
                or len(output) >= _MAX_FILES
                or member.name in output
                or not member.name
                or member.name.startswith("/")
                or "\\" in member.name
                or ".." in Path(member.name).parts
                or member.name != Path(member.name).as_posix()
            ):
                raise StageError("unsafe or duplicate archive file")
            stream = archive.extractfile(member)
            if stream is None:
                raise StageError("unreadable archive member")
            data = stream.read(_MAX_FILE + 1)
            if len(data) != member.size:
                raise StageError("archive member size mismatch")
            output[member.name] = data
    return output


def _validate_bundle(
    bundle: Path, app_wheel: Path, sha: str, app_digest: str, bundle_digest: str
) -> dict[str, bytes]:
    """Bind exact transport, source, wheel set and app wheel without executing."""
    if (
        not _SHA.fullmatch(sha)
        or not _HASH.fullmatch(app_digest)
        or not _HASH.fullmatch(bundle_digest)
    ):
        raise StageError("invalid source SHA or application wheel digest")
    if bundle.is_symlink() or app_wheel.is_symlink():
        raise StageError("symlinked release input refused")
    if bundle.stat().st_size > _MAX_ARCHIVE or app_wheel.stat().st_size > _MAX_FILE:
        raise StageError("oversized release input")
    blob = bundle.read_bytes()
    if _digest(blob) != bundle_digest:
        raise StageError("transport payload differs from reviewed SHA256")
    data = _read_archive(blob)
    if (
        "release-payload.json" not in data
        or "source.tar" not in data
        or "dependency-lock.json" not in data
    ):
        raise StageError("incomplete release transport payload")
    manifest = json.loads(data.pop("release-payload.json"))
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or manifest.get("type") != "offline-transport-payload-not-installable"
        or manifest.get("git_commit") != sha
        or manifest.get("production_ready") is not False
        or manifest.get("interpreter_included") is not False
        or manifest.get("signed_release") is not False
        or manifest.get("root_owned_release") is not False
        or manifest.get("loaded_code_proven") is not False
    ):
        raise StageError("unsafe release manifest state")
    expected_hashes = manifest.get("components_sha256")
    if not isinstance(expected_hashes, dict) or set(expected_hashes) != set(data):
        raise StageError("missing or untracked component")
    for name, raw in data.items():
        if _digest(raw) != expected_hashes[name]:
            raise StageError("release payload component digest mismatch")
    lock = json.loads(data["dependency-lock.json"])
    entries = lock.get("packages")
    if not isinstance(entries, dict) or len(entries) != manifest.get("verified_wheels"):
        raise StageError("release dependency count mismatch")
    wheel_names = {"wheels/" + rec["file"] for rec in entries.values()}
    if set(data) != wheel_names | {"source.tar", "dependency-lock.json"}:
        raise StageError("missing or extra pinned wheel")
    for record in entries.values():
        if _digest(data["wheels/" + record["file"]]) != record["sha256"]:
            raise StageError("locked wheel bytes differ")
    source_files = _read_archive(data["source.tar"])
    if "source-manifest.json" not in source_files:
        raise StageError("source blob manifest missing")
    source_manifest = json.loads(source_files.pop("source-manifest.json"))
    if source_manifest.get("git_commit") != sha or source_manifest.get("source_files") != {
        name: _digest(raw) for name, raw in source_files.items()
    }:
        raise StageError("source manifest not bound to exact files")
    wheel_bytes = app_wheel.read_bytes()
    if _digest(wheel_bytes) != app_digest or not app_wheel.name.endswith("-py3-none-any.whl"):
        raise StageError("noneditable app wheel hash or tag mismatch")
    try:
        with ZipFile(io.BytesIO(wheel_bytes)) as archive:
            if not any(name.endswith(".dist-info/RECORD") for name in archive.namelist()):
                raise StageError("application wheel RECORD missing")
            if any(name.endswith((".pth", ".egg-link")) for name in archive.namelist()):
                raise StageError("editable/path injection in application wheel")
    except BadZipFile as exc:
        raise StageError("invalid application wheel archive") from exc
    data["app/" + app_wheel.name] = wheel_bytes
    data["release-payload.json"] = (json.dumps(manifest, sort_keys=True) + "\n").encode()
    return data


def _private_stage_root(root: Path) -> None:
    """Only accept an already-private non-production workspace owned by caller."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise StageError("staging root must be an existing directory, not symlink")
    info = root.lstat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise StageError("staging root must be private and caller-owned")
    if root == Path("/") or str(root).startswith(
        ("/opt/", "/usr/", "/etc/", "/var/", "/run/", "/home/geoff/")
    ):
        raise StageError("refusing production or privileged staging root")


def _atomic_noreplace(source: Path, target: Path) -> None:
    """Linux renameat2 with NOREPLACE; fail if not supported or target exists.

    os.rename can silently replace an empty directory. Do not use it for an
    immutable candidate even when a preliminary existence check passed.
    """
    libname = ctypes.util.find_library("c")
    if libname is None:
        raise StageError("atomic no-replace staging is unsupported")
    libc = ctypes.CDLL(libname, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise StageError("renameat2 no-replace is unavailable")
    renameat2.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    renameat2.restype = ctypes.c_int
    # AT_FDCWD = -100, RENAME_NOREPLACE = 1.
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(target), 1) != 0:
        error = ctypes.get_errno()
        raise StageError(f"atomic no-replace staging refused: errno {error}")


def stage(
    root: Path, bundle: Path, app_wheel: Path, sha: str, digest: str, bundle_digest: str
) -> Path:
    """Create exactly one immutable candidate through private atomic rename."""
    _private_stage_root(root)
    data = _validate_bundle(bundle, app_wheel, sha, digest, bundle_digest)
    target = root / sha
    if target.exists() or target.is_symlink():
        raise StageError("candidate already exists; replacement forbidden")
    temporary = Path(tempfile.mkdtemp(prefix=".candidate-", dir=root))
    try:
        for name, raw in sorted(data.items()):
            destination = temporary / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as writer:
                writer.write(raw)
                writer.flush()
                os.fsync(writer.fileno())
            destination.chmod(0o400)
        record: dict[str, Any] = {
            "schema": 1,
            "git_commit": sha,
            "state": "staged_offline_not_executable",
            "files": {name: _digest(raw) for name, raw in sorted(data.items())},
            "app_wheel_sha256": digest,
            "native_arm64_executed": False,
            "os_interpreter_included": False,
            "installed_venv": False,
            "root_owned_production_release": False,
            "signed_release": False,
            "loaded_python_bytes_independently_proven": False,
            "production_ready": False,
        }
        (temporary / "staging-record.json").write_text(json.dumps(record, sort_keys=True) + "\n")
        (temporary / "staging-record.json").chmod(0o400)
        for directory in sorted(
            (p for p in temporary.rglob("*") if p.is_dir()),
            key=lambda p: len(p.parts),
            reverse=True,
        ):
            directory.chmod(0o500)
        temporary.chmod(0o500)
        if target.exists() or target.is_symlink():
            raise StageError("candidate appeared during staging")
        _atomic_noreplace(temporary, target)
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
        return target
    except BaseException:
        # An interrupted attempt must not silently overwrite a prior release.
        # A failed directory fsync after rename leaves the target for review.
        if temporary.exists():
            for p in temporary.rglob("*"):
                if p.is_dir():
                    p.chmod(0o700)
            temporary.chmod(0o700)
            shutil.rmtree(temporary)
        raise


def verify_staged(root: Path, sha: str) -> dict[str, Any]:
    """Verify every immutable candidate file after staging; never claim runtime.

    Rechecking cannot establish root ownership, executing bytes or provenance;
    any change since staging must fail closed and preserve release refusal.
    """
    _private_stage_root(root)
    if not _SHA.fullmatch(sha):
        raise StageError("invalid exact candidate commit")
    candidate = root / sha
    info = candidate.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or candidate.is_symlink()
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o500
    ):
        raise StageError("untrusted candidate directory")
    manifest_file = candidate / "staging-record.json"
    if manifest_file.is_symlink() or manifest_file.stat().st_mode & 0o777 != 0o400:
        raise StageError("unsafe candidate manifest")
    record = json.loads(manifest_file.read_text())
    if (
        not isinstance(record, dict)
        or record.get("git_commit") != sha
        or record.get("state") != "staged_offline_not_executable"
        or any(
            record.get(flag) is not False
            for flag in (
                "production_ready",
                "native_arm64_executed",
                "os_interpreter_included",
                "installed_venv",
                "root_owned_production_release",
                "signed_release",
                "loaded_python_bytes_independently_proven",
            )
        )
    ):
        raise StageError("candidate contains a falsely approved status")
    expected = record.get("files")
    if not isinstance(expected, dict) or not expected:
        raise StageError("candidate file inventory missing")
    actual: set[str] = set()
    for path in candidate.rglob("*"):
        rel = path.relative_to(candidate).as_posix()
        info = path.lstat()
        if path.is_symlink() or info.st_uid != os.geteuid():
            raise StageError("untrusted staged path")
        if stat.S_ISDIR(info.st_mode):
            if stat.S_IMODE(info.st_mode) != 0o500:
                raise StageError("writable staged directory")
            continue
        if not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o400:
            raise StageError("writable or untrusted staged file")
        if rel == "staging-record.json":
            continue
        actual.add(rel)
        if rel not in expected or not isinstance(expected[rel], str):
            raise StageError("unlisted candidate file")
        sha256 = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(65536), b""):
                sha256.update(chunk)
        if sha256.hexdigest() != expected[rel]:
            raise StageError("staged file hash mismatch")
    if actual != set(expected):
        raise StageError("missing staged component")
    return {
        "state": "offline_staged_files_integrity_verified",
        "files_checked": len(actual),
        "production_ready": False,
        "loaded_python_bytes_independently_proven": False,
    }


def main() -> int:
    """Only an explicit disposable workspace destination is accepted."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", required=True, type=Path)
    parser.add_argument("--verify-only", action="store_true")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--app-wheel", type=Path)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--app-hash")
    parser.add_argument("--bundle-hash")
    args = parser.parse_args()
    try:
        if args.verify_only:
            print(json.dumps(verify_staged(args.workspace, args.sha), sort_keys=True))
            return 0
        if any(
            value is None
            for value in (args.bundle, args.app_wheel, args.app_hash, args.bundle_hash)
        ):
            raise StageError("new staging requires exact bundle, wheel and both hashes")
        target = stage(
            args.workspace,
            args.bundle,
            args.app_wheel,
            args.sha,
            args.app_hash,
            args.bundle_hash,
        )
        print(json.dumps({"candidate": str(target), "status": "staged_offline_not_executable"}))
        return 0
    except (OSError, StageError, KeyError, ValueError, TypeError, tarfile.TarError) as exc:
        parser.exit(75, f"STAGE REFUSED: {type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
