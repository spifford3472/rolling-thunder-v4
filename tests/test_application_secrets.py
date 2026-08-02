import pytest
from pydantic import SecretStr

from rolling_thunder.application_secrets import (
    ApplicationSecrets,
    QrzCredentials,
    SecretConfigurationError,
    load_application_secrets,
)


def test_no_environment_credentials_disables_qrz() -> None:
    secrets = load_application_secrets({})

    assert secrets == ApplicationSecrets()
    assert secrets.qrz is None


def test_environment_credentials_are_loaded_and_redacted() -> None:
    secrets = load_application_secrets(
        {
            "ROLLING_THUNDER_QRZ_USERNAME": "  KI5VNB  ",
            "ROLLING_THUNDER_QRZ_PASSWORD": "private-value",
        }
    )

    assert secrets.qrz == QrzCredentials(
        username="KI5VNB",
        password=SecretStr("private-value"),
    )
    assert secrets.qrz.password.get_secret_value() == "private-value"
    assert "private-value" not in repr(secrets)
    assert "private-value" not in str(secrets)


@pytest.mark.parametrize(
    "environment",
    [
        {"ROLLING_THUNDER_QRZ_USERNAME": "KI5VNB"},
        {"ROLLING_THUNDER_QRZ_PASSWORD": "private-value"},
    ],
)
def test_partial_environment_credentials_are_rejected(
    environment: dict[str, str],
) -> None:
    with pytest.raises(
        SecretConfigurationError,
        match="must either both be set or both be unset",
    ):
        load_application_secrets(environment)
