"""Independent Forge callsign-info process."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from rolling_thunder.application_secrets import (
    SecretConfigurationError,
    load_application_secrets,
)
from rolling_thunder.forge_callsign_info import ForgeCallsignInfoService
from rolling_thunder.forge_callsign_info_api import (
    ForgeCallsignInfoApiApplication,
    ForgeCallsignInfoHttpServer,
)
from rolling_thunder.forge_callsign_info_config import (
    ForgeCallsignInfoConfigurationError,
    load_forge_callsign_info_config,
)
from rolling_thunder.forge_open_meteo_weather import OpenMeteoForgeWeatherProvider
from rolling_thunder.qrz_xml import QrzXmlCallsignNameProvider
from rolling_thunder.wavelog import WavelogClient

DEFAULT_CONFIG_PATH = Path("config/forge-callsign-info.yaml")
EXIT_SUCCESS = 0
EXIT_CONFIGURATION_ERROR = 2
EXIT_RUNTIME_ERROR = 3


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rolling-thunder-forge-callsign-info",
        description="Forge QRZ/Wavelog/weather callsign intelligence service",
    )
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_forge_callsign_info_config(args.config)
        secrets = load_application_secrets()
    except (ForgeCallsignInfoConfigurationError, SecretConfigurationError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return EXIT_CONFIGURATION_ERROR

    if secrets.qrz is None or secrets.wavelog is None:
        print(
            "ERROR: callsign-info requires QRZ credentials and a Wavelog v2 token.",
            file=sys.stderr,
        )
        return EXIT_CONFIGURATION_ERROR

    logger = logging.getLogger("rolling_thunder.forge_callsign_info")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.propagate = False

    try:
        qrz = QrzXmlCallsignNameProvider(
            secrets.qrz,
            timeout_s=config.qrz_request_timeout_s,
        )
        wavelog = WavelogClient(
            str(config.wavelog.base_url).rstrip("/"),
            secrets.wavelog.token,
            station_location_name=config.wavelog.station_location_name,
            timeout_s=config.wavelog.request_timeout_s,
        )
        weather = (
            OpenMeteoForgeWeatherProvider(
                timeout_s=config.weather.request_timeout_s,
                endpoint=str(config.weather.endpoint),
            )
            if config.weather.enabled
            else None
        )
        service = ForgeCallsignInfoService(
            qrz,
            wavelog,
            weather,
            profile_ttl_s=config.profile_cache_ttl_s,
            negative_profile_ttl_s=config.negative_profile_cache_ttl_s,
            history_ttl_s=config.history_cache_ttl_s,
            station_ttl_s=config.station_cache_ttl_s,
            weather_ttl_s=config.weather.cache_ttl_s,
        )
        application = ForgeCallsignInfoApiApplication(service)
        server = ForgeCallsignInfoHttpServer(
            config.server.bind_host,
            config.server.bind_port,
            application,
            logger=logger,
        )
    except (OSError, ValueError) as error:
        logger.error("Callsign-info service could not start: %s", error)
        return EXIT_RUNTIME_ERROR

    host, port = server.server_address
    logger.info("Forge callsign-info API listening on http://%s:%s", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Callsign-info service interrupted; shutting down.")
    except OSError as error:
        logger.error("Callsign-info service failed: %s", error)
        return EXIT_RUNTIME_ERROR
    finally:
        server.close()
    return EXIT_SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
