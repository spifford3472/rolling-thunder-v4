"""Tests for the Rolling Thunder application entry point."""

from pathlib import Path

from pytest import CaptureFixture

from rolling_thunder.main import main


def write_config(tmp_path: Path, content: str) -> Path:
    """Write a temporary startup configuration."""
    path = tmp_path / "rolling-thunder.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_main_starts_with_valid_configuration(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Valid configuration should allow normal startup and logging."""
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 0

    captured = capsys.readouterr()
    assert "Rolling Thunder v4 starting" in captured.out
    assert "KI5VNB" in captured.out
    assert "mock hardware=True" in captured.out
    assert captured.err == ""

    log_text = log_path.read_text(encoding="utf-8")
    assert "Application startup requested" in log_text
    assert "Configuration loaded for operator=KI5VNB" in log_text
    assert "mock_hardware=True" in log_text
    assert "schema_version=2" in log_text


def test_main_reports_missing_configuration_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Missing configuration should be reported and logged without traceback."""
    config_path = tmp_path / "missing.yaml"
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder configuration error" in captured.err
    assert str(config_path) in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "ERROR" in log_text
    assert "Configuration error" in log_text
    assert str(config_path) in log_text
    assert "Traceback" not in log_text


def test_main_reports_invalid_configuration_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Invalid configuration should be reported and logged without traceback."""
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: NOT-A-CALL
  home_grid: EM79xm
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "operator.callsign" in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "ERROR" in log_text
    assert "operator.callsign" in log_text
    assert "Traceback" not in log_text


def test_logging_creates_parent_directory(tmp_path: Path) -> None:
    """Startup logging should create its parent directory automatically."""
    config_path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
""",
    )
    log_path = tmp_path / "nested" / "log" / "rolling-thunder.log"

    assert not log_path.parent.exists()

    assert main(config_path, log_path) == 0

    assert log_path.is_file()


def test_main_reports_storage_failure_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Storage initialization failures should be concise and logged."""
    database_path = tmp_path / "database-directory"
    database_path.mkdir()

    config_path = write_config(
        tmp_path,
        f"""
operator:
  callsign: KI5VNB
  home_grid: EM79xm
storage:
  database_path: {database_path}
""",
    )
    log_path = tmp_path / "logs" / "rolling-thunder.log"

    assert main(config_path, log_path) == 3

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder storage error" in captured.err
    assert str(database_path) in captured.err
    assert "Traceback" not in captured.err

    log_text = log_path.read_text(encoding="utf-8")
    assert "Storage error" in log_text
    assert str(database_path) in log_text
    assert "Traceback" not in log_text
