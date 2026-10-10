#!/usr/bin/env bash
# 远程节点薄壳——全部引导逻辑（venv/依赖/配置/模型/启动）在 services/remote_node.py。
# 用法: ./start-remote-node.sh [--check 预检 | --relay-host ... 等参数注入 | --skip-tts ...]
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
exec python3 "${HERE}/.opencode/control/backend/services/remote_node.py" "$@"
