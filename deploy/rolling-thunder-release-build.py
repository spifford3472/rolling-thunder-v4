"""Offline deterministic exact-Git-source bundle; never install or launch code.

A source archive is NOT a complete deployable release. Dependencies, platform,
venv, native extensions, configuration and trusted launch remain separate gates.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import subprocess
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

_SHA = re.compile(r"[0-9a-f]{40}\Z")
_ALLOWED_ROOTS = ("src/", "deploy/")
_SOURCE_FILES = ("pyproject.toml", "README.md")
_MAX_FILES = 30000
_MAX_BLOB = 20 * 1024 * 1024
_MAX_BUNDLE = 200 * 1024 * 1024


class BuildError(ValueError):
    """Unverifiable or potentially unsafe candidate source was encountered."""


def _git(repo: Path, *args: str, input_bytes: bytes | None = None) -> bytes:
    """Use bounded, noninteractive Git with optional index locks disabled."""
    try:
        result = subprocess.run(
            ["/usr/bin/git", "-C", str(repo), *args],
            input=input_bytes,
            capture_output=True,
            timeout=10,
            check=True,
            env={"PATH": "/usr/bin:/bin", "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BuildError("Git source verification failed") from exc
    if len(result.stdout) > _MAX_BUNDLE:
        raise BuildError("Git output exceeds source bundle limit")
    return result.stdout


def _selected(name: str) -> bool:
    """Whitelist only source and deployment code, never station data/secrets."""
    return name in _SOURCE_FILES or name.startswith(_ALLOWED_ROOTS)


def source_entries(repo: Path, sha: str) -> dict[str, bytes]:
    """Read exact immutable Git blobs, refusing all submodules and symlinks."""
    if not _SHA.fullmatch(sha):
        raise BuildError("expected an exact lowercase forty-hex commit")
    commit = _git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}").strip().decode()
    if commit != sha:
        raise BuildError("requested commit is not the exact verified commit")
    raw = _git(repo, "ls-tree", "-r", "-z", "--full-tree", sha)
    files: dict[str, bytes] = {}
    total = 0
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode, kind, blob_id = metadata.decode("ascii").split()
            name = raw_path.decode("utf-8")
        except (ValueError, UnicodeError) as exc:
            raise BuildError("invalid Git tree record") from exc
        if not _selected(name):
            continue
        path = PurePosixPath(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or name != str(path)
            or mode not in ("100644", "100755")
            or kind != "blob"
        ):
            raise BuildError("unsupported source path, symlink, or submodule")
        if len(files) >= _MAX_FILES or name in files:
            raise BuildError("duplicate or oversized source tree")
        size = int(_git(repo, "cat-file", "-s", blob_id).strip())
        if size > _MAX_BLOB or total + size > _MAX_BUNDLE:
            raise BuildError("source file or aggregate bundle oversized")
        content = _git(repo, "cat-file", "blob", blob_id)
        if len(content) != size:
            raise BuildError("Git object size discrepancy")
        files[name] = content
        total += size
    if not {
        "pyproject.toml",
        "src/rolling_thunder/ui_main.py",
        "deploy/rolling-thunder-autostart",
    }.issubset(files):
        raise BuildError("incomplete source release")
    return files


def build_bytes(repo: Path, sha: str) -> tuple[bytes, dict[str, Any]]:
    """Return deterministic tar and manifest; no privileged installation."""
    files = source_entries(repo, sha)
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in sorted(files.items())}
    manifest: dict[str, Any] = {
        "schema": 1,
        "git_commit": sha,
        "type": "source-only-candidate",
        "dependencies_pinned": False,
        "runtime_proven": False,
        "source_files": hashes,
    }
    document = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode()
    files["source-manifest.json"] = document
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, content in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(content)
            member.mode = 0o644
            member.uid = member.gid = member.mtime = 0
            member.uname = member.gname = ""
            archive.addfile(member, io.BytesIO(content))
    return buffer.getvalue(), manifest


def main() -> int:
    """Write a candidate file in user space; refuse overwriting old builds."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        data, manifest = build_bytes(args.repo, args.sha)
        with args.output.open("xb") as stream:
            stream.write(data)
        print(
            json.dumps(
                {
                    "source_bundle_sha256": hashlib.sha256(data).hexdigest(),
                    "git_commit": manifest["git_commit"],
                    "state": "source_only_not_installable",
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, BuildError) as exc:
        parser.exit(75, f"SOURCE BUILD REFUSED: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
