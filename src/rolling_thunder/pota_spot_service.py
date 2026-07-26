"""Application service for refreshing and filtering POTA spot snapshots."""

from collections.abc import Callable
from datetime import UTC, datetime

from pydantic import Field, field_validator, model_validator

from rolling_thunder.domain import DomainModel, RadioMode
from rolling_thunder.pota_spot_source import (
    PotaSpotSource,
    PotaSpotSourceAvailability,
    PotaSpotSourceError,
)
from rolling_thunder.pota_spots import AmateurBand, PotaSpot, filter_pota_spots


class PotaSpotServiceState(DomainModel):
    """Immutable application-facing POTA spot snapshot."""

    availability: PotaSpotSourceAvailability
    spots: tuple[PotaSpot, ...] = ()
    last_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = Field(default=None, max_length=500)

    @field_validator("last_attempt_at", "last_success_at")
    @classmethod
    def normalize_timestamp(cls, value: datetime | None) -> datetime | None:
        """Require aware timestamps and normalize them to UTC."""
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include timezone information")
        return value.astimezone(UTC)

    @field_validator("last_error")
    @classmethod
    def normalize_error(cls, value: str | None) -> str | None:
        """Trim optional errors and convert blank text to None."""
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @model_validator(mode="after")
    def validate_consistency(self) -> "PotaSpotServiceState":
        """Keep availability, timestamps, spots, and errors consistent."""
        if self.availability is PotaSpotSourceAvailability.UNKNOWN:
            if self.last_attempt_at is not None or self.last_error is not None:
                raise ValueError("unknown POTA service state cannot contain attempt data")
        elif self.last_attempt_at is None:
            raise ValueError("known POTA service state requires last_attempt_at")

        if self.availability is PotaSpotSourceAvailability.AVAILABLE:
            if self.last_success_at is None:
                raise ValueError("available POTA service state requires last_success_at")
            if self.last_error is not None:
                raise ValueError("available POTA service state cannot contain last_error")
        elif self.availability is PotaSpotSourceAvailability.UNAVAILABLE:
            if self.last_error is None:
                raise ValueError("unavailable POTA service state requires last_error")
            if self.spots and self.last_success_at is None:
                raise ValueError("stale POTA spots require last_success_at")
        return self

    @property
    def is_stale(self) -> bool:
        """Return whether retained spots came from an earlier successful refresh."""
        return (
            self.availability is PotaSpotSourceAvailability.UNAVAILABLE
            and bool(self.spots)
        )


class PotaSpotService:
    """Refresh and retain POTA spots without background work or transport coupling."""

    def __init__(
        self,
        source: PotaSpotSource,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._source = source
        self._now = now or (lambda: datetime.now(UTC))
        self._state = PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.UNKNOWN,
        )

    def get_state(self) -> PotaSpotServiceState:
        """Return the latest immutable service state without performing I/O."""
        return self._state

    def refresh(self) -> PotaSpotServiceState:
        """Refresh from the source, retaining the last successful spots on failure."""
        attempted_at = self._aware_now()
        try:
            result = self._source.fetch_spots()
        except PotaSpotSourceError as error:
            self._state = self._failed_state(attempted_at, str(error))
            return self._state

        if result.availability is PotaSpotSourceAvailability.UNAVAILABLE:
            self._state = self._failed_state(
                attempted_at,
                result.last_error or "POTA spot source unavailable.",
            )
            return self._state

        if result.availability is not PotaSpotSourceAvailability.AVAILABLE:
            self._state = self._failed_state(
                attempted_at,
                "POTA spot source returned an unknown availability state.",
            )
            return self._state

        self._state = PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.AVAILABLE,
            spots=result.spots,
            last_attempt_at=attempted_at,
            last_success_at=result.fetched_at,
        )
        return self._state

    def filtered_spots(
        self,
        *,
        band: AmateurBand | None = None,
        mode: RadioMode | None = None,
    ) -> tuple[PotaSpot, ...]:
        """Return the retained snapshot filtered without performing I/O."""
        return tuple(
            filter_pota_spots(list(self._state.spots), band=band, mode=mode)
        )

    def _failed_state(self, attempted_at: datetime, error: str) -> PotaSpotServiceState:
        return PotaSpotServiceState(
            availability=PotaSpotSourceAvailability.UNAVAILABLE,
            spots=self._state.spots,
            last_attempt_at=attempted_at,
            last_success_at=self._state.last_success_at,
            last_error=error,
        )

    def _aware_now(self) -> datetime:
        value = self._now()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("POTA spot service clock must return an aware datetime.")
        return value.astimezone(UTC)
