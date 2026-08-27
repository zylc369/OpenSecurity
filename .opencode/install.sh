#!/usr/bin/env bash
# OpenSecurity 一键安装 (macOS / Linux)
# 用法: bash .opencode/install.sh
# 逻辑在 detect_py_deps.py install（python 依赖）+ detect_tools.py install（外部工具）。
# 两层都是必需层: python 依赖失败立即中断; 工具层单项失败不中断其余安装，
# 但只要有失败，本脚本以非零退出码结束（重装命令见输出末尾汇总）。

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

# 本脚本不接收参数（安装内容固定：全部必需依赖）
if [[ $# -gt 0 ]]; then
    echo "错误：install.sh 不接收参数（收到: $*）。" >&2
    exit 1
fi

# 1. Python 依赖（必需层: 失败即中断）
"$PYTHON" "${SCRIPT_DIR}/control/backend/services/detect_py_deps.py" install

# 2. 外部工具（必需层: 单项失败不中断其余，但整体失败 → 非零退出码）
echo "[*] === 安装外部工具（单项失败不中断，失败汇总在末尾） ==="
"$PYTHON" "${SCRIPT_DIR}/control/backend/services/detect_tools.py" install
