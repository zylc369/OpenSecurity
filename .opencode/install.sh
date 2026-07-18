#!/usr/bin/env bash
# OpenSecurity 一键安装 (macOS / Linux)
# 用法: bash .opencode/install.sh
# 逻辑全在 detect_env.py install（跨平台），此脚本只负责找到 Python 并启动它。

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
    echo "错误：未找到 Python。请安装 Miniforge 或 Python 3.10+。" >&2
    exit 1
fi

exec "$PYTHON" "${SCRIPT_DIR}/binary-analysis/scripts/detect_env.py" install
