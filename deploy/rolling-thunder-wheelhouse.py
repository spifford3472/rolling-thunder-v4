"""Fail-closed ARM64/Python 3.13 wheelhouse validation for offline releases.

Only checks immutable data against a reviewed lock; no pip install, network,
privilege, service, database or radio command is performed by this tool.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from email.parser import Parser
from pathlib import Path
from typing import Any
from zipfile import BadZipFile, ZipFile

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import canonicalize_name, parse_wheel_filename

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
TARGET = {"architecture": "aarch64", "python": "3.13.5", "abi": "cp313", "glibc": "2.41"}
DIRECT = {"pillow", "pycountry", "pydantic", "pyserial", "pyyaml", "vosk"}
MAX_WHEEL_SIZE = 80 * 1024 * 1024
MAX_ENTRIES = 30000


class WheelhouseError(ValueError):
    """Rejected package integrity, dependency closure or incompatible wheel."""


def _platform_tags() -> set[Any]:
    """Use explicit Debian ARM64 glibc 2.41 compatible manylinux tags."""
    platforms = [f"manylinux_2_{v}_aarch64" for v in range(17, 42)]
    platforms.append("manylinux2014_aarch64")
    return set(cpython_tags(python_version=(3, 13), abis=["cp313"], platforms=platforms)) | set(
        compatible_tags(python_version=(3, 13), interpreter="cp313", platforms=platforms)
    )


def _metadata(wheel: Path) -> Any:
    """Read bounded wheel metadata and disallow potentially unsafe extraction."""
    with ZipFile(wheel) as archive:
        members = archive.infolist()
        if len(members) > MAX_ENTRIES or sum(m.file_size for m in members) > 400 * 1024 * 1024:
            raise WheelhouseError("excessive wheel archive expansion")
        for item in members:
            parts = item.filename.split("/")
            if (
                item.filename.startswith("/")
                or ".." in parts
                or "\\" in item.filename
                or item.filename.endswith((".pth", ".egg-link"))
                or stat.S_ISLNK(item.external_attr >> 16)
            ):
                raise WheelhouseError("unsafe wheel member")
        for item in members:
            name = item.filename.lower()
            if name.endswith((".so", ".pyd", ".dll", ".dylib")) or ".so." in name:
                if name.endswith((".pyd", ".dll", ".dylib")):
                    raise WheelhouseError("non-Linux binary in ARM64 wheel")
                with archive.open(item) as source:
                    header = source.read(20)
                if (
                    len(header) < 20 or header[:4] != b"\x7fELF"
                    or header[4:6] != b"\x02\x01"
                    or int.from_bytes(header[18:20], "little") != 183
                ):
                    raise WheelhouseError("native extension is not AArch64 ELF64")
        candidates = [item for item in members if item.filename.endswith(".dist-info/METADATA")]
        if len(candidates) != 1 or candidates[0].file_size > 1024 * 1024:
            raise WheelhouseError("missing or oversized wheel metadata")
        return Parser().parsestr(archive.read(candidates[0]).decode("utf-8"))


def verify(lock_path: Path, wheelhouse: Path) -> dict[str, Any]:
    """Verify exact lock, platform tags and full active dependency closure."""
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    if not isinstance(lock, dict) or lock.get("schema") != 1 or lock.get("target") != TARGET:
        raise WheelhouseError("unsupported lock target or schema")
    records = lock.get("packages")
    if not isinstance(records, dict) or not records or not DIRECT.issubset(records):
        raise WheelhouseError("missing required base and speech package pins")
    if wheelhouse.is_symlink() or not wheelhouse.is_dir():
        raise WheelhouseError("unsafe wheelhouse directory")
    found = {p.name for p in wheelhouse.iterdir()}
    expected = {rec.get("file") for rec in records.values() if isinstance(rec, dict)}
    if len(found) != len(expected) or found != expected:
        raise WheelhouseError("missing, extra, or duplicated wheel files")
    allowed = _platform_tags()
    versions: dict[str, Any] = {}
    requirements: list[tuple[str, Requirement]] = []
    total_bytes = 0
    for key, record in sorted(records.items()):
        if not isinstance(record, dict) or canonicalize_name(key) != key:
            raise WheelhouseError("invalid package key")
        filename = record.get("file")
        digest = record.get("sha256")
        version = record.get("version")
        if (
            not isinstance(filename, str)
            or filename != Path(filename).name
            or not filename.endswith(".whl")
            or not isinstance(digest, str)
            or SHA256.fullmatch(digest) is None
            or not isinstance(version, str)
        ):
            raise WheelhouseError("invalid immutable wheel pin")
        path = wheelhouse / filename
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_WHEEL_SIZE or info.st_size <= 0:
            raise WheelhouseError("unsafe wheel file type or size")
        total_bytes += info.st_size
        name, parsed_version, _build, wheel_tags = parse_wheel_filename(filename)
        if canonicalize_name(str(name)) != key or str(parsed_version) != version:
            raise WheelhouseError("wheel identity differs from locked version")
        if not allowed.intersection(wheel_tags):
            raise WheelhouseError("wheel is not for CPython 3.13 ARM64")
        sha = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                sha.update(block)
        if sha.hexdigest() != digest:
            raise WheelhouseError("wheel hash differs from locked file")
        metadata = _metadata(path)
        if canonicalize_name(metadata.get("Name", "")) != key or metadata.get("Version") != version:
            raise WheelhouseError("wheel metadata and filename disagree")
        requires_python = metadata.get("Requires-Python")
        if requires_python and "3.13.5" not in SpecifierSet(requires_python):
            raise WheelhouseError("wheel requires different Python version")
        versions[key] = parsed_version
        for req in metadata.get_all("Requires-Dist") or []:
            requirements.append((key, Requirement(req)))
    env = default_environment()
    env.update(
        {
            "python_version": "3.13",
            "python_full_version": "3.13.5",
            "sys_platform": "linux",
            "platform_system": "Linux",
            "platform_machine": "aarch64",
            "os_name": "posix",
            "extra": "",
            "implementation_name": "cpython",
            "platform_python_implementation": "CPython",
        }
    )
    for owner, requirement in requirements:
        if requirement.marker is not None and not requirement.marker.evaluate(env):
            continue
        package = canonicalize_name(requirement.name)
        if package not in versions or versions[package] not in requirement.specifier:
            raise WheelhouseError(
                f"unsatisfied locked transitive dependency for {owner}: {package}"
            )
    return {
        "status": "wheelhouse_hashes_and_dependency_closure_verified",
        "target": TARGET,
        "packages": len(records),
        "bytes": total_bytes,
        "interpreter_included": False,
        "release_installable": False,
        "reviewed_provenance": False,
    }


def main() -> int:
    """Read-only verification command for the offline candidate wheelhouse."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", required=True, type=Path)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    options = parser.parse_args()
    try:
        print(json.dumps(verify(options.lock, options.wheelhouse), sort_keys=True))
        return 0
    except (OSError, ValueError, BadZipFile) as exc:
        parser.exit(75, f"WHEELHOUSE REFUSED: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
