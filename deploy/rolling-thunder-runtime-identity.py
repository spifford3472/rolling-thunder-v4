"""Read-only process-to-protected-release binding, never a hardware safety proof.

This independent tool refuses the existing writable editable checkout. It can
verify a FUTURE separately approved, root-owned pinned release layout, but
cannot infer all already-imported Python bytecode from /proc or trust Git HEAD
alone. Never emits a claim of independently proven in-memory Python code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
SERVICE = "rolling-thunder.service"
MAX_FILES = 30000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024


def _service_status() -> dict[str, str]:
    """Query systemd's system manager; never start or stop the service."""
    output = subprocess.run(
        [
            "/usr/bin/systemctl",
            "show",
            SERVICE,
            "--no-pager",
            "-p",
            "ActiveState",
            "-p",
            "MainPID",
            "-p",
            "User",
            "-p",
            "ControlGroup",
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=3,
    ).stdout
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def _trusted_path(path: Path, *, uid: int, anchor: Path = Path("/")) -> bool:
    """Trust only owner-controlled, non-symlink components without group writes."""
    if not path.is_absolute():
        return False
    # Production anchors at /; a fixture may anchor at its private root.
    if not anchor.is_absolute() or not path.is_relative_to(anchor):
        return False
    cursor = anchor
    components = (".", *path.relative_to(anchor).parts)
    for component in components:
        cursor /= component
        try:
            info = cursor.lstat()
        except OSError:
            return False
        if stat.S_ISLNK(info.st_mode) or info.st_uid != uid or info.st_mode & 0o022:
            return False
        if cursor != path and not stat.S_ISDIR(info.st_mode):
            return False
    return True


def _file_hash(
    path: Path, *, uid: int, anchor: Path = Path("/"), limit: int = 20 * 1024 * 1024
) -> str:
    """Use nofollow file descriptor and bound individual file reads."""
    if not _trusted_path(path, uid=uid, anchor=anchor):
        raise ValueError("untrusted protected release file path")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise ValueError("unsafe protected release file")
        digest = hashlib.sha256()
        length = 0
        while fragment := os.read(fd, 65536):
            length += len(fragment)
            if length > limit:
                raise ValueError("release file exceeds bounded hash limit")
            digest.update(fragment)
        return digest.hexdigest()
    finally:
        os.close(fd)


def protected_release(
    artifact: Path, *, expected_sha: str, uid: int, anchor: Path = Path("/")
) -> dict[str, Any]:
    """Check pinned manifest coverage and every hashed file, without writes."""
    report: dict[str, Any] = {"state": "unverified", "files_checked": 0}
    try:
        if not SHA.fullmatch(expected_sha) or artifact.name != expected_sha:
            raise ValueError("release directory and requested SHA differ")
        manifest_path = artifact / "release-manifest.json"
        if not _trusted_path(artifact, uid=uid, anchor=anchor):
            raise ValueError("release directory or ancestor not protected")
        if not _trusted_path(manifest_path, uid=uid, anchor=anchor):
            raise ValueError("release manifest not protected")
        if manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
            raise ValueError("release manifest oversized")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(manifest, dict) or manifest.get("sha") != expected_sha:
            raise ValueError("release manifest SHA not exact")
        entries = manifest.get("files")
        if not isinstance(entries, dict) or not 1 <= len(entries) <= MAX_FILES:
            raise ValueError("invalid protected release inventory")
        files_seen: set[str] = set()
        for folder in ("src", ".venv", "deploy"):
            directory = artifact / folder
            if not directory.exists():
                raise ValueError("incomplete protected release")
            for root, dirs, filenames in os.walk(directory, followlinks=False):
                # Any symlink or untrusted ownership makes the release untrusted.
                base = Path(root)
                if not _trusted_path(base, uid=uid, anchor=anchor):
                    raise ValueError("unprotected release subdirectory")
                for item in dirs:
                    if not _trusted_path(base / item, uid=uid, anchor=anchor):
                        raise ValueError("untrusted release directory or symlink")
                for item in filenames:
                    entry = base / item
                    if not _trusted_path(entry, uid=uid, anchor=anchor):
                        raise ValueError("untrusted release file or symlink")
                    files_seen.add(entry.relative_to(artifact).as_posix())
                    if len(files_seen) > MAX_FILES:
                        raise ValueError("release inventory limit exceeded")
        # Ensure the bootstrap and manifest cannot hide unlisted code paths.
        for entry in (artifact / "pyproject.toml", artifact / "config/rolling-thunder.yaml"):
            if entry.exists():
                files_seen.add(entry.relative_to(artifact).as_posix())
        if files_seen != set(entries):
            raise ValueError("missing, extra or unlisted release files")
        for rel, expected_hash in entries.items():
            if (
                not isinstance(rel, str)
                or not isinstance(expected_hash, str)
                or not re.fullmatch(r"[a-f0-9]{64}", expected_hash)
                or rel.startswith("/")
                or ".." in Path(rel).parts
                or _file_hash(artifact / rel, uid=uid, anchor=anchor) != expected_hash
            ):
                raise ValueError("modified or invalid release content")
        report.update(
            {"state": "protected_artifact_matches_manifest", "files_checked": len(files_seen)}
        )
    except (OSError, ValueError, TypeError, KeyError, UnicodeError) as exc:
        report["error"] = type(exc).__name__
    return report


def inspect(
    *,
    artifact: Path,
    expected_sha: str,
    proc_root: Path = Path("/proc"),
    trusted_uid: int = 0,
    operator_user: str = "geoff",
    service: dict[str, str] | None = None,
    trusted_anchor: Path = Path("/"),
) -> dict[str, Any]:
    """Reconcile process identity with an immutable protected source artifact."""
    report: dict[str, Any] = {
        "expected_sha": expected_sha,
        "state": "unverified",
        "loaded_python_bytes_independently_proven": False,
        "disposition": "blocked_manual_review",
        "release": protected_release(
            artifact, expected_sha=expected_sha, uid=trusted_uid, anchor=trusted_anchor
        ),
    }
    try:
        if report["release"]["state"] != "protected_artifact_matches_manifest":
            return report
        values = _service_status() if service is None else service
        pid = int(values.get("MainPID", "0"))
        operator_uid = pwd.getpwnam(operator_user).pw_uid
        if (
            pid <= 1
            or values.get("ActiveState") != "active"
            or values.get("User") != operator_user
            or values.get("ControlGroup") != "/system.slice/rolling-thunder.service"
        ):
            return report
        process = proc_root / str(pid)
        if process.stat().st_uid != operator_uid:
            return report
        if (
            process.joinpath("cgroup").read_text(encoding="utf-8").strip()
            != "0::/system.slice/rolling-thunder.service"
        ):
            return report
        if process.joinpath("cwd").resolve(strict=True) != artifact.resolve(strict=True):
            return report
        argv = [
            arg.decode("utf-8")
            for arg in process.joinpath("cmdline").read_bytes().split(b"\0")
            if arg
        ]
        # Isolation is mandatory to eliminate PYTHONPATH/user-site injection.
        expected_executable = str(artifact / ".venv/bin/python")
        expected_entrypoint = str(artifact / ".venv/bin/rolling-thunder-ui")
        if (
            len(argv) != 4
            or argv[0] != expected_executable
            or argv[1:4] != ["-I", "-B", expected_entrypoint]
        ):
            return report
        report.update({"state": "protected_release_and_process_path_bound", "pid": pid})
        # This does NOT prove loaded Python modules from memory. A separately
        # reviewed launch-integrity protocol is required to clear release gate.
    except (OSError, ValueError, UnicodeError, subprocess.SubprocessError, KeyError):
        pass
    return report


def main() -> int:
    """Never report fully verified in-memory code from this static check."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    report = inspect(artifact=args.artifact, expected_sha=args.sha)
    print(json.dumps(report, sort_keys=True))
    # Never expose a success exit code for in-memory code identity on disk-only
    # evidence; callers must not turn a valid artifact into release approval.
    return 75


if __name__ == "__main__":
    raise SystemExit(main())
