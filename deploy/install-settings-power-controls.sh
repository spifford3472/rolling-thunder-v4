#!/usr/bin/env bash
# Install the exact Settings power allowlist and suppress the duplicate MATE agent.
set -euo pipefail

if [[ "$EUID" -ne 0 ]]; then
    echo "Run this installer with sudo." >&2
    exit 1
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
SUDOERS_SOURCE="$SCRIPT_DIR/rolling-thunder-settings-power.sudoers"
AUTOSTART_SOURCE="$SCRIPT_DIR/polkit-mate-authentication-agent-1.desktop"
SUDOERS_TARGET="/etc/sudoers.d/rolling-thunder-settings-power"
AUTOSTART_DIR="/home/geoff/.config/autostart"
AUTOSTART_TARGET="$AUTOSTART_DIR/polkit-mate-authentication-agent-1.desktop"
BACKUP_ROOT="/var/backups/rolling-thunder"
BACKUP_DIR=""

if [[ ! -r "$SUDOERS_SOURCE" || ! -r "$AUTOSTART_SOURCE" ]]; then
    echo "Required Settings power configuration files are missing." >&2
    exit 2
fi

if ! getent passwd geoff >/dev/null; then
    echo "Expected operator account geoff was not found." >&2
    exit 2
fi
if [[ "$(getent passwd geoff | cut -d: -f6)" != "/home/geoff" ]]; then
    echo "The geoff account home directory is not /home/geoff; refusing to continue." >&2
    exit 2
fi
if [[ -L "$SUDOERS_TARGET" || -L "$AUTOSTART_TARGET" ]]; then
    echo "Refusing to replace a symlink at a protected configuration path." >&2
    exit 2
fi

command -v visudo >/dev/null
command -v runuser >/dev/null
visudo -cf "$SUDOERS_SOURCE"

install -d -o root -g root -m 0700 "$BACKUP_ROOT"
BACKUP_DIR="$(mktemp -d "$BACKUP_ROOT/settings-power-controls.XXXXXX")"
chown root:root "$BACKUP_DIR"
chmod 0700 "$BACKUP_DIR"

backup_state() {
    local source_path="$1"
    local label="$2"

    if [[ -e "$source_path" ]]; then
        cp -a -- "$source_path" "$BACKUP_DIR/$label"
        printf '%s\n' present > "$BACKUP_DIR/$label.state"
    else
        printf '%s\n' absent > "$BACKUP_DIR/$label.state"
    fi
}

backup_state "$SUDOERS_TARGET" sudoers
backup_state "$AUTOSTART_TARGET" autostart

rollback_after_failure() {
    local status="$?"
    trap - EXIT
    if [[ "$status" -ne 0 && -n "$BACKUP_DIR" ]]; then
        echo "Installation failed; restoring the prior configuration." >&2
        if ! bash "$SCRIPT_DIR/rollback-settings-power-controls.sh" "$BACKUP_DIR"; then
            echo "Automatic rollback failed; run the rollback command shown in the deployment guide." >&2
        fi
    fi
    exit "$status"
}
trap rollback_after_failure EXIT

runuser -u geoff -- install -d -m 0755 "$AUTOSTART_DIR"
AUTOSTART_TMP="$(runuser -u geoff -- mktemp "$AUTOSTART_DIR/.polkit-mate-authentication-agent-1.desktop.XXXXXX")"
runuser -u geoff -- install -m 0644 "$AUTOSTART_SOURCE" "$AUTOSTART_TMP"
runuser -u geoff -- mv -f -- "$AUTOSTART_TMP" "$AUTOSTART_TARGET"

SUDOERS_TMP="$(mktemp /etc/sudoers.d/.rolling-thunder-settings-power.XXXXXX)"
install -o root -g root -m 0440 "$SUDOERS_SOURCE" "$SUDOERS_TMP"
visudo -cf "$SUDOERS_TMP"
mv -f -- "$SUDOERS_TMP" "$SUDOERS_TARGET"
visudo -c

trap - EXIT
printf 'Settings power controls installed.\n'
printf 'BACKUP_DIR=%s\n' "$BACKUP_DIR"
