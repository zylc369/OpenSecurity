#!/usr/bin/env bash
# relayd VPS 部署薄壳——全部部署逻辑在 tools/relay-deploy/deploy.py。
# 用法: ./deploy-relayd.sh <VPS_IP> [SSH_USER=root] [--dry-run 预检]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# 定位 Python >=3.11（与 start-remote-node.sh 同款守卫——统一约束，避免两套规则）
py_ok() { "${1}" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" 2>/dev/null; }
PY="$(command -v python3 || true)"
if [ -z "${PY}" ] || ! py_ok "${PY}"; then
  PY=""
  for c in python3.14 python3.13 python3.12 python3.11; do
    if command -v "${c}" >/dev/null 2>&1 && py_ok "$(command -v "${c}")"; then
      PY="$(command -v "${c}")"; break
    fi
  done
fi
if [ -z "${PY}" ]; then
  echo "[ERROR] 未找到 Python >= 3.11（PATH 的 python3 过老或缺失）。请安装后重试:" >&2
  echo "  https://www.python.org/downloads/ （或 conda 系任意 3.11+）" >&2
  exit 1
fi
exec "${PY}" "${HERE}/.opencode/control/backend/tools/relay-deploy/deploy.py" "$@"
