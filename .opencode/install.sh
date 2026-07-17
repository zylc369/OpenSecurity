#!/usr/bin/env bash
# OpenSecurity 一键安装脚本 (macOS / Linux)
#
# 用法:
#   bash .opencode/install.sh
#
# 功能:
#   1. 检测/安装 conda (Miniforge)
#   2. 创建 conda 虚拟环境
#   3. 安装全部 Python 依赖包（所有 agent 共用）
#   4. 安装 Playwright Chromium 浏览器
#   5. 检测 Docker + 启动 Neo4j 容器
#   6. 运行 detect_env.py 验证

set -euo pipefail

# ============================================================
# 配置
# ============================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${HOME}/bw-security-analysis"
VENV_DIR="${DATA_DIR}/.venv"

# ============================================================
# 颜色输出
# ============================================================
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    RED='\033[0;31m'
    BLUE='\033[0;34m'
    NC='\033[0m'
else
    GREEN='' YELLOW='' RED='' BLUE='' NC=''
fi

info()  { echo -e "${GREEN}[OK]${NC}  $1"; }
warn()  { echo -e "${YELLOW}[!]${NC}  $1"; }
fail()  { echo -e "${RED}[X]${NC}  $1"; }
step()  { echo -e "\n${BLUE}=== Step ${1}/4: ${2} ===${NC}"; }

echo ""
echo "============================================================"
echo "  OpenSecurity 一键安装 (macOS / Linux)"
echo "============================================================"

# ============================================================
# Step 1: 检测 conda
# ============================================================
step 1 "检测 conda (Miniforge)"

CONDA=""
if command -v conda &>/dev/null; then
    CONDA="conda"
elif [[ -f "${HOME}/miniforge3/bin/conda" ]]; then
    CONDA="${HOME}/miniforge3/bin/conda"
elif [[ -f "${HOME}/miniconda3/bin/conda" ]]; then
    CONDA="${HOME}/miniconda3/bin/conda"
elif [[ -f "/opt/homebrew/Caskroom/miniforge/base/condabin/conda" ]]; then
    CONDA="/opt/homebrew/Caskroom/miniforge/base/condabin/conda"
fi

if [[ -z "$CONDA" ]]; then
    fail "conda 未安装"
    echo ""
    echo "请先安装 Miniforge："
    local_arch="$(uname -m)"
    if [[ "$(uname -s)" == "Darwin" ]]; then
        echo "  curl -L -o /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-MacOSX-${local_arch}.sh"
        echo "  bash /tmp/miniforge.sh -b -p ${HOME}/miniforge3"
    else
        echo "  curl -L -o /tmp/miniforge.sh https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-${local_arch}.sh"
        echo "  bash /tmp/miniforge.sh -b -p ${HOME}/miniforge3"
    fi
    echo ""
    echo "安装后重新打开终端，再次运行此脚本。"
    exit 1
fi
info "conda: $CONDA"

# ============================================================
# Step 2: 创建 conda 虚拟环境
# ============================================================
step 2 "创建 conda 虚拟环境"

if [[ -f "${VENV_DIR}/bin/python" ]]; then
    info "虚拟环境已存在: ${VENV_DIR}"
else
    echo "  创建中（python=3.13）..."
    "$CONDA" create -p "$VENV_DIR" python=3.13 -y
    info "虚拟环境已创建: ${VENV_DIR}"
fi

PYTHON="${VENV_DIR}/bin/python"

# ============================================================
# Step 3: 安装全部依赖（Python 包 + Playwright + 外部工具提示 + events MCP）
# ============================================================
step 3 "安装全部依赖（可能需要 5-15 分钟）"

echo "  调用 detect_env.py install..."
"$PYTHON" "${SCRIPT_DIR}/binary-analysis/scripts/detect_env.py" install

# ============================================================
# Step 4: 验证安装结果
# ============================================================
step 4 "验证安装结果"

echo "  运行 detect_env.py check-preinstall all..."
echo ""

# detect_env.py 失败时不中断脚本（它 exit 1 表示有缺失，我们要看输出）
set +e
"$PYTHON" "${SCRIPT_DIR}/binary-analysis/scripts/detect_env.py" check-preinstall all
DETECT_EXIT=$?
set -e

echo ""
echo "============================================================"
if [[ $DETECT_EXIT -eq 0 ]]; then
    info "全部检测通过！可以开始使用了。"
else
    warn "部分依赖未就绪（见上方输出）。"
    echo ""
    echo "  常见需要手动配置的项："
    echo "    - ZHIPU_API_KEY: 在 .opencode/.ai_env 中设置（用于事件检索）"
    echo "    - 外部工具: 按上方提示安装（brew install ...）"
fi
echo "============================================================"
echo ""
