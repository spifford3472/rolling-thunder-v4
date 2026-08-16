"""Central environment-backed secret configuration for Rolling Thunder."""

import os
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator

_QRZ_USERNAME_ENV = "ROLLING_THUNDER_QRZ_USERNAME"
_QRZ_PASSWORD_ENV = "ROLLING_THUNDER_QRZ_PASSWORD"
_WAVELOG_V2_TOKEN_ENV = "ROLLING_THUNDER_WAVELOG_V2_TOKEN"


class SecretConfigurationError(Exception):
    """Raised when required secret values are incomplete or invalid."""


class SecretModel(BaseModel):
    """Frozen base model for secret-bearing configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class QrzCredentials(SecretModel):
    """Credentials for the QRZ XML callsign-data service."""

    username: str
    password: SecretStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        """Require a nonblank QRZ username without exposing it in errors."""
        normalized = value.strip()
        if not normalized:
            raise ValueError("must not be blank")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        """Require a nonblank QRZ password while preserving redaction."""
        if not value.get_secret_value():
            raise ValueError("must not be blank")
        return value


class WavelogCredentials(SecretModel):
    """Bearer token used only by the Forge Wavelog integration."""

    token: SecretStr

    @field_validator("token")
    @classmethod
    def validate_token(cls, value: SecretStr) -> SecretStr:
        """Require a nonblank token while preserving redaction."""
        if not value.get_secret_value().strip():
            raise ValueError("must not be blank")
        return value


class ApplicationSecrets(SecretModel):
    """Complete set of optional runtime secrets."""

    qrz: QrzCredentials | None = None
    wavelog: WavelogCredentials | None = None


def load_application_secrets(
    environ: Mapping[str, str] | None = None,
) -> ApplicationSecrets:
    """Load supported secrets once from an injected or process environment."""
    source = os.environ if environ is None else environ
    username = source.get(_QRZ_USERNAME_ENV, "").strip()
    password = source.get(_QRZ_PASSWORD_ENV, "")
    wavelog_token = source.get(_WAVELOG_V2_TOKEN_ENV, "").strip()

    if bool(username) != bool(password):
        raise SecretConfigurationError(
            f"{_QRZ_USERNAME_ENV} and {_QRZ_PASSWORD_ENV} must either both be set "
            "or both be unset."
        )

    qrz = None
    if username:
        qrz = QrzCredentials(
            username=username,
            password=SecretStr(password),
        )

    wavelog = None
    if wavelog_token:
        wavelog = WavelogCredentials(token=SecretStr(wavelog_token))

    return ApplicationSecrets(qrz=qrz, wavelog=wavelog)
