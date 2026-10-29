#!/usr/bin/env bash
# OpenSecurity 工具箱镜像构建 (macOS / Linux 入口)
# 用法: ./docker-build-toolbox.sh [--arch arm64|amd64|both] [--no-smoke]
# 逻辑全在 control/backend/services/docker_build_toolbox.py（CLI 实时透传 docker build 输出）。

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        PYTHON="$cmd"
        break
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "错误：未找到 Python。请安装 Python 3.10+。" >&2
    exit 1
fi

exec "$PYTHON" "${SCRIPT_DIR}/.opencode/control/backend/services/docker_build_toolbox.py" "$@"
