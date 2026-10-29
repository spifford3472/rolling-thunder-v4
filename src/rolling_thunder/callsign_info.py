"""Normalized callsign-information models shared by Forge and the Pi."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from rolling_thunder.domain import ContactWeatherObservation, DomainModel


class CallsignInfoFailure(StrEnum):
    """Safe Pi lookup-failure categories published to presentation code."""

    FORGE_UNREACHABLE = "forge_unreachable"
    SERVICE_UNAVAILABLE = "service_unavailable"


class CallsignInfoProfile(DomainModel):
    """Compact QRZ identity and location data needed by the in-car overlay."""

    callsign: str = Field(min_length=1, max_length=32)
    name: str | None = Field(default=None, max_length=160)
    address1: str | None = Field(default=None, max_length=160)
    address2: str | None = Field(default=None, max_length=160)
    state: str | None = Field(default=None, max_length=80)
    country: str | None = Field(default=None, max_length=120)
    grid: str | None = Field(default=None, max_length=12)
    latitude: float | None = Field(default=None, ge=-90.0, le=90.0)
    longitude: float | None = Field(default=None, ge=-180.0, le=180.0)
    coordinate_source: str | None = Field(default=None, max_length=32)
    license_class: str | None = Field(default=None, max_length=80)
    license_effective_date: str | None = Field(default=None, max_length=32)
    license_expiration_date: str | None = Field(default=None, max_length=32)
    birth_year: int | None = Field(default=None, ge=1900, le=2100)


class CallsignInfoLastQso(DomainModel):
    """Purpose-built previous-QSO summary; absent record means FIRST CONTACT."""

    exists: bool
    worked_count: int | None = Field(default=None, ge=1, strict=True)
    band: str | None = Field(default=None, min_length=1, max_length=16)
    occurred_at: datetime | None = None
    station_location: str | None = Field(default=None, max_length=160)
    comments: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=1000)
    qth: str | None = Field(default=None, max_length=200)
    grid: str | None = Field(default=None, max_length=12)
    pota_reference: str | None = Field(default=None, max_length=32)
    my_pota_reference: str | None = Field(default=None, max_length=32)
    mobile: bool | None = None


class CallsignInfoWeather(DomainModel):
    """Small current-weather presentation for the target station or park."""

    temperature_f: int = Field(ge=-150, le=160)
    condition: str = Field(min_length=1, max_length=40)
    location_source: Literal["pota", "qrz"]
    attribution: str | None = Field(default=None, max_length=256)
    timezone: str | None = Field(default=None, min_length=1, max_length=128)
    observation: ContactWeatherObservation | None = None


class CallsignInfoResponse(DomainModel):
    """Versioned compact response returned to anvilmobile."""

    api_schema_version: Literal["1"] = "1"
    callsign: str = Field(min_length=1, max_length=32)
    profile: CallsignInfoProfile | None = None
    last_qso: CallsignInfoLastQso
    weather: CallsignInfoWeather | None = None
