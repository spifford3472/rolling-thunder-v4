"""Static safety checks for the production Forge deployment assets."""

import os
import shlex
import subprocess
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
UNIT_PATH = ROOT / "deploy/systemd/rolling-thunder-forge-spots.service"
CONFIG_PATH = ROOT / "config/forge-spots.production.example.yaml"


def test_systemd_service_uses_dedicated_unprivileged_account() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "User=rollingthunder" in unit
    assert "Group=rollingthunder" in unit
    assert "User=root" not in unit
    assert "User=geoff" not in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=" in unit


def test_systemd_service_uses_production_paths_and_persistent_state() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "WorkingDirectory=/opt/rolling-thunder-forge" in unit
    assert (
        "ExecStart=/opt/rolling-thunder-forge/.venv/bin/"
        "rolling-thunder-forge-spots "
        "--config /etc/rolling-thunder/forge-spots.yaml"
    ) in unit
    assert "StateDirectory=rolling-thunder" in unit
    assert "StateDirectoryMode=0750" in unit


def test_systemd_service_loads_secrets_only_from_external_environment_file() -> None:
    unit = UNIT_PATH.read_text(encoding="utf-8")

    assert "EnvironmentFile=-/etc/rolling-thunder/forge-spots.env" in unit
    assert "ROLLING_THUNDER_QRZ_USERNAME=" not in unit
    assert "ROLLING_THUNDER_QRZ_PASSWORD=" not in unit


def test_production_example_uses_radio_lan_only_and_checkpoint_8_port() -> None:
    config = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["server"] == {
        "bind_host": "192.168.9.170",
        "bind_port": 8766,
    }
    assert config["storage"]["database_path"] == (
        "/var/lib/rolling-thunder/forge-spots.db"
    )
    assert config["server"]["bind_host"] != "0.0.0.0"


def test_production_example_contains_no_qrz_credentials() -> None:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(text)

    assert config["qrz"]["enabled"] is False
    assert "username:" not in text.lower()
    assert "password:" not in text.lower()
    assert "ROLLING_THUNDER_QRZ_USERNAME=..." in text
    assert "ROLLING_THUNDER_QRZ_PASSWORD=..." in text



CALLSIGN_UNIT_PATH = ROOT / "deploy/systemd/rolling-thunder-forge-callsign-info.service"
CALLSIGN_CONFIG_PATH = ROOT / "config/forge-callsign-info.example.yaml"


def test_callsign_info_service_uses_private_unprivileged_deployment() -> None:
    unit = CALLSIGN_UNIT_PATH.read_text(encoding="utf-8")
    config = yaml.safe_load(CALLSIGN_CONFIG_PATH.read_text(encoding="utf-8"))

    assert "User=rollingthunder" in unit
    assert "Group=rollingthunder" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=" in unit
    assert config["server"] == {
        "bind_host": "192.168.9.170",
        "bind_port": 8788,
    }


def test_callsign_info_service_keeps_credentials_out_of_yaml_and_unit() -> None:
    unit = CALLSIGN_UNIT_PATH.read_text(encoding="utf-8")
    text = CALLSIGN_CONFIG_PATH.read_text(encoding="utf-8")

    assert "EnvironmentFile=/etc/rolling-thunder/forge-callsign-info.env" in unit
    assert "ROLLING_THUNDER_QRZ_USERNAME=" not in unit
    assert "ROLLING_THUNDER_QRZ_PASSWORD=" not in unit
    assert "ROLLING_THUNDER_WAVELOG_V2_TOKEN=" not in unit
    assert "username:" not in text.lower()
    assert "password:" not in text.lower()
    assert "token:" not in text.lower()


