#!/bin/bash
# Explicit, separately approved installation only. No service or radio changes.
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /usr/bin/python3 -I "$source_dir/daemon/install_control_permissions.py" "$@"
