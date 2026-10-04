"""Composition tests for POTA, DXSpider, and optional Forge QRZ enrichment."""

from collections.abc import Mapping
from pathlib import Path

import pytest
from pydantic import SecretStr

from rolling_thunder.application_secrets import (
    ApplicationSecrets,
    QrzCredentials,
)
from rolling_thunder.forge_config import ForgeApplicationConfig
from rolling_thunder.forge_spot_api import ForgeSpotApiApplication
from rolling_thunder.forge_spot_main import (
    EXIT_CONFIGURATION_ERROR,
    ForgeRuntimeConfigurationError,
    build_forge_runtime,
    main,
)
from rolling_thunder.http_home_platform import HttpResponse
from rolling_thunder.spot_domain import SpotProvider


class FakeServer:
    @property
    def server_address(self) -> tuple[str, int]:
        return "127.0.0.1", 8765

    def serve_forever(self) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def close(self) -> None:
        return None


class RejectingTransport:
    def request(
        self,
        method: str,
        url: str,
        *,
        headers: Mapping[str, str],
        body: bytes | None,
        timeout_s: float,
    ) -> HttpResponse:
        del method, url, headers, body, timeout_s
        raise AssertionError("composition must not perform external HTTP")


class RejectingDxSpiderSessionFactory:
    def open(
        self,
        *,
        host: str,
        port: int,
        connect_timeout_s: float,
        read_timeout_s: float,
    ) -> None:
        del host, port, connect_timeout_s, read_timeout_s
        raise AssertionError("composition must not open a DXSpider session")


def config_for(
    tmp_path: Path,
    *,
    pota: bool,
    dxspider: bool,
    qrz: bool = False,
) -> ForgeApplicationConfig:
    return ForgeApplicationConfig.model_validate(
        {
            "storage": {"database_path": tmp_path / "forge.db"},
            "aggregation": {"refresh_on_start": False},
            "pota": {"enabled": pota},
            "dxspider": {
                "enabled": dxspider,
                "host": "cluster.example.test",
                "login_callsign": "KI5VNB",
            },
            "qrz": {
                "enabled": qrz,
                "minimum_request_interval_s": 0,
            },
        }
    )


def server_factory(
    host: str,
    port: int,
    application: ForgeSpotApiApplication,
) -> FakeServer:
    del host, port, application
    return FakeServer()


def qrz_secrets() -> ApplicationSecrets:
    return ApplicationSecrets(
        qrz=QrzCredentials(
            username="test-user",
            password=SecretStr("test-password"),
        )
    )


@pytest.mark.parametrize(
    ("pota", "dxspider", "expected"),
    [
        (True, False, (SpotProvider.POTA,)),
        (False, True, (SpotProvider.DX,)),
        (True, True, (SpotProvider.DX, SpotProvider.POTA)),
    ],
)
def test_enabled_provider_combinations_compose_without_external_work(
    tmp_path: Path,
    pota: bool,
    dxspider: bool,
    expected: tuple[SpotProvider, ...],
) -> None:
    runtime = build_forge_runtime(
        config_for(tmp_path, pota=pota, dxspider=dxspider),
        server_factory=server_factory,
        transport=RejectingTransport(),
        dxspider_session_factory=RejectingDxSpiderSessionFactory(),
    )

    assert tuple(
        provider.provider for provider in runtime.polling.latest_state.providers
    ) == expected


def test_no_enabled_provider_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        ForgeRuntimeConfigurationError,
        match="POTA, DXSpider, or DX Summit",
    ):
        build_forge_runtime(
            config_for(tmp_path, pota=False, dxspider=False),
            server_factory=server_factory,
        )


def test_qrz_enabled_without_credentials_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(
        ForgeRuntimeConfigurationError,
        match="ROLLING_THUNDER_QRZ_USERNAME",
    ):
        build_forge_runtime(
            config_for(tmp_path, pota=True, dxspider=False, qrz=True),
            server_factory=server_factory,
            secrets=ApplicationSecrets(),
        )


def test_qrz_enabled_with_credentials_composes_without_http(tmp_path: Path) -> None:
    runtime = build_forge_runtime(
        config_for(tmp_path, pota=True, dxspider=True, qrz=True),
        server_factory=server_factory,
        transport=RejectingTransport(),
        dxspider_session_factory=RejectingDxSpiderSessionFactory(),
        secrets=qrz_secrets(),
    )

    assert tuple(
        provider.provider for provider in runtime.polling.latest_state.providers
    ) == (SpotProvider.DX, SpotProvider.POTA)


def test_main_reports_missing_qrz_credentials_as_configuration_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config_path = tmp_path / "forge.yaml"
    config_path.write_text(
        "qrz:\n  enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("ROLLING_THUNDER_QRZ_USERNAME", raising=False)
    monkeypatch.delenv("ROLLING_THUNDER_QRZ_PASSWORD", raising=False)

    result = main(("--config", str(config_path)))

    assert result == EXIT_CONFIGURATION_ERROR
    captured = capsys.readouterr()
    assert "ROLLING_THUNDER_QRZ_USERNAME" in captured.err
    assert "ROLLING_THUNDER_QRZ_PASSWORD" in captured.err