PROPAGATION_UNIT_PATH = ROOT / "deploy/systemd/rolling-thunder-forge-propagation.service"
PROPAGATION_CONFIG_PATH = ROOT / "config/forge-propagation.production.example.yaml"
PROPAGATION_SYSUSERS_PATH = (
    ROOT / "deploy/sysusers.d/rolling-thunder-forge-propagation.conf"
)
PROPAGATION_ROLLOUT_PATH = ROOT / "deploy/forge-propagation-rollout"
PROPAGATION_DEPLOY_HOOK_PATH = (
    ROOT / "deploy/rolling-thunder-forge-deploy-propagation"
)
PROPAGATION_DISPATCH_EXAMPLE_PATH = (
    ROOT / "deploy/rolling-thunder-forge-deploy-propagation-dispatch.example"
)
PROPAGATION_STAGE_PREPARER_PATH = (
    ROOT / "deploy/prepare-forge-propagation-stage"
)
PSKREPORTER_UNIT_PATH = (
    ROOT / "deploy/systemd/rolling-thunder-forge-pskreporter.service"
)
PSKREPORTER_CONFIG_PATH = (
    ROOT / "config/forge-pskreporter-worker.production.example.yaml"
)
PSKREPORTER_SYSUSERS_PATH = (
    ROOT / "deploy/sysusers.d/rolling-thunder-forge-pskreporter.conf"
)
PSKREPORTER_ENV_PATH = (
    ROOT / "deploy/systemd/forge-pskreporter-worker.env.example"
)


def test_pskreporter_service_is_independent_hardened_and_unprivileged() -> None:
    unit = PSKREPORTER_UNIT_PATH.read_text(encoding="utf-8")
    sysusers = PSKREPORTER_SYSUSERS_PATH.read_text(encoding="utf-8")

    assert "User=rolling-thunder-pskreporter" in unit
    assert "Group=rolling-thunder-pskreporter" in unit
    assert "StateDirectory=rolling-thunder-forge-pskreporter" in unit
    assert "NoNewPrivileges=true" in unit
    assert "PrivateDevices=true" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "rolling-thunder-forge-propagation.service" not in unit
    assert "rolling-thunder-forge-contact-sync.service" not in unit
    assert "/usr/sbin/nologin" in sysusers


def test_pskreporter_production_template_is_triple_disabled_and_isolated() -> None:
    config = yaml.safe_load(PSKREPORTER_CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["enabled"] is False
    assert config["ingestion_enabled"] is False
    assert config["pskreporter"]["enabled"] is False
    assert config["pskreporter"]["minimum_query_interval_s"] >= 300
    assert config["pskreporter"]["report_latency_s"] >= 300
    assert config["orchestration_database_path"] != config["history_database_path"]
    assert "rolling-thunder-forge-pskreporter" in config["orchestration_database_path"]
    assert "rolling-thunder-forge-pskreporter" in config["history_database_path"]


def test_pskreporter_secret_is_external_and_preflight_is_provider_free() -> None:
    unit = PSKREPORTER_UNIT_PATH.read_text(encoding="utf-8")
    config_text = PSKREPORTER_CONFIG_PATH.read_text(encoding="utf-8")
    environment = PSKREPORTER_ENV_PATH.read_text(encoding="utf-8")

    assert (
        "EnvironmentFile=-/etc/rolling-thunder-forge-pskreporter/"
        "forge-pskreporter-worker.env"
    ) in unit
    assert "--check-config" in unit
    assert "ROLLING_THUNDER_PSKREPORTER_INGEST_TOKEN=" not in unit
    assert "ROLLING_THUNDER_PSKREPORTER_INGEST_TOKEN=" not in config_text
    assert "ROLLING_THUNDER_PSKREPORTER_INGEST_TOKEN=" in environment


def _write_console_script_fixture_wheel(wheelhouse: Path) -> Path:
    wheel = wheelhouse / "rolling_thunder-0-py3-none-any.whl"
    dist_info = "rolling_thunder-0.dist-info"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("rolling_thunder_fixture/__init__.py", "")
        archive.writestr(
            "rolling_thunder_fixture/cli.py",
            "def main():\n    return 0\n",
        )
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\nName: rolling-thunder\nVersion: 0\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test fixture\n"
            "Root-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(
            f"{dist_info}/entry_points.txt",
            "[console_scripts]\n"
            "rolling-thunder-forge-propagation = rolling_thunder_fixture.cli:main\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return wheel


def _write_deploy_hook_harness(
    tmp_path: Path,
    application_root: Path,
    invocation: str,
) -> tuple[Path, dict[str, str]]:
    hook = PROPAGATION_DEPLOY_HOOK_PATH.read_text(encoding="utf-8")
    hook = hook.replace(
        'readonly application_root="/opt/rolling-thunder-forge-propagation"',
        f"readonly application_root={shlex.quote(str(application_root))}",
    )
    hook = hook.replace('chown root:"${service_user}"', ":")
    hook = hook.replace('chown -R root:"${service_user}"', ":")
    hook = hook.replace(
        'install -o root -g "${service_user}" -m 0640',
        "install -m 0640",
    )
    hook = hook.removesuffix('main "$@"\n') + f"{invocation}\n"

    harness = tmp_path / "deploy-hook-harness"
    harness.write_text(hook, encoding="utf-8")
    harness.chmod(0o755)

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    runuser = stub_bin / "runuser"
    runuser.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "while [[ \"$1\" != \"--\" ]]; do shift; done\n"
        "shift\n"
        "exec \"$@\"\n",
        encoding="utf-8",
    )
    runuser.chmod(0o755)
    environment = os.environ | {"PATH": f"{stub_bin}{os.pathsep}{os.environ['PATH']}"}
    return harness, environment


