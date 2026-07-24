"""Tests for the Rolling Thunder application entry point."""

from rolling_thunder.main import main


def test_main_starts_successfully() -> None:
    """The application should start and return success."""
    assert main() == 0