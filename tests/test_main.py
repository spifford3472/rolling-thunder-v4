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
    """Valid configuration should allow normal startup."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: KI5VNB
  home_grid: EM79xm
hardware:
  mock: true
""",
    )

    assert main(path) == 0

    captured = capsys.readouterr()
    assert "Rolling Thunder v4 starting" in captured.out
    assert "KI5VNB" in captured.out
    assert "mock hardware=True" in captured.out
    assert captured.err == ""


def test_main_reports_missing_configuration_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Missing configuration should return an actionable operator error."""
    path = tmp_path / "missing.yaml"

    assert main(path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Rolling Thunder configuration error" in captured.err
    assert str(path) in captured.err
    assert "Traceback" not in captured.err


def test_main_reports_invalid_configuration_without_traceback(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    """Invalid configuration should return an actionable operator error."""
    path = write_config(
        tmp_path,
        """
operator:
  callsign: NOT-A-CALL
  home_grid: EM79xm
""",
    )

    assert main(path) == 2

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "operator.callsign" in captured.err
    assert "Traceback" not in captured.err
