#!/usr/bin/env bash
# Read-only, local parked/drive acceptance. Does not open MeshCore or GPS tty.
set -uo pipefail
DB="${HOME}/.local/share/meshcore-collector/meshcore-observations.db"
SOCKET="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/meshcore-collector.sock"
PYTHON="${HOME}/projects/rolling-thunder-v4/.venv/bin/python"

echo "MeshCore independent collector acceptance: $(date -Is)"
echo "Rolling Thunder: $(systemctl is-active rolling-thunder.service 2>/dev/null)"
echo "Collector: $(systemctl --user is-active meshcore-collector.service 2>/dev/null)"
echo "Heltec: $(readlink -f /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1.1:1.0 2>/dev/null)"
echo "GPS: $(readlink -f /dev/serial/by-path/platform-fd500000.pcie-pci-0000:01:00.0-usb-0:1.1.4:1.0-port0 2>/dev/null)"
if command -v curl >/dev/null 2>&1 && [[ -S "$SOCKET" ]]; then
  echo "Read-only collector health:"
  curl --silent --show-error --max-time 3 --unix-socket "$SOCKET" http://localhost/v1/health
  printf '\n'
fi
if [[ -f "$DB" ]]; then
  "$PYTHON" - "$DB" <<'PY'
import sqlite3
import sys

path = sys.argv[1]
with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as db:
    print("SQLite:", db.execute("PRAGMA quick_check").fetchone()[0])
    for table in ("meshcore_observed_nodes", "meshcore_observations",
                  "meshcore_signal_samples"):
        print(table, db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    print("GPS outcomes:", db.execute(
        "SELECT gps_status, COUNT(*) FROM meshcore_observations "
        "GROUP BY gps_status"
    ).fetchall())
    print("Latest observation:", db.execute(
        "SELECT MAX(received_at_utc) FROM meshcore_observations"
    ).fetchone()[0])
PY
else
  echo "SQLite: not installed"
fi
echo "USB errors since collector service activation (if journal access allowed):"
journalctl -k -b --no-pager 2>/dev/null |
    grep -Ei 'error -71|USB disconnect|over-current' | tail -5 || true
