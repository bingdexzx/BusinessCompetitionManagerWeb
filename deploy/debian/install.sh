#!/usr/bin/env bash
# Debian 一键部署入口（真正的逻辑在 deploy.py，Debian 自带 python3 即可运行）
#
#   sudo bash deploy/debian/install.sh
#   sudo bash deploy/debian/install.sh --domain bcm.example.com --yes
#
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/deploy.py" "$@"
