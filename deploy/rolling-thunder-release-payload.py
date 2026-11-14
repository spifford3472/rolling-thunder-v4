"""Create a deterministic ARM64 offline transport payload (NOT installable).

The tar contains exact Git source, fully verified wheelhouse, an immutable lock,
and a manifest. The Pi interpreter, signed provenance and privileged installer
are deliberately absent; no install or service operation can be performed.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path
from typing import Any


def _load(filename: str, name: str) -> Any:
    module_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(name, module_path)
    if spec is None or spec.loader is None:
        raise ValueError("offline release support module missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _hash(data: bytes) -> str:
    """Calculate exact payload component digest."""
    return hashlib.sha256(data).hexdigest()


def _write_tar(files: dict[str, bytes]) -> bytes:
    """Normalize ordering, timestamps and identities without extraction."""
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            member.uid = member.gid = member.mtime = 0
            member.uname = member.gname = ""
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(data))
    return output.getvalue()


def build_payload(
    repo: Path, sha: str, wheelhouse: Path, lock_path: Path
) -> tuple[bytes, dict[str, Any]]:
    """Bundle only the exact Git commit and a verified complete wheelhouse."""
    source = _load("rolling-thunder-release-build.py", "rt_release_source")
    wheels = _load("rolling-thunder-wheelhouse.py", "rt_release_wheelhouse")
    source_tar, source_manifest = source.build_bytes(repo, sha)
    result = wheels.verify(lock_path, wheelhouse)
    if source_manifest["git_commit"] != sha:
        raise ValueError("source manifest commit mismatch")
    data: dict[str, bytes] = {"source.tar": source_tar}
    lock_bytes = lock_path.read_bytes()
    data["dependency-lock.json"] = lock_bytes
    for filename in sorted(p.name for p in wheelhouse.iterdir()):
        data["wheels/" + filename] = (wheelhouse / filename).read_bytes()
    file_hashes = {name: _hash(content) for name, content in sorted(data.items())}
    manifest: dict[str, Any] = {
        "schema": 1,
        "type": "offline-transport-payload-not-installable",
        "git_commit": sha,
        "target": result["target"],
        "verified_wheels": result["packages"],
        "components_sha256": file_hashes,
        "interpreter_included": False,
        "signed_release": False,
        "root_owned_release": False,
        "loaded_code_proven": False,
        "production_ready": False,
    }
    data["release-payload.json"] = (
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    return _write_tar(data), manifest


def main() -> int:
    """Write output on Forge only, refusing overwrite; no executable stage."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--wheelhouse", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        tar, manifest = build_payload(args.repo, args.sha, args.wheelhouse, args.lock)
        with args.output.open("xb") as stream:
            stream.write(tar)
        print(
            json.dumps(
                {
                    "state": "offline_payload_not_installable",
                    "git_commit": manifest["git_commit"],
                    "packages": manifest["verified_wheels"],
                    "payload_sha256": _hash(tar),
                    "size_bytes": len(tar),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, ValueError) as exc:
        parser.exit(75, f"RELEASE PAYLOAD REFUSED: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
