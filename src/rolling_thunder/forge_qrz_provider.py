"""Provider decorator applying bounded best-effort QRZ enrichment."""

from threading import RLock

from rolling_thunder.forge_qrz_enrichment import (
    ForgeQrzEnricher,
    ForgeQrzEnrichmentDiagnostics,
)
from rolling_thunder.forge_spot_provider import (
    ForgeProviderSlice,
    ForgeSpotProvider,
)
from rolling_thunder.spot_domain import SpotProvider


class ForgeQrzEnrichedSpotProvider:
    """Decorate one complete Forge provider slice with optional QRZ metadata."""

    def __init__(
        self,
        provider: ForgeSpotProvider,
        enricher: ForgeQrzEnricher,
    ) -> None:
        self._provider = provider
        self._enricher = enricher
        self._lock = RLock()
        self._last_diagnostics = ForgeQrzEnrichmentDiagnostics(enabled=False)

    @property
    def provider(self) -> SpotProvider:
        """Return the unchanged provider family supplied by the wrapped adapter."""
        return self._provider.provider

    @property
    def last_diagnostics(self) -> ForgeQrzEnrichmentDiagnostics:
        """Return immutable diagnostics from the most recent successful fetch."""
        with self._lock:
            return self._last_diagnostics

    def fetch_slice(self) -> ForgeProviderSlice:
        """Fetch the provider slice, enrich it, and retain bounded diagnostics."""
        provider_slice = self._provider.fetch_slice()
        result = self._enricher.enrich_slice(provider_slice)
        with self._lock:
            self._last_diagnostics = result.diagnostics
        return result.provider_slice
