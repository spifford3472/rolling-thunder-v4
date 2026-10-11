#!/usr/bin/env bash
# PROPOSED ROOT-ONLY COMPONENT-SCOPED HELPER; NOT AN AUTHORIZED INSTALLED WRAPPER.
# The owner must review and install this script as root-owned before any live run.
set -euo pipefail
umask 077
ROOT=/opt/rolling-thunder-forge-ft8-readiness
CONFIG_ROOT=/etc/rolling-thunder-forge-ft8-readiness
STATE=/var/lib/rolling-thunder-forge-ft8-readiness
SERVICE=rolling-thunder-forge-ft8-readiness.service
TIMER=rolling-thunder-forge-ft8-readiness.timer
SYSTEMD=/etc/systemd/system
if [[ $# != 2 ]]; then
  echo 'USAGE: install-forge-ft8-readiness.sh EXACT_40_CHAR_SHA ROOT_OWNED_STAGE_DIRECTORY' >&2
  exit 2
fi
SHA=$1
STAGE=$2
[[ $EUID -eq 0 ]] || { echo 'ERROR: root-only proposed installer' >&2; exit 3; }
[[ $SHA =~ ^[0-9a-f]{40}$ ]] || { echo 'ERROR: malformed commit SHA' >&2; exit 4; }
[[ $STAGE == /var/lib/rolling-thunder-forge-deploy/staging/ft8-readiness/* && -d $STAGE && ! -L $STAGE ]] || { echo 'ERROR: stage must be absolute directory' >&2; exit 4; }
[[ $(stat -c %u "$STAGE") == 0 ]] || { echo 'ERROR: stage must be root-owned' >&2; exit 4; }
[[ $(stat -c %a "$STAGE") == 700 ]] || { echo 'ERROR: stage must be owner-only mode 0700' >&2; exit 4; }
[[ -f "$STAGE/COMMIT_SHA" && $(cat "$STAGE/COMMIT_SHA") == "$SHA" ]] || { echo 'ERROR: commit identity mismatch' >&2; exit 4; }
[[ -f "$STAGE/COMPONENT" && $(cat "$STAGE/COMPONENT") == "forge-ft8-readiness" ]] || { echo 'ERROR: component mismatch' >&2; exit 4; }
[[ -d "$STAGE/wheelhouse" && -f "$STAGE/wheelhouse/SHA256SUMS" ]] || { echo 'ERROR: missing offline wheels' >&2; exit 4; }
(cd "$STAGE/wheelhouse" && sha256sum -c SHA256SUMS)
[[ -f "$STAGE/PROJECT_VERSION" ]] || { echo 'ERROR: missing project version' >&2; exit 4; }
VERSION=$(cat "$STAGE/PROJECT_VERSION")
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo 'ERROR: invalid version' >&2; exit 4; }
[[ -f "$STAGE/$SERVICE" && -f "$STAGE/$TIMER" ]] || { echo 'ERROR: missing unit files' >&2; exit 4; }
[[ -f "$CONFIG_ROOT/policy.yaml" && -f "$CONFIG_ROOT/paths.env" ]] || { echo 'ERROR: protected configuration not initialized' >&2; exit 5; }
[[ $(stat -c %u "$CONFIG_ROOT/policy.yaml") == 0 && $(stat -c %u "$CONFIG_ROOT/paths.env") == 0 ]] || { echo 'ERROR: config must be root owned' >&2; exit 5; }
if [[ -L "$ROOT/current" ]]; then
  CURRENT=$(readlink "$ROOT/current")
  [[ $CURRENT =~ ^releases/[0-9a-f]{40}$ ]] || {
    echo 'ERROR: unknown existing readiness release link' >&2
    exit 6
  }
fi
[[ ! -e "$ROOT/releases/$SHA" ]] || { echo 'ERROR: release already exists' >&2; exit 6; }

# Validate policy and unambiguous literal source variables without executing
# an environment file as shell script. Default/OFF is compulsory at cutover.
python3 - "$CONFIG_ROOT/policy.yaml" "$CONFIG_ROOT/paths.env" <<'PY'
from pathlib import Path
import sys
import yaml
policy = yaml.safe_load(Path(sys.argv[1]).read_text())
assert isinstance(policy, dict) and policy.get('mode') == 'off', 'first installation requires mode: "off"'
expected = {'C3_INBOX_DB_PATH', 'C3_HISTORY_DB_PATH', 'C4_DB_PATH'}
seen = {}
for line in Path(sys.argv[2]).read_text().splitlines():
    line = line.strip()
    if not line or line.startswith('#'):
        continue
    name, sep, value = line.partition('=')
    assert sep and name in expected and name not in seen, 'unrecognized/multiple path variable'
    assert value.startswith('/') and '/REVIEW_REQUIRED/' not in value and '\n' not in value, 'invalid source pathname'
    assert '$' not in value and '"' not in value and "'" not in value and '..' not in value.split('/'), 'unsafe path value'
    seen[name] = value
assert set(seen) == expected, 'missing required C3/C4 path(s)'
print('PASS root-owned OFF policy and three explicit evidence paths')
PY

# Protect existing release state during staging and always permit rollback.
install -d -o root -g root -m 0755 "$ROOT" "$ROOT/releases"
RELEASE="$ROOT/releases/$SHA"
mkdir -m 0755 "$RELEASE"
cleanup_release() { rm -rf -- "$RELEASE"; }
trap cleanup_release ERR
python3 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/pip" install --no-index --find-links "$STAGE/wheelhouse" "rolling-thunder==$VERSION"
"$RELEASE/.venv/bin/rolling-thunder-forge-ft8-readiness-preflight" --help >/dev/null
"$RELEASE/.venv/bin/rolling-thunder-forge-ft8-readiness" --help >/dev/null
python3 - "$CONFIG_ROOT/paths.env" "$RELEASE/.venv/bin/rolling-thunder-forge-ft8-readiness-preflight" <<'PY_PREFLIGHT'
from pathlib import Path
import subprocess,sys
paths = {}
for line in Path(sys.argv[1]).read_text().splitlines():
    if not line or line.startswith('#'):
        continue
    name, _, path = line.partition('=')
    paths[name] = path
subprocess.check_call([sys.argv[2], '--inbox-db', paths['C3_INBOX_DB_PATH'],
    '--history-db', paths['C3_HISTORY_DB_PATH'], '--c4-db', paths['C4_DB_PATH']])
PY_PREFLIGHT
printf '%s\n' "$SHA" > "$RELEASE/COMMIT_SHA"
chown -R root:root "$RELEASE"
chmod -R go-w "$RELEASE"
trap - ERR

# It is deliberate that C4 research and C3 QSO stores are read-only inputs;
# the helper never writes, migrates, backs up or restarts their live services.
mkdir -p /var/backups/rolling-thunder
BACKUP=$(mktemp -d /var/backups/rolling-thunder/ft8-readiness-before-XXXXXX)
chmod 0700 "$BACKUP"
if [[ -L "$ROOT/current" ]]; then
    readlink "$ROOT/current" > "$BACKUP/previous-current"
fi
for unit in "$SERVICE" "$TIMER"; do
    if [[ -f "$SYSTEMD/$unit" ]]; then cp -p "$SYSTEMD/$unit" "$BACKUP/$unit"; fi
done
rollback() {
    echo 'ERROR: readiness activation failed; restoring previous release and units' >&2
    systemctl disable --now "$TIMER" >/dev/null 2>&1 || true
    if [[ -f "$BACKUP/previous-current" ]]; then
        ln -s "$(cat "$BACKUP/previous-current")" "$ROOT/.restore-$$"
        mv -Tf "$ROOT/.restore-$$" "$ROOT/current"
    else
        rm -f "$ROOT/current"
    fi
    for unit in "$SERVICE" "$TIMER"; do
        if [[ -f "$BACKUP/$unit" ]]; then
            cp -p "$BACKUP/$unit" "$SYSTEMD/$unit"
        else
            rm -f "$SYSTEMD/$unit"
        fi
    done
    systemctl daemon-reload
}
trap rollback ERR
install -o root -g root -m 0644 "$STAGE/$SERVICE" "$SYSTEMD/$SERVICE"
install -o root -g root -m 0644 "$STAGE/$TIMER" "$SYSTEMD/$TIMER"
systemd-analyze verify "$SYSTEMD/$SERVICE" "$SYSTEMD/$TIMER"
ln -s "releases/$SHA" "$ROOT/.next-$$"
mv -Tf "$ROOT/.next-$$" "$ROOT/current"
systemctl daemon-reload
systemctl enable --now "$TIMER"
systemctl start "$SERVICE"
if [[ ! -s "$STATE/status.json" ]]; then
  echo 'ERROR: no readiness status snapshot' >&2
  false
fi
python3 - "$STATE/status.json" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))
assert v['readiness']=='OFF', 'new service must start in OFF state'
assert v['may_transmit'] is False and v['apply_allowed'] is False
assert v['suggested_start_watts'] is None
for key in ('c4_inventory', 'prospective_inventory', 'regional_c4_asof_inventory'):
    assert v[key]['available'] is True, f'missing/unreadable live database: {key}'
print('PASS C5.4 readiness timer installed in non-actuating OFF mode with 3 verified sources')
PY
systemctl is-active --quiet "$TIMER"
trap - ERR
printf 'RELEASE_SHA=%s\nBACKUP=%s\n' "$SHA" "$BACKUP"
