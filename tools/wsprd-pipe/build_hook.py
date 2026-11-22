"""Build the optional Linux WSPR helper as part of the application package."""

from __future__ import annotations

import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

_SOURCE_NAMES = (
    "wsprd_pipe.c",
    "fano.c",
    "nhash.c",
    "tab.c",
    "wsprd_utils.c",
    "wsprsim_utils.c",
)


class WsprDecoderBuildHook(BuildHookInterface):
    """Include the pipe-only CLI when the build host has a C compiler and FFTW."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        self._build_directory: TemporaryDirectory[str] | None = None
        compiler = shutil.which("cc")
        if sys.platform != "linux" or compiler is None:
            return
        headers = subprocess.run(
            (compiler, "-x", "c", "-E", "-"),
            input=b"#include <fftw3.h>\n",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=10,
        )
        if headers.returncode != 0:
            return

        source_directory = Path(self.root) / "tools" / "wsprd-pipe"
        self._build_directory = TemporaryDirectory(prefix="rolling-thunder-wspr-build-")
        executable = Path(self._build_directory.name) / "rolling-thunder-wsprd"
        subprocess.run(
            (
                compiler,
                "-O3",
                "-o",
                str(executable),
                *(str(source_directory / name) for name in _SOURCE_NAMES),
                "-lfftw3f",
                "-lm",
            ),
            check=True,
            timeout=60,
        )
        build_data["shared_scripts"][str(executable)] = executable.name
        platform_tag = sysconfig.get_platform().replace("-", "_").replace(".", "_")
        build_data["tag"] = f"py3-none-{platform_tag}"
        build_data["pure_python"] = False
        for source in source_directory.iterdir():
            if source.suffix in {".c", ".h", ".py", ".md"} or source.name == "COPYING":
                build_data["shared_data"][str(source)] = f"share/rolling-thunder/wsprd/{source.name}"

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        if self._build_directory is not None:
            self._build_directory.cleanup()
