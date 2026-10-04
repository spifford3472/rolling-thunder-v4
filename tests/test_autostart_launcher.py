from __future__ import annotations

import os
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = REPO_ROOT / "deploy" / "rolling-thunder-autostart"


def _launcher_environment(tmp_path: Path, *, uptime: str, minimum: int) -> dict[str, str]:
    app_dir = tmp_path / "app"
    venv_dir = tmp_path / "venv"
    config_dir = app_dir / "config"
    bin_dir = venv_dir / "bin"

    config_dir.mkdir(parents=True)
    bin_dir.mkdir(parents=True)

    (app_dir / "pyproject.toml").write_text("[project]\nname='test'\n", encoding="utf-8")
    (config_dir / "rolling-thunder.yaml").write_text("{}\n", encoding="utf-8")

    ui = bin_dir / "rolling-thunder-ui"
    ui.write_text("#!/usr/bin/env bash\necho FAKE_UI_STARTED\n", encoding="utf-8")
    ui.chmod(0o755)

    uptime_path = tmp_path / "uptime"
    uptime_path.write_text(f"{uptime} 0.00\n", encoding="utf-8")

    env = os.environ.copy()
    env.update(
        {
            "ROLLING_THUNDER_APP_DIR": str(app_dir),
            "ROLLING_THUNDER_VENV_DIR": str(venv_dir),
            "ROLLING_THUNDER_CONFIG": str(config_dir / "rolling-thunder.yaml"),
            "ROLLING_THUNDER_MIN_UPTIME_SECONDS": str(minimum),
            "ROLLING_THUNDER_UPTIME_PATH": str(uptime_path),
            "XAUTHORITY": str(tmp_path / "missing-Xauthority"),
            "DISPLAY": ":99",
        }
    )
    return env


def test_autostart_launches_immediately_when_minimum_uptime_is_satisfied(
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        ["/usr/bin/bash", str(LAUNCHER)],
        env=_launcher_environment(tmp_path, uptime="181.50", minimum=180),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "minimum uptime 180s already satisfied" in result.stdout
    assert "FAKE_UI_STARTED" in result.stdout


def test_autostart_waits_only_until_minimum_uptime(tmp_path: Path) -> None:
    result = subprocess.run(
        ["/usr/bin/bash", str(LAUNCHER)],
        env=_launcher_environment(tmp_path, uptime="0.25", minimum=1),
        text=True,
        capture_output=True,
        check=True,
    )

    assert "waiting 1s until minimum uptime 1s" in result.stdout
    assert "FAKE_UI_STARTED" in result.stdout
