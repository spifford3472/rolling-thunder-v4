#!/usr/bin/env bash
# Owner-reviewed root-only C4 service installer; never enables provider sampling.
set -euo pipefail
umask 077
if [[ $# != 2 ]]; then
    echo 'USAGE: install-forge-voacap-baseline.sh EXACT_40_CHAR_SHA ROOT_OWNED_STAGE' >&2
    exit 2
fi
SHA=$1
STAGE=$2
ROOT=/opt/rolling-thunder-forge-voacap-baseline
CONFIG=/etc/rolling-thunder-forge-voacap-baseline/config.json
SERVICE=rolling-thunder-forge-voacap-baseline.service
TIMER=rolling-thunder-forge-voacap-baseline.timer
[[ $EUID -eq 0 && $SHA =~ ^[0-9a-f]{40}$ ]] || exit 3
[[ $STAGE == /var/lib/rolling-thunder-forge-deploy/staging/voacap-baseline/* && -d $STAGE && ! -L $STAGE ]] || exit 3
[[ $(stat -c %u "$STAGE") == 0 && $(stat -c %a "$STAGE") == 700 ]] || exit 3
[[ $(cat "$STAGE/COMMIT_SHA") == "$SHA" && $(cat "$STAGE/COMPONENT") == 'forge-voacap-baseline' ]] || exit 3
[[ -f "$CONFIG" && $(stat -c %u "$CONFIG") == 0 ]] || { echo 'ERROR: missing root-owned C4 config' >&2; exit 4; }
python3 - "$CONFIG" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))
assert v.get('process_enabled') is False
assert v.get('scheduler_enabled') is False
assert v.get('provider_enabled') is False
assert v.get('database_path') == '/var/lib/rolling-thunder-forge-propagation/c4-baseline.sqlite3'
print('PASS: all three provider/scheduler gates OFF')
PY
(cd "$STAGE/wheelhouse" && sha256sum -c SHA256SUMS >/dev/null)
VERSION=$(cat "$STAGE/PROJECT_VERSION")
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 4
[[ ! -e "$ROOT/releases/$SHA" && ! -L "$ROOT/current" ]] || { echo 'ERROR: current C4 release exists; update flow requires separate review' >&2; exit 4; }
install -d -o root -g root -m 0755 "$ROOT" "$ROOT/releases"
RELEASE="$ROOT/releases/$SHA"
install -d -o root -g root -m 0755 "$RELEASE"
cleanup() { rm -rf "$RELEASE"; }
trap cleanup ERR
python3 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/pip" install --no-index --find-links "$STAGE/wheelhouse" "rolling-thunder==$VERSION"
printf '%s\n' "$SHA" > "$RELEASE/COMMIT_SHA"
chown -R root:root "$RELEASE"
find "$RELEASE" -type d -exec chmod 0755 {} +
find "$RELEASE" -type f -exec chmod a+r,go-w {} +
"$RELEASE/.venv/bin/rolling-thunder-forge-voacap-baseline" --config "$CONFIG" --check-config
trap - ERR
BACKUP=$(mktemp -d /var/backups/rolling-thunder/voacap-baseline-before-XXXXXX)
chmod 0700 "$BACKUP"
for u in "$SERVICE" "$TIMER"; do
  if [[ -f "/etc/systemd/system/$u" ]]; then cp -p "/etc/systemd/system/$u" "$BACKUP/$u"; fi
done
rollback() {
  systemctl disable --now "$TIMER" >/dev/null 2>&1 || true
  rm -f "$ROOT/current"
  for u in "$SERVICE" "$TIMER"; do
    if [[ -f "$BACKUP/$u" ]]; then cp -p "$BACKUP/$u" "/etc/systemd/system/$u"; else rm -f "/etc/systemd/system/$u"; fi
  done
  systemctl daemon-reload
}
trap rollback ERR
install -o root -g root -m 0644 "$STAGE/$SERVICE" "/etc/systemd/system/$SERVICE"
install -o root -g root -m 0644 "$STAGE/$TIMER" "/etc/systemd/system/$TIMER"
ln -s "releases/$SHA" "$ROOT/current"
systemctl daemon-reload
systemctl start "$SERVICE"
systemctl show "$SERVICE" -p Result -p ExecMainStatus
[[ $(systemctl show -P Result "$SERVICE") == success ]]
systemctl enable --now "$TIMER"
systemctl is-active --quiet "$TIMER"
trap - ERR
printf 'PASS: disabled C4 sampler service installed at %s\nBACKUP=%s\n' "$SHA" "$BACKUP"
