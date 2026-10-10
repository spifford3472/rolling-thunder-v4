"""Contact-sync configuration excludes provider work from the upload process."""

from pathlib import Path

import pytest

from rolling_thunder.forge_contact_sync_config import (
    ForgeContactSyncConfigurationError,
    load_forge_contact_sync_config,
)


def test_contact_sync_rejects_obsolete_weather_provider_configuration(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "forge-contact-sync.yaml"
    config_path.write_text("weather:\n  enabled: true\n", encoding="utf-8")

    with pytest.raises(ForgeContactSyncConfigurationError, match="weather"):
        load_forge_contact_sync_config(config_path)