def test_propagation_service_is_independent_and_unprivileged() -> None:
    unit = PROPAGATION_UNIT_PATH.read_text(encoding="utf-8")
    sysusers = PROPAGATION_SYSUSERS_PATH.read_text(encoding="utf-8")

    assert "User=rolling-thunder-propagation" in unit
    assert "Group=rolling-thunder-propagation" in unit
    assert "User=root" not in unit
    assert "User=geoff" not in unit
    assert "StateDirectory=rolling-thunder-forge-propagation" in unit
    assert "NoNewPrivileges=true" in unit
    assert "CapabilityBoundingSet=" in unit
    assert "PrivateDevices=true" in unit
    assert "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6" in unit
    assert (
        "InaccessiblePaths=-/etc/rolling-thunder -/var/lib/rolling-thunder "
        "-/opt/rolling-thunder-forge-contact-sync"
    ) in unit
    assert "rolling-thunder-propagation" in sysusers
    assert "/usr/sbin/nologin" in sysusers


def test_propagation_install_docs_persist_the_sysusers_definition() -> None:
    documentation = (ROOT / "docs/PROPAGATION_HISTORY.md").read_text(encoding="utf-8")

    assert "/etc/sysusers.d/rolling-thunder-forge-propagation.conf" in documentation
    assert "systemd-sysusers rolling-thunder-forge-propagation.conf" in documentation


def test_propagation_service_uses_only_dedicated_paths_and_entry_point() -> None:
    unit = PROPAGATION_UNIT_PATH.read_text(encoding="utf-8")
    execution_directives = "\n".join(
        line for line in unit.splitlines() if line.startswith("Exec")
    )

    assert (
        "WorkingDirectory=/opt/rolling-thunder-forge-propagation/current" in unit
    )
    assert (
        "ExecStartPre=/opt/rolling-thunder-forge-propagation/current/.venv/bin/"
        "rolling-thunder-forge-propagation --config "
        "/etc/rolling-thunder-forge-propagation/forge-propagation.yaml --check-config"
    ) in unit
    assert (
        "ExecStart=/opt/rolling-thunder-forge-propagation/current/.venv/bin/"
        "rolling-thunder-forge-propagation --config "
        "/etc/rolling-thunder-forge-propagation/forge-propagation.yaml"
    ) in unit
    assert "forge-contact-sync" not in execution_directives
    assert "rolling-thunder-forge-spots" not in execution_directives
    assert "wavelog" not in execution_directives.lower()


