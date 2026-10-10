#!/usr/bin/env bash
# After a root-run pip install, restore service-user read access before restart.
set -euo pipefail
[[ "$(id -u)" -eq 0 && "$#" -eq 0 ]] || { echo 'Run as root without arguments' >&2; exit 2; }
SITE=/opt/rolling-thunder-forge-contact-sync/.venv/lib/python3.12/site-packages
PYTHON=/opt/rolling-thunder-forge-contact-sync/.venv/bin/python
CHECK=/home/geoff/projects/rolling-thunder-v4-ft8-p1/scripts/verify-forge-python-access.py
[[ -d "$SITE/rolling_thunder" && -d "$SITE/rolling_thunder-4.4.0.dist-info" ]] || { echo 'Expected installed package missing' >&2; exit 3; }
chgrp -R rollingthunder "$SITE/rolling_thunder" "$SITE/rolling_thunder-4.4.0.dist-info"
chmod -R g+rX "$SITE/rolling_thunder" "$SITE/rolling_thunder-4.4.0.dist-info"
runuser -u rollingthunder -- "$PYTHON" "$CHECK"
