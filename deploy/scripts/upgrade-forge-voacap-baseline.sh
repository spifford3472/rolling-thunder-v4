#!/usr/bin/env bash
# Explicit administrator-only C6 update. No provider enabling or radio operations.
set -euo pipefail
umask 077
if [[ $# != 2 ]]; then
 echo 'USAGE: upgrade-forge-voacap-baseline.sh EXACT_40_CHAR_SHA ROOT_OWNED_STAGE' >&2
 exit 2
fi
SHA=$1
STAGE=$2
ROOT=/opt/rolling-thunder-forge-voacap-baseline
CONFIG=/etc/rolling-thunder-forge-voacap-baseline/config.json
SERVICE=rolling-thunder-forge-voacap-baseline.service
TIMER=rolling-thunder-forge-voacap-baseline.timer
[[ $EUID == 0 && $SHA =~ ^[0-9a-f]{40}$ ]] || exit 3
[[ $STAGE == /var/lib/rolling-thunder-forge-deploy/staging/voacap-baseline/* && -d $STAGE && ! -L $STAGE ]] || exit 3
[[ $(stat -c %u "$STAGE") == 0 && $(stat -c %a "$STAGE") == 700 ]] || exit 3
[[ $(cat "$STAGE/COMMIT_SHA") == "$SHA" && $(cat "$STAGE/COMPONENT") == 'forge-voacap-baseline' ]] || exit 3
[[ -L "$ROOT/current" && -d "$ROOT/current" && ! -e "$ROOT/releases/$SHA" ]] || {
 echo 'ERROR: expected an existing release and a fresh target SHA' >&2; exit 4;
}
[[ -f "$CONFIG" && $(stat -c %u "$CONFIG") == 0 ]] || exit 4
python3 - "$CONFIG" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))
assert all(v.get(g) is False for g in ('process_enabled','scheduler_enabled','provider_enabled'))
assert v.get('database_path') == '/var/lib/rolling-thunder-forge-propagation/c4-baseline.sqlite3'
assert v.get('ssn_snapshot_path'), 'new release requires explicit NOAA snapshot path'
print('PASS: three activation gates OFF and source configuration present')
PY
(cd "$STAGE/wheelhouse" && sha256sum -c SHA256SUMS >/dev/null)
VERSION=$(cat "$STAGE/PROJECT_VERSION")
[[ $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || exit 4
OLD=$(readlink "$ROOT/current")
[[ $OLD == releases/* && -d "$ROOT/$OLD" ]] || { echo 'ERROR: unsafe old release symlink'; exit 4; }
[[ $(systemctl is-active "$TIMER") == active ]] || { echo 'ERROR: existing timer not active'; exit 4; }
BACKUP=$(mktemp -d /var/backups/rolling-thunder/voacap-baseline-upgrade-XXXXXXXX)
chmod 0700 "$BACKUP"
cp -p "$CONFIG" "$BACKUP/config.json"
for u in "$SERVICE" "$TIMER"; do
 cp -p "/etc/systemd/system/$u" "$BACKUP/$u"
done
printf '%s\n' "$OLD" > "$BACKUP/previous-release"
RELEASE="$ROOT/releases/$SHA"
install -d -o root -g root -m 0755 "$RELEASE"
SWITCHED=false
rollback() {
 local result=$?
 trap - ERR
 if [[ $SWITCHED == true ]]; then
   ln -s "$OLD" "$ROOT/.current-rollback-$$"
   mv -Tf "$ROOT/.current-rollback-$$" "$ROOT/current"
   cp -p "$BACKUP/config.json" "$CONFIG"
   for u in "$SERVICE" "$TIMER"; do cp -p "$BACKUP/$u" "/etc/systemd/system/$u"; done
   systemctl daemon-reload
 fi
 systemctl enable --now "$TIMER" >/dev/null 2>&1 || true
 echo "UPGRADE_ROLLBACK_BACKUP=$BACKUP" >&2
 exit "$result"
}
trap rollback ERR
python3 -m venv "$RELEASE/.venv"
"$RELEASE/.venv/bin/pip" install --no-index --find-links "$STAGE/wheelhouse" "rolling-thunder==$VERSION"
printf '%s\n' "$SHA" > "$RELEASE/COMMIT_SHA"
chown -R root:root "$RELEASE"
find "$RELEASE" -type d -exec chmod 0755 {} +
find "$RELEASE" -type f -exec chmod a+r,go-w {} +
"$RELEASE/.venv/bin/rolling-thunder-forge-voacap-baseline" --config "$CONFIG" --check-config
# The previous release remains installed and the timer stays gated OFF.
systemctl stop "$TIMER"
install -o root -g root -m 0644 "$STAGE/$SERVICE" "/etc/systemd/system/$SERVICE"
install -o root -g root -m 0644 "$STAGE/$TIMER" "/etc/systemd/system/$TIMER"
ln -s "releases/$SHA" "$ROOT/.current-upgrade-$$"
mv -Tf "$ROOT/.current-upgrade-$$" "$ROOT/current"
SWITCHED=true
systemctl daemon-reload
systemctl start "$SERVICE"
systemctl enable --now "$TIMER"
[[ $(systemctl show -P Result "$SERVICE") == success ]]
systemctl is-active --quiet "$TIMER"
python3 - "$CONFIG" <<'PY'
import json,sys
v=json.load(open(sys.argv[1]))
assert all(v.get(g) is False for g in ('process_enabled','scheduler_enabled','provider_enabled'))
PY
trap - ERR
echo "UPGRADE_PASS_SHA=$SHA"
echo "PREVIOUS_RELEASE=$OLD"
echo "ROLLBACK_BACKUP=$BACKUP"