def test_propagation_production_config_is_disabled_and_isolated() -> None:
    config = yaml.safe_load(PROPAGATION_CONFIG_PATH.read_text(encoding="utf-8"))

    assert config["enabled"] is False
    assert config["database_path"] == (
        "/var/lib/rolling-thunder-forge-propagation/propagation-history.sqlite3"
    )
    assert config["collection_interval_s"] >= 3600
    assert config["retry_initial_backoff_s"] >= config["collection_interval_s"]
    assert config["provider_timeout_s"] <= 60
    assert config["voacap_enabled"] is False
    assert config["weather_enrichment_enabled"] is False
    assert config["pskreporter"]["enabled"] is False


def test_propagation_rollout_requires_explicit_network_and_activation_confirmation() -> None:
    rollout = PROPAGATION_ROLLOUT_PATH.read_text(encoding="utf-8")

    assert "--confirm-hamqsl-kc2g-egress" in rollout
    assert "--confirm-activate" in rollout
    assert "run_as_service --check-config" in rollout
    assert "run_as_service --status" in rollout
    assert "run_as_service --once" in rollout
    assert 'systemctl disable --now "${service_name}"' in rollout
    assert 'systemctl disable --now "${service_name}" 2>/dev/null || true' not in rollout
    assert 'state_path="/var/lib/rolling-thunder-forge-propagation"' in rollout
    assert 'test -w "${state_path}"' in rollout
    assert '"${account_shell}" == "/usr/sbin/nologin"' in rollout
    assert "validate_phase1_plan" in rollout
    assert '"pskreporter_enabled": false' in rollout
    assert '"voacap_enabled": false' in rollout
    assert '"weather_enrichment_enabled": false' in rollout
    assert "systemd-analyze verify" in rollout
    assert "/etc/rolling-thunder-forge-propagation/forge-propagation.yaml" in rollout
    assert 'config_path="/etc/rolling-thunder/forge-propagation.yaml"' not in rollout
    assert "rolling-thunder.service" not in rollout
    assert "rolling-thunder-forge-contact-sync.service" not in rollout


