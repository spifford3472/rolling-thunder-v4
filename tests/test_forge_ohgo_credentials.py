"""Source-disabled, secret-redacted Forge OHGO key loading tests."""

from __future__ import annotations

from rolling_thunder.forge_ohgo_credentials import (
    load_ohgo_credential,
    ohgo_enabled_by_operator,
)


def test_missing_supervisor_credentials_disables_provider(monkeypatch) -> None:
    monkeypatch.delenv("CREDENTIALS_DIRECTORY", raising=False)
    monkeypatch.delenv("ROLLING_THUNDER_OHGO_ENABLED", raising=False)
    assert not ohgo_enabled_by_operator()
    assert load_ohgo_credential() is None


def test_systemd_only_credential_file_read(tmp_path, monkeypatch) -> None:
    target = tmp_path / "ohgo-api-key"
    target.write_text("test-only-key\n")
    target.chmod(0o400)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    monkeypatch.setenv("ROLLING_THUNDER_OHGO_ENABLED", "1")
    assert ohgo_enabled_by_operator()
    assert load_ohgo_credential() == "test-only-key"


def test_symlink_and_bad_credential_fail_closed(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(tmp_path))
    key = tmp_path / "ohgo-api-key"
    other = tmp_path / "other"
    other.write_text("unsafe-key")
    key.symlink_to(other)
    assert load_ohgo_credential() is None
    key.unlink()
    key.write_text("bad with whitespace")
    assert load_ohgo_credential() is None
