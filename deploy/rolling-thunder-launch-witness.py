"""Verify external signed process-start observations; no privileged actions.

A signature establishes provenance of an observation by a trusted observer, NOT
that all Python bytes currently executing match the intended release. The
external privileged observer/issuer and public-key installation do not exist.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import os
import re
import stat
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SHA = re.compile(r"[0-9a-f]{40}\Z")
BOOT_ID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\Z")
PUBLIC_KEY = Path("/etc/rolling-thunder/launch-witness-ed25519.pub")


class WitnessError(ValueError):
    """Missing, malformed, forged, stale or unbound process evidence."""


def _private_regular(path: Path, uid: int) -> bytes:
    """Reject symlinks and nonprivate evidence files; bounded nofollow read."""
    parent = path.parent.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != uid
        or parent.st_mode & 0o022
        or path.parent.is_symlink()
    ):
        raise WitnessError("untrusted observation directory")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        metadata = os.fstat(fd)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != uid
            or metadata.st_mode & 0o077
            or metadata.st_size > 4096
        ):
            raise WitnessError("unsafe witness file")
        return os.read(fd, 4097)
    finally:
        os.close(fd)


def _verify(message: bytes, signature: bytes, key: Path, uid: int) -> None:
    """OpenSSL 3 Ed25519 detached signature check through inherited memfds."""
    if len(signature) != 64 or len(message) > 4096:
        raise WitnessError("invalid signature or witness size")
    parent = key.parent.lstat()
    meta = key.lstat()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != uid
        or parent.st_mode & 0o022
        or key.parent.is_symlink()
        or not stat.S_ISREG(meta.st_mode)
        or meta.st_uid != uid
        or meta.st_mode & 0o022
        or meta.st_size > 4096
        or key.is_symlink()
    ):
        raise WitnessError("untrusted launch authority key")
    content_fd = os.memfd_create("launch-witness-content", flags=0)
    signature_fd = os.memfd_create("launch-witness-signature", flags=0)
    try:
        os.write(content_fd, message)
        os.write(signature_fd, signature)
        os.lseek(content_fd, 0, os.SEEK_SET)
        os.lseek(signature_fd, 0, os.SEEK_SET)
        result = subprocess.run(
            [
                "/usr/bin/openssl",
                "pkeyutl",
                "-verify",
                "-pubin",
                "-inkey",
                str(key),
                "-rawin",
                "-in",
                f"/proc/self/fd/{content_fd}",
                "-sigfile",
                f"/proc/self/fd/{signature_fd}",
            ],
            pass_fds=(content_fd, signature_fd),
            capture_output=True,
            timeout=3,
            check=False,
        )
        if result.returncode != 0:
            raise WitnessError("launch-witness signature verification failed")
    finally:
        os.close(content_fd)
        os.close(signature_fd)


def _start_ticks(data: bytes) -> int:
    """Parse field 22 of /proc/PID/stat despite spaces in process comm."""
    closing = data.rfind(b") ")
    if closing < 0:
        raise WitnessError("malformed process stat")
    fields = data[closing + 2 :].split()
    if len(fields) < 20:
        raise WitnessError("incomplete process stat")
    return int(fields[19])


def inspect(
    receipt_path: Path,
    *,
    public_key: Path = PUBLIC_KEY,
    expected_sha: str,
    process_root: Path = Path("/proc"),
    boot_id_path: Path = Path("/proc/sys/kernel/random/boot_id"),
    trusted_uid: int = 0,
) -> dict[str, Any]:
    """Bind a signed observation to current PID+boot+start ticks fail-closed."""
    report: dict[str, Any] = {
        "state": "unverified",
        "loaded_python_bytes_independently_proven": False,
        "disposition": "blocked_manual_review",
    }
    try:
        if not SHA.fullmatch(expected_sha):
            raise WitnessError("invalid release SHA")
        data = json.loads(_private_regular(receipt_path, trusted_uid))
        if not isinstance(data, dict):
            raise WitnessError("invalid launch witness record")
        encoded = data.pop("signature_b64", None)
        if not isinstance(encoded, str):
            raise WitnessError("missing signature")
        signature = base64.b64decode(encoded, validate=True)
        canonical = json.dumps(
            data, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode()
        _verify(canonical, signature, public_key, trusted_uid)
        if (
            data.get("schema") != 1
            or data.get("project") != "spifford3472/rolling-thunder-v4"
            or data.get("host") != "anvilmobile"
            or data.get("service") != "rolling-thunder.service"
            or data.get("sha") != expected_sha
        ):
            raise WitnessError("witness scope or release SHA mismatch")
        pid, ticks, boot = data.get("pid"), data.get("start_ticks"), data.get("boot_id")
        if (
            type(pid) is not int
            or not 2 <= pid <= 2**22
            or type(ticks) is not int
            or ticks <= 0
            or not isinstance(boot, str)
            or not BOOT_ID.fullmatch(boot)
        ):
            raise WitnessError("invalid process identity fields")
        issued = datetime.fromisoformat(data["observed_utc"])
        if issued.tzinfo is None or issued.astimezone(UTC) > datetime.now(UTC):
            raise WitnessError("invalid observation time")
        if (datetime.now(UTC) - issued.astimezone(UTC)).total_seconds() > 86400:
            raise WitnessError("observation too old")
        if boot_id_path.read_text(encoding="ascii").strip() != boot:
            raise WitnessError("process boot identity changed")
        process = process_root / str(pid)
        if _start_ticks(process.joinpath("stat").read_bytes()) != ticks:
            raise WitnessError("process start ticks mismatch or PID recycled")
        report["state"] = "signed_launch_observation_bound_to_live_process"
        report["sha"] = expected_sha
        report["pid"] = pid
        # The signer may have observed the intended process at one instant;
        # no independent in-memory module proof is derived from that claim.
    except (
        OSError,
        ValueError,
        TypeError,
        KeyError,
        UnicodeError,
        binascii.Error,
        subprocess.SubprocessError,
    ) as exc:
        report["error"] = type(exc).__name__
    return report


def main() -> int:
    """Always return refusal; signed observation alone is not release-ready."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    parser.add_argument("--sha", required=True)
    args = parser.parse_args()
    print(json.dumps(inspect(args.receipt, expected_sha=args.sha), sort_keys=True))
    return 75


if __name__ == "__main__":
    raise SystemExit(main())