def test_propagation_rollout_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(PROPAGATION_ROLLOUT_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_propagation_rollout_rejects_extra_arguments_before_any_action() -> None:
    result = subprocess.run(
        ["bash", str(PROPAGATION_ROLLOUT_PATH), "status", "unexpected"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "usage:" in result.stderr


def test_propagation_deploy_hook_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(PROPAGATION_DEPLOY_HOOK_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["28f798a"],
        ["A" * 40],
        ["g" * 40],
        ["0" * 39],
        ["0" * 41],
        ["--help"],
        ["0" * 40, "extra"],
    ],
)
def test_propagation_deploy_hook_rejects_non_exact_sha_arguments(
    arguments: list[str],
) -> None:
    result = subprocess.run(
        ["bash", str(PROPAGATION_DEPLOY_HOOK_PATH), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Propagation release" not in result.stdout


def test_propagation_deploy_hook_does_not_evaluate_sha_text(tmp_path: Path) -> None:
    marker = tmp_path / "injected"
    malicious = f"{'0' * 40};touch {marker}"

    result = subprocess.run(
        ["bash", str(PROPAGATION_DEPLOY_HOOK_PATH), malicious],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert not marker.exists()


def test_propagation_deploy_hook_is_path_and_service_isolated() -> None:
    hook = PROPAGATION_DEPLOY_HOOK_PATH.read_text(encoding="utf-8")
    main_body = hook.split("main() {", maxsplit=1)[1]
    systemctl_lines = [
        line.strip()
        for line in hook.splitlines()
        if line.lstrip().startswith("systemctl ")
    ]

    assert PROPAGATION_DEPLOY_HOOK_PATH.stat().st_mode & 0o111
    assert 'service_name="rolling-thunder-forge-propagation.service"' in hook
    assert 'service_user="rolling-thunder-propagation"' in hook
    assert 'application_root="/opt/rolling-thunder-forge-propagation"' in hook
    assert (
        'staging_root="/var/lib/rolling-thunder-forge-deploy/propagation"' in hook
    )
    assert 'lock_path="/run/lock/rolling-thunder-forge-propagation-deploy.lock"' in hook
    assert "flock --nonblock" in hook
    assert "^/" not in hook  # no caller-supplied absolute-path regular expression
    assert "rolling-thunder.service" not in hook
    assert "rolling-thunder-forge-spots.service" not in hook
    assert "rolling-thunder-forge-contact-sync.service" not in hook
    assert systemctl_lines
    assert all('"${service_name}"' in line for line in systemctl_lines)
    assert 'systemctl restart "${service_name}"' in hook
    assert "systemctl enable" not in hook
    assert "systemctl disable" not in hook
    assert "daemon-reload" not in hook
    assert "--no-index" in hook
    assert '[[ "$1" =~ ^[0-9a-f]{40}$ ]]' in hook
    assert "cmp --silent <(printf '%s\\n' \"${sha}\")" in hook
    assert main_body.index('validate_arguments "$@"') < main_body.index("require_root")


def test_propagation_deploy_hook_installs_real_launcher_at_final_path(
    tmp_path: Path,
) -> None:
    sha = "1" * 40
    application_root = tmp_path / "application"
    releases_root = application_root / "releases"
    releases_root.mkdir(parents=True)
    stage = tmp_path / "stage"
    wheelhouse = stage / "wheelhouse"
    wheelhouse.mkdir(parents=True)
    _write_console_script_fixture_wheel(wheelhouse)
    (stage / "COMMIT_SHA").write_text(f"{sha}\n", encoding="utf-8")
    harness, environment = _write_deploy_hook_harness(
        tmp_path,
        application_root,
        'install_release "$1" "$2"',
    )

    result = subprocess.run(
        [str(harness), sha, str(stage)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    release = releases_root / sha
    launcher = release / ".venv/bin/rolling-thunder-forge-propagation"
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(release)
    assert launcher.is_file()
    launcher_text = launcher.read_text(encoding="utf-8")
    shebang = launcher_text.splitlines()[0]
    assert shebang.startswith("#!")
    assert str(release / ".venv/bin") in launcher_text
    assert ".incoming." not in launcher_text
    subprocess.run([str(launcher), "--help"], check=True)
    assert not list(releases_root.glob(f".{sha}.incoming.*"))


def test_propagation_deploy_hook_rejects_existing_broken_release_before_switch(
    tmp_path: Path,
) -> None:
    sha = "2" * 40
    application_root = tmp_path / "application"
    release = application_root / "releases" / sha
    launcher = release / ".venv/bin/rolling-thunder-forge-propagation"
    launcher.parent.mkdir(parents=True)
    (release / "COMMIT_SHA").write_text(f"{sha}\n", encoding="utf-8")
    launcher.write_text(
        f"#!{application_root}/releases/.{sha}.incoming.removed/.venv/bin/python3\n",
        encoding="utf-8",
    )
    launcher.chmod(0o750)
    current = application_root / "current"
    current.symlink_to("releases/known-good")
    harness, environment = _write_deploy_hook_harness(
        tmp_path,
        application_root,
        'activate_release "$1" "$2"',
    )

    result = subprocess.run(
        [str(harness), sha, str(release)],
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert result.returncode == 2
    assert "failed provider-free validation" in result.stderr
    assert current.readlink() == Path("releases/known-good")
    assert release.is_dir()


def test_propagation_dispatch_fragment_matches_verified_early_interface() -> None:
    fragment = PROPAGATION_DISPATCH_EXAMPLE_PATH.read_text(encoding="utf-8")

    assert "REVIEWED INSERTION FRAGMENT" in fragment
    assert 'if [[ "$1" == "propagation" ]]' in fragment
    assert 'run_as_geoff git -C "${SOURCE_REPO}" fetch origin' in fragment
    assert 'verify_remote_sha "${SOURCE_REPO}" "$2"' in fragment
    assert (
        'exec /usr/local/libexec/rolling-thunder-forge-deploy-propagation "$2"'
        in fragment
    )
    assert fragment.index("fetch origin") < fragment.index("verify_remote_sha")
    assert fragment.index("verify_remote_sha") < fragment.index("exec /usr/local")
    assert "after its existing exact-lowercase-40-SHA argument validation" in fragment
    assert "before its STATE_FILE prerequisite" in fragment
    assert "contact-sync)" not in fragment
    assert "callsign-info)" not in fragment
    assert "spots)" not in fragment
    assert "SPOTS_REPO}" not in fragment


def test_propagation_dispatch_fragment_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(PROPAGATION_DISPATCH_EXAMPLE_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_propagation_stage_preparer_is_unprivileged_and_exact_commit_only() -> None:
    preparer = PROPAGATION_STAGE_PREPARER_PATH.read_text(encoding="utf-8")

    assert PROPAGATION_STAGE_PREPARER_PATH.stat().st_mode & 0o111
    assert '[[ "${sha}" =~ ^[0-9a-f]{40}$ ]]' in preparer
    assert "(( EUID != 0 ))" in preparer
    assert 'git -C "${repo}" fetch origin' in preparer
    assert "refs/remotes/origin/" in preparer
    assert 'git -C "${repo}" archive --format=tar "${sha}"' in preparer
    assert "python3 -m pip wheel" in preparer
    assert "sha256sum -- *.whl > SHA256SUMS" in preparer
    assert "sha256sum --check --strict SHA256SUMS" in preparer
    assert 'printf \'%s\\n\' "${sha}" > "${payload_root}/COMMIT_SHA"' in preparer
    assert "sudo" not in preparer
    assert "release-candidate/20261008/wheelhouse" not in preparer


def test_propagation_stage_preparer_has_valid_bash_syntax() -> None:
    subprocess.run(
        ["bash", "-n", str(PROPAGATION_STAGE_PREPARER_PATH)],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "arguments",
    [
        [],
        ["dry-run"],
        ["unknown", "0" * 40, "/tmp"],
        ["dry-run", "0" * 39, "/tmp"],
        ["dry-run", "A" * 40, "/tmp"],
    ],
)
def test_propagation_stage_preparer_rejects_invalid_arguments(
    arguments: list[str],
) -> None:
    result = subprocess.run(
        ["bash", str(PROPAGATION_STAGE_PREPARER_PATH), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2


def test_propagation_stage_preparer_requires_a_pushed_origin_commit(
    tmp_path: Path,
) -> None:
    git_environment = os.environ.copy()
    local_git_variables = subprocess.run(
        ["git", "rev-parse", "--local-env-vars"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for variable in local_git_variables:
        git_environment.pop(variable, None)

    remote = tmp_path / "remote.git"
    checkout = tmp_path / "checkout"
    artifact_root = tmp_path / "artifacts"
    subprocess.run(
        ["git", "init", "--bare", str(remote)],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(checkout)],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    (checkout / "deploy").mkdir()
    copied_preparer = checkout / "deploy/prepare-forge-propagation-stage"
    copied_preparer.write_bytes(PROPAGATION_STAGE_PREPARER_PATH.read_bytes())
    copied_preparer.chmod(0o755)
    (checkout / "README.md").write_text("pushed\n", encoding="utf-8")
    artifact_root.mkdir()
    subprocess.run(
        ["git", "-C", str(checkout), "add", "."],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "pushed",
        ],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "remote", "add", "origin", str(remote)],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "push", "-u", "origin", "main"],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    pushed_sha = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=git_environment,
    ).stdout.strip()

    accepted = subprocess.run(
        [str(copied_preparer), "dry-run", pushed_sha, str(artifact_root)],
        check=False,
        capture_output=True,
        text=True,
        env=git_environment,
    )

    assert accepted.returncode == 0
    assert f"Verified pushed origin commit: {pushed_sha}" in accepted.stdout
    assert not (artifact_root / pushed_sha).exists()

    stub_bin = tmp_path / "stub-bin"
    stub_bin.mkdir()
    stub_python = stub_bin / "python3"
    stub_python.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
wheel_dir=""
while (( $# > 0 )); do
    if [[ "$1" == "--wheel-dir" ]]; then
        wheel_dir="$2"
        shift 2
    else
        shift
    fi
done
[[ -n "${wheel_dir}" ]]
printf 'stub wheel\n' > "${wheel_dir}/rolling_thunder-0-py3-none-any.whl"
""",
        encoding="utf-8",
    )
    stub_python.chmod(0o755)
    temporary_root = tmp_path / "temporary"
    temporary_root.mkdir()
    build_environment = git_environment | {
        "PATH": f"{stub_bin}{os.pathsep}{git_environment['PATH']}",
        "TMPDIR": str(temporary_root),
    }

    built = subprocess.run(
        [str(copied_preparer), "build", pushed_sha, str(artifact_root)],
        check=False,
        capture_output=True,
        text=True,
        env=build_environment,
    )

    destination = artifact_root / pushed_sha
    wheelhouse = destination / "wheelhouse"
    assert built.returncode == 0
    assert "unbound variable" not in built.stderr
    assert f"Prepared unprivileged exact-commit artifact: {destination}" in built.stdout
    assert (destination / "COMMIT_SHA").read_text(encoding="utf-8") == (
        f"{pushed_sha}\n"
    )
    assert (wheelhouse / "rolling_thunder-0-py3-none-any.whl").is_file()
    assert (wheelhouse / "SHA256SUMS").is_file()
    assert not list(artifact_root.glob(".propagation-stage.*"))
    assert not list(temporary_root.iterdir())

    replacement = subprocess.run(
        [str(copied_preparer), "build", pushed_sha, str(artifact_root)],
        check=False,
        capture_output=True,
        text=True,
        env=build_environment,
    )

    assert replacement.returncode == 2
    assert "refusing to replace existing artifact" in replacement.stderr
    assert (wheelhouse / "rolling_thunder-0-py3-none-any.whl").read_text(
        encoding="utf-8"
    ) == "stub wheel\n"

    (checkout / "README.md").write_text("pushed failure fixture\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(checkout), "add", "README.md"],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "pushed failure fixture",
        ],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    subprocess.run(
        ["git", "-C", str(checkout), "push", "origin", "main"],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    failure_sha = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=git_environment,
    ).stdout.strip()
    stub_python.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")

    failed_build = subprocess.run(
        [str(copied_preparer), "build", failure_sha, str(artifact_root)],
        check=False,
        capture_output=True,
        text=True,
        env=build_environment,
    )

    assert failed_build.returncode == 23
    assert not (artifact_root / failure_sha).exists()
    assert not list(artifact_root.glob(".propagation-stage.*"))
    assert not list(temporary_root.iterdir())

    (checkout / "README.md").write_text("not pushed\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(checkout), "add", "README.md"],
        check=True,
        env=git_environment,
    )
    subprocess.run(
        [
            "git",
            "-C",
            str(checkout),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "not pushed",
        ],
        check=True,
        capture_output=True,
        env=git_environment,
    )
    unpushed_sha = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
        env=git_environment,
    ).stdout.strip()

    rejected = subprocess.run(
        [str(copied_preparer), "dry-run", unpushed_sha, str(artifact_root)],
        check=False,
        capture_output=True,
        text=True,
        env=git_environment,
    )

    assert rejected.returncode == 2
    assert "not contained in a fetched origin branch" in rejected.stderr
    assert not (artifact_root / unpushed_sha).exists()
