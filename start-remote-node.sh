#!/usr/bin/env bash
# 远程节点薄壳——全部引导逻辑（venv/依赖/配置/模型/启动）在 services/remote_node.py。
# 用法: ./start-remote-node.sh [--check 预检 | --relay-host ... 等参数注入 | --skip-tts ...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"

# 拉最新代码（节点机日常=一键"最新+运行"; 失败不阻断——离线/冲突/脏工作区
# 时以本地代码继续启动，旧代码好过没有节点）:
if command -v git >/dev/null 2>&1 \
   && git -C "${HERE}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  if git -C "${HERE}" pull --ff-only >/dev/null 2>&1; then
    echo "[+] git pull: $(git -C "${HERE}" log -1 --oneline)"
  else
    echo "[!] git pull 失败（离线/分叉/脏工作区）——以本地代码继续"
  fi
fi

# 定位 Python ≥3.11（remote_node 顶层依赖 typing.Never 等 3.11+ 特性）:
# PATH 的 python3 优先; 过老/缺失则依次尝试常见新版本名; 仍无 → 明确报错
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
exec "${PY}" "${HERE}/.opencode/control/backend/services/remote_node.py" "$@"
