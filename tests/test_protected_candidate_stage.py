"""Private offline candidate staging never overwrites or executes releases."""

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path
from zipfile import ZipFile

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "deploy/rolling-thunder-stage-candidate.py"
SPEC = importlib.util.spec_from_file_location("rt_stab07f_stage", SOURCE)
assert SPEC and SPEC.loader
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)
SHA = "a" * 40


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tar(files: dict[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for name, data in sorted(files.items()):
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return stream.getvalue()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, str, str]:
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    app = tmp_path / "rolling_thunder-4.4.1-py3-none-any.whl"
    with ZipFile(app, "w") as output:
        output.writestr("rolling_thunder-4.4.1.dist-info/RECORD", "")
    dependency = b"pinned-wheel-fixture"
    wheel_name = "pillow-1.0-py3-none-any.whl"
    lock = {"packages": {"pillow": {"file": wheel_name, "sha256": _sha(dependency)}}}
    code = b"# verified code\n"
    sources = {"src/rolling_thunder/ui_main.py": code}
    sources["source-manifest.json"] = json.dumps(
        {
            "git_commit": SHA,
            "source_files": {"src/rolling_thunder/ui_main.py": _sha(code)},
        }
    ).encode()
    blobs = {
        "source.tar": _tar(sources),
        "dependency-lock.json": json.dumps(lock).encode(),
        "wheels/" + wheel_name: dependency,
    }
    manifest = {
        "schema": 1,
        "type": "offline-transport-payload-not-installable",
        "git_commit": SHA,
        "components_sha256": {name: _sha(blob) for name, blob in blobs.items()},
        "verified_wheels": 1,
        "production_ready": False,
        "interpreter_included": False,
        "signed_release": False,
        "root_owned_release": False,
        "loaded_code_proven": False,
    }
    blobs["release-payload.json"] = json.dumps(manifest).encode()
    bundle = tmp_path / "bundle.tar"
    bundle.write_bytes(_tar(blobs))
    return root, bundle, app, _sha(bundle.read_bytes()), _sha(app.read_bytes())


def _run(tmp_path: Path) -> Path:
    root, bundle, app, digest, app_hash = _fixture(tmp_path)
    return stage.stage(root, bundle, app, SHA, app_hash, digest)


def test_private_staging_is_readonly_and_marked_not_executable(tmp_path: Path) -> None:
    destination = _run(tmp_path)
    assert destination.name == SHA
    assert destination.stat().st_mode & 0o777 == 0o500
    assert (destination / "source.tar").stat().st_mode & 0o777 == 0o400
    record = json.loads((destination / "staging-record.json").read_text())
    assert record["production_ready"] is False
    assert record["native_arm64_executed"] is False
    assert record["os_interpreter_included"] is False
    assert record["installed_venv"] is False
    assert record["root_owned_production_release"] is False
    assert record["loaded_python_bytes_independently_proven"] is False


def test_poststage_verifier_rejects_modified_or_extra_artifacts(tmp_path: Path) -> None:
    destination = _run(tmp_path)
    root = destination.parent
    assert stage.verify_staged(root, SHA)["state"] == "offline_staged_files_integrity_verified"
    source = destination / "source.tar"
    source.chmod(0o600)
    source.write_bytes(source.read_bytes() + b"injected")
    source.chmod(0o400)
    with pytest.raises(stage.StageError, match="hash mismatch"):
        stage.verify_staged(root, SHA)


def test_poststage_verifier_rejects_fake_approval_and_missing_files(tmp_path: Path) -> None:
    destination = _run(tmp_path)
    root = destination.parent
    manifest = destination / "staging-record.json"
    document = json.loads(manifest.read_text())
    document["production_ready"] = True
    manifest.chmod(0o600)
    manifest.write_text(json.dumps(document))
    manifest.chmod(0o400)
    with pytest.raises(stage.StageError, match="falsely approved"):
        stage.verify_staged(root, SHA)
    document["production_ready"] = False
    manifest.chmod(0o600)
    manifest.write_text(json.dumps(document))
    manifest.chmod(0o400)
    # Deliberate fixture tampering must first undo the read-only directory.
    destination.chmod(0o700)
    (destination / "source.tar").unlink()
    destination.chmod(0o500)
    with pytest.raises(stage.StageError, match="missing staged"):
        stage.verify_staged(root, SHA)


def test_existing_candidate_is_never_replaced(tmp_path: Path) -> None:
    root, bundle, app, digest, app_hash = _fixture(tmp_path)
    existing = root / SHA
    existing.mkdir()
    (existing / "sentinel").write_text("old-release")
    with pytest.raises(stage.StageError, match="already exists"):
        stage.stage(root, bundle, app, SHA, app_hash, digest)
    assert (existing / "sentinel").read_text() == "old-release"
    assert not list(root.glob(".candidate-*"))


def test_existing_empty_candidate_also_refuses_atomic_replace(tmp_path: Path) -> None:
    root, _bundle, _app, _digest, _app_hash = _fixture(tmp_path)
    existing = root / SHA
    existing.mkdir()
    other = root / "other"
    other.mkdir()
    with pytest.raises(stage.StageError, match="atomic no-replace"):
        stage._atomic_noreplace(other, existing)
    assert other.is_dir() and existing.is_dir()


def test_modified_transport_and_application_hash_refused(tmp_path: Path) -> None:
    root, bundle, app, digest, app_hash = _fixture(tmp_path)
    bundle.write_bytes(bundle.read_bytes() + b"tampered")
    with pytest.raises(stage.StageError, match="transport payload differs"):
        stage.stage(root, bundle, app, SHA, app_hash, digest)
    assert list(root.iterdir()) == []
    bundle.write_bytes(bundle.read_bytes()[:-8])
    app.write_bytes(app.read_bytes() + b"tampered")
    with pytest.raises(stage.StageError, match="app wheel hash"):
        stage.stage(root, bundle, app, SHA, app_hash, digest)
    assert list(root.iterdir()) == []


def test_unsafe_root_and_symlinked_bundle_refused(tmp_path: Path) -> None:
    root, bundle, app, digest, app_hash = _fixture(tmp_path)
    root.chmod(0o777)
    with pytest.raises(stage.StageError, match="private"):
        stage.stage(root, bundle, app, SHA, app_hash, digest)
    root.chmod(0o700)
    moved = tmp_path / "original.tar"
    bundle.rename(moved)
    bundle.symlink_to(moved)
    with pytest.raises(stage.StageError, match="symlinked"):
        stage.stage(root, bundle, app, SHA, app_hash, digest)


def test_untrusted_source_manifest_refused_even_if_payload_digest_updated(tmp_path: Path) -> None:
    root, bundle, app, _digest, app_hash = _fixture(tmp_path)
    files = stage._read_archive(bundle.read_bytes())
    sources = stage._read_archive(files["source.tar"])
    sources["src/rolling_thunder/ui_main.py"] = b"modified"
    files["source.tar"] = _tar(sources)
    manifest = json.loads(files["release-payload.json"])
    manifest["components_sha256"]["source.tar"] = _sha(files["source.tar"])
    files["release-payload.json"] = json.dumps(manifest).encode()
    bundle.write_bytes(_tar(files))
    with pytest.raises(stage.StageError, match="source manifest"):
        stage.stage(root, bundle, app, SHA, app_hash, _sha(bundle.read_bytes()))


def test_readonly_files_cannot_be_mutated_without_approved_permission_change(
    tmp_path: Path,
) -> None:
    destination = _run(tmp_path)
    record = (destination / "staging-record.json").read_bytes()
    assert b'"production_ready": false' in record
    assert (destination / "staging-record.json").stat().st_mode & 0o222 == 0
    assert os.geteuid() == destination.stat().st_uid
