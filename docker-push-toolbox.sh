#!/usr/bin/env bash
# OpenSecurity 工具箱镜像推送 (macOS / Linux 入口)
# 用法: ./docker-push-toolbox.sh --ver 1.0（版本号必填，1.0 与 v1.0 等价）
# 逻辑全在 control/backend/services/docker_push_toolbox.py（CLI 实时透传 docker 输出）。

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 找 python3
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

exec "$PYTHON" "${SCRIPT_DIR}/.opencode/control/backend/services/docker_push_toolbox.py" "$@"
