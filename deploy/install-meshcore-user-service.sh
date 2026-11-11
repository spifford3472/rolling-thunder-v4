#!/usr/bin/env bash
# Install the independently supervised, local-only MeshCore collector.
# Invoke only after an authorized RT deploy has removed embedded USB ownership.
set -euo pipefail

APP_DIR="${HOME}/projects/rolling-thunder-v4"
OLD_DB="${APP_DIR}/config/data/meshcore-observations.db"
DATA_DIR="${HOME}/.local/share/meshcore-collector"
NEW_DB="${DATA_DIR}/meshcore-observations.db"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="meshcore-collector.service"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/meshcore-collector.sock"
DEVICE="/dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1.1:1.0"

if [[ "$(id -un)" != "geoff" ]]; then
  echo "ERROR: run as geoff on anvilmobile, never as root" >&2
  exit 1
fi
if [[ ! -x "${APP_DIR}/.venv/bin/rolling-thunder-meshcore-collector" ]]; then
  echo "ERROR: standalone collector entry point missing; deploy source first" >&2
  exit 1
fi
if [[ ! -e "$DEVICE" ]]; then
  echo "ERROR: verified V4 physical USB path missing" >&2
  exit 1
fi
if fuser -s /dev/ttyACM0 2>/dev/null; then
  echo "ERROR: MeshCore port still occupied; embedded collector not stopped" >&2
  exit 1
fi
if [[ -e "$SOCKET" ]]; then
  echo "ERROR: collector socket already exists; review running instance" >&2
  exit 1
fi

mkdir -p "$DATA_DIR" "$UNIT_DIR"
chmod 700 "$DATA_DIR"
if [[ ! -e "$NEW_DB" ]]; then
  if [[ ! -f "$OLD_DB" ]]; then
    echo "ERROR: previous MeshCore history missing; refusing empty database" >&2
    exit 1
  fi
  # SQLite's online backup API creates a consistent snapshot without
  # deleting or altering old historical observations.
  "${APP_DIR}/.venv/bin/python" - "$OLD_DB" "$NEW_DB" <<'PY'
import sqlite3
import sys
from pathlib import Path

source, target = map(Path, sys.argv[1:])
with sqlite3.connect(f"file:{source}?mode=ro", uri=True) as old:
    if old.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise SystemExit("ERROR: historical MeshCore DB failed integrity check")
    with sqlite3.connect(target) as new:
        old.backup(new)
        if new.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise SystemExit("ERROR: copied MeshCore DB failed integrity check")
PY
  chmod 600 "$NEW_DB"
fi
install -m 0644 "${APP_DIR}/deploy/meshcore-collector.user.service" "${UNIT_DIR}/$UNIT"
systemctl --user daemon-reload
systemctl --user enable --now "$UNIT"
systemctl --user is-active "$UNIT"
echo "Collector enabled. Database: $NEW_DB"
echo "Read-only local interface: $SOCKET"
