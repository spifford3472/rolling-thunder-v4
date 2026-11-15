"""Read-only comparison of quarantined Raspberry Pi archives with Pi ELF samples.

Byte equivalence with an observed Pi file is NOT repository authentication,
trusted installation approval, loaded-code attestation, or release readiness.
No dynamic loader or application is started and no package is installed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
from typing import Any

SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MAX_BYTES = 250_000_000
ARCHIVES = {
    "libc6": "libc6_2.41-12+rpt1+deb13u3_arm64.deb",
    "libssl3t64": "libssl3t64_3.5.6-1~deb13u2+rpt1_arm64.deb",
}


class QuarantineEvidenceError(ValueError):
    """Untrusted candidate content is missing, changed or unsafe to inspect."""


def _sha256(path: Path, *, limit: int = MAX_BYTES) -> str:
    """Stream bounded regular files, refusing symlink leaves."""
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise QuarantineEvidenceError("missing, symlinked or oversized file")
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(131072), b""):
            size += len(block)
            if size > limit:
                raise QuarantineEvidenceError("file exceeded bounded size")
            h.update(block)
    return h.hexdigest()


def _checked_child(base: Path, raw: str) -> Path:
    """Resolve a canonical guest POSIX path only underneath a private root."""
    if not raw.startswith("/") or len(raw) > 512 or not raw.startswith(("/lib/", "/usr/")):
        raise QuarantineEvidenceError("not a canonical OS library path")
    if any(part in {"", ".", ".."} for part in raw[1:].split("/")):
        raise QuarantineEvidenceError("noncanonical native path")
    path = PurePosixPath(raw)
    if str(path) != raw:
        raise QuarantineEvidenceError("noncanonical target path")
    candidate = base.joinpath(*path.parts[1:])
    resolved_base = base.resolve(strict=True)
    resolved_file = candidate.resolve(strict=False)
    if not resolved_file.is_relative_to(resolved_base):
        raise QuarantineEvidenceError("file escapes isolated root")
    return candidate


def compare(
    *,
    sample: dict[str, Any],
    quarantine: Path,
    archive_sha256: dict[str, str],
    trusted_overlay: Path | None = None,
) -> dict[str, Any]:
    """Return strict content-only evidence; never elevate a quarantine verdict."""
    if (
        not isinstance(sample, dict)
        or sample.get("host") != "anvilmobile"
        or sample.get("mode") != "read_only_sample"
        or sample.get("production_ready") is not False
        or not isinstance(sample.get("files"), dict)
        or not 1 <= len(sample["files"]) <= 256
    ):
        raise QuarantineEvidenceError("unverified Pi native observation")
    if (
        not isinstance(archive_sha256, dict)
        or set(archive_sha256) != set(ARCHIVES)
        or any(
            not isinstance(v, str) or SHA256_RE.fullmatch(v) is None
            for v in archive_sha256.values()
        )
    ):
        raise QuarantineEvidenceError("missing pinned candidate archive digests")
    if not quarantine.is_absolute() or quarantine.is_symlink() or not quarantine.is_dir():
        raise QuarantineEvidenceError("unsafe private quarantine")
    if trusted_overlay is not None and (
        not trusted_overlay.is_absolute()
        or trusted_overlay.is_symlink()
        or not trusted_overlay.is_dir()
    ):
        raise QuarantineEvidenceError("unsafe independent signed-package overlay")

    # Resolve every archive through the private root, not through a symlinked
    # parent directory that could redirect to station or system files.
    for part in (quarantine / "archives", quarantine / "extracted"):
        if part.is_symlink() or not part.is_dir():
            raise QuarantineEvidenceError("quarantine parent directory is unsafe")
        if not part.resolve(strict=True).is_relative_to(quarantine.resolve(strict=True)):
            raise QuarantineEvidenceError("quarantine parent escapes private root")

    actual_archive_sha256: dict[str, str] = {}
    for pkg, filename in ARCHIVES.items():
        path = quarantine / "archives" / filename
        if not path.resolve(strict=True).is_relative_to(quarantine.resolve(strict=True)):
            raise QuarantineEvidenceError("archive escapes private root")
        digest = _sha256(path)
        if digest != archive_sha256[pkg]:
            raise QuarantineEvidenceError("quarantined archive SHA256 changed")
        actual_archive_sha256[pkg] = digest

    origins: dict[str, Path] = {
        "untrusted_libc6": quarantine / "extracted/libc6",
        "untrusted_openssl": quarantine / "extracted/openssl",
    }
    if trusted_overlay is not None:
        origins["separate_signed_14"] = trusted_overlay

    for origin, base in origins.items():
        if base.is_symlink() or not base.is_dir():
            raise QuarantineEvidenceError("unsafe extracted package directory")
        if origin.startswith("untrusted_") and not base.resolve(strict=True).is_relative_to(
            quarantine.resolve(strict=True)
        ):
            raise QuarantineEvidenceError("extracted package directory escapes quarantine")

    inventory: dict[str, dict[str, str]] = {}
    counts = {origin: 0 for origin in origins}
    counts["absent"] = 0
    for raw, item in sorted(sample["files"].items()):
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("sha256"), str)
            or SHA256_RE.fullmatch(item["sha256"]) is None
            or not isinstance(item.get("resolved"), str)
        ):
            raise QuarantineEvidenceError("invalid recorded native file digest")
        _checked_child(quarantine, raw)  # validate sample's canonical file path
        recorded = item["resolved"]
        _checked_child(quarantine, recorded)
        observed: list[tuple[str, str]] = []
        for origin, base in origins.items():
            file = _checked_child(base, recorded)
            if not file.exists():
                continue
            if file.is_symlink() or not file.is_file():
                raise QuarantineEvidenceError("symlink or special file in extracted evidence")
            digest = _sha256(file)
            if digest != item["sha256"]:
                raise QuarantineEvidenceError(f"native file differs from Pi sample in {origin}")
            observed.append((origin, digest))
        if len(observed) > 1:
            raise QuarantineEvidenceError("multiple candidate origins for the same native file")
        if observed:
            origin, _digest_value = observed[0]
            counts[origin] += 1
            inventory[raw] = {"origin": origin, "observed_pi_sha256": item["sha256"]}
        else:
            counts["absent"] += 1

    return {
        "schema": 1,
        "classification": "CONTENT_EQUIVALENCE_ONLY_NO_SIGNED_HISTORICAL_RPI_INDEX",
        "archives": actual_archive_sha256,
        "sampled_file_count": len(sample["files"]),
        "observed_file_counts": counts,
        "observed_files": inventory,
        "rpi_historical_signed_index_verified": False,
        "archive_release_authenticity_proven": False,
        "debs_authorized_for_execution": False,
        "complete_os_runtime_closure_proven": False,
        "loaded_python_bytes_independently_proven": False,
        "production_ready": False,
        "release_decision": "NO_GO",
    }


def main() -> int:
    """Inspect only; success is content equivalence, never release authorization."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sample", required=True, type=Path)
    parser.add_argument("--quarantine", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True, type=Path)
    parser.add_argument("--trusted-overlay", type=Path)
    args = parser.parse_args()
    try:
        sample = json.loads(args.sample.read_text(encoding="utf-8"))
        pins = json.loads(args.expected_sha256.read_text(encoding="utf-8"))
        outcome = compare(
            sample=sample,
            quarantine=args.quarantine,
            archive_sha256=pins,
            trusted_overlay=args.trusted_overlay,
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        parser.exit(75, f"QUARANTINE EVIDENCE REFUSED: {type(exc).__name__}: {exc}\n")
    print(json.dumps(outcome, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
