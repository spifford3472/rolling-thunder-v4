"""Fallback retained-weather state when the optional weather subsystem cannot start."""

from rolling_thunder.forge_weather import ForgeWeatherState, WeatherProviderStatus


class UnavailableForgeWeatherStateSource:
    """Expose a truthful unavailable state without making Forge startup fail."""

    def __init__(self, error: BaseException) -> None:
        text = (str(error).strip() or error.__class__.__name__)[:500]
        self._state = ForgeWeatherState(
            revision=0,
            provider_status=WeatherProviderStatus.UNAVAILABLE,
            startup_storage_error=text,
        )

    def get_state(self) -> ForgeWeatherState:
        """Return the immutable unavailable state without external work."""
        return self._state

    def is_stale(self) -> bool:
        """No retained weather means the weather view is stale/unavailable."""
        return True
