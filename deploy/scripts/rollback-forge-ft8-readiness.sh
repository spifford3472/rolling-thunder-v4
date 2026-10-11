#!/usr/bin/env bash
# Proposed, component-only post-deployment rollback. Root review required.
set -euo pipefail
ROOT=/opt/rolling-thunder-forge-ft8-readiness
SYSTEMD=/etc/systemd/system
SERVICE=rolling-thunder-forge-ft8-readiness.service
TIMER=rolling-thunder-forge-ft8-readiness.timer
if [[ $# != 1 ]]; then
  echo 'USAGE: rollback-forge-ft8-readiness.sh /var/backups/rolling-thunder/ft8-readiness-before-XXXXXX' >&2
  exit 2
fi
[[ $EUID -eq 0 ]] || { echo 'ERROR: root only' >&2; exit 3; }
BACKUP=$1
[[ $BACKUP == /var/backups/rolling-thunder/ft8-readiness-before-* && -d $BACKUP && ! -L $BACKUP ]] || {
  echo 'ERROR: invalid backup path' >&2
  exit 4
}
[[ $(stat -c %u "$BACKUP") == 0 && $(stat -c %a "$BACKUP") == 700 ]] || {
  echo 'ERROR: backup not root-owned/private' >&2
  exit 4
}
if [[ -f "$BACKUP/previous-current" ]]; then
  PRIOR=$(cat "$BACKUP/previous-current")
  [[ $PRIOR =~ ^releases/[0-9a-f]{40}$ ]] || {
    echo 'ERROR: invalid previous SHA symlink' >&2
    exit 5
  }
  [[ -d "$ROOT/$PRIOR" ]] || {
    echo 'ERROR: previous release unavailable' >&2
    exit 5
  }
fi
systemctl disable --now "$TIMER" >/dev/null 2>&1 || true
if [[ -n ${PRIOR:-} ]]; then
  ln -s "$PRIOR" "$ROOT/.rollback-$$"
  mv -Tf "$ROOT/.rollback-$$" "$ROOT/current"
else
  rm -f "$ROOT/current"
fi
for unit in "$SERVICE" "$TIMER"; do
  if [[ -f "$BACKUP/$unit" ]]; then
    install -o root -g root -m 0644 "$BACKUP/$unit" "$SYSTEMD/$unit"
  else
    rm -f "$SYSTEMD/$unit"
  fi
done
systemctl daemon-reload
if [[ -n ${PRIOR:-} && -f "$BACKUP/$TIMER" ]]; then
  systemctl enable --now "$TIMER"
  systemctl start "$SERVICE"
fi
printf 'ROLLED_BACK_READINESS_TO=%s\n' "${PRIOR:-disabled}"
echo 'C3 QSO worker, Pi radio and other Forge services untouched'
