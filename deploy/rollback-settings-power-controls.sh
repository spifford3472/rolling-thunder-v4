#!/usr/bin/env bash
# Restore the exact sudoers and desktop-autostart state saved by the installer.
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "Run this rollback with sudo." >&2
    exit 1
fi
if [[ "$#" -ne 1 ]]; then
    echo "Usage: $0 /var/backups/rolling-thunder/settings-power-controls.*" >&2
    exit 2
fi

BACKUP_ROOT="/var/backups/rolling-thunder"
BACKUP_DIR="$(realpath -e -- "$1")"
BACKUP_ROOT_REAL="$(realpath -e -- "$BACKUP_ROOT")"
case "$BACKUP_DIR" in
    "$BACKUP_ROOT_REAL"/settings-power-controls.*) ;;
    *)
        echo "Backup directory is outside the approved Rolling Thunder backup path." >&2
        exit 2
        ;;
esac
if [[ "$(stat -c '%u:%a' "$BACKUP_DIR")" != "0:700" ]]; then
    echo "Backup directory must be root-owned with mode 0700." >&2
    exit 2
fi

SUDOERS_TARGET="/etc/sudoers.d/rolling-thunder-settings-power"
AUTOSTART_DIR="/home/geoff/.config/autostart"
AUTOSTART_TARGET="$AUTOSTART_DIR/polkit-mate-authentication-agent-1.desktop"

restore_sudoers() {
    local state
    state="$(cat "$BACKUP_DIR/sudoers.state")"
    if [[ "$state" == absent ]]; then
        rm -f -- "$SUDOERS_TARGET"
    elif [[ "$state" == present ]]; then
        local temporary
        temporary="$(mktemp /etc/sudoers.d/.rolling-thunder-settings-power.restore.XXXXXX)"
        install -o root -g root -m 0440 "$BACKUP_DIR/sudoers" "$temporary"
        visudo -cf "$temporary"
        mv -f -- "$temporary" "$SUDOERS_TARGET"
    else
        echo "Unknown sudoers backup state." >&2
        return 2
    fi
}

restore_autostart() {
    local state
    state="$(cat "$BACKUP_DIR/autostart.state")"
    runuser -u geoff -- install -d -m 0755 "$AUTOSTART_DIR"
    if [[ "$state" == absent ]]; then
        runuser -u geoff -- rm -f -- "$AUTOSTART_TARGET"
    elif [[ "$state" == present ]]; then
        cat "$BACKUP_DIR/autostart" | runuser -u geoff -- tee "$AUTOSTART_TARGET" >/dev/null
        chown geoff:geoff "$AUTOSTART_TARGET"
        chmod 0644 "$AUTOSTART_TARGET"
    else
        echo "Unknown autostart backup state." >&2
        return 2
    fi
}

restore_sudoers
restore_autostart
visudo -c
printf 'Settings power controls rolled back from %s\n' "$BACKUP_DIR"
