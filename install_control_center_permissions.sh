#!/bin/bash
# Optional, explicit installation only. Does not restart services or change radios.
set -euo pipefail
if [[ $EUID != 0 || $# != 1 || ! $1 =~ ^[a-z_][a-z0-9_-]*\$?$ ]]; then
    echo 'Usage: sudo bash install_control_center_permissions.sh DAEMON_USER' >&2
    exit 2
fi
id "$1" >/dev/null
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
target=/usr/lib/whisplay/control-action
rule=/etc/sudoers.d/whisplay-control-center
if [[ -e $target || -e $rule || -L $target || -L $rule ]]; then
    echo 'Existing helper/rule found. Preserve and review it before replacement.' >&2
    exit 1
fi
temporary=$(mktemp)
trap 'rm -f -- "$temporary"' EXIT
printf '%s ALL=(root) NOPASSWD: /usr/lib/whisplay/control-action\n' "$1" > "$temporary"
/usr/sbin/visudo -cf "$temporary"
install -d -o root -g root -m 755 /usr/lib/whisplay
install -o root -g root -m 755 "$source_dir/daemon/control_action.py" "$target"
if ! install -o root -g root -m 440 "$temporary" "$rule"; then
    rm -f -- "$target"
    exit 1
fi
echo 'Fixed control helper installed. No services restarted; no network changes.'
