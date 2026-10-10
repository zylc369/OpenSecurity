#!/usr/bin/env bash
# 远程节点（Mac Mini 等）一键启动 OpenSecurity 控制台。
# 薄壳: 仅定位仓库与 Python; 依赖安装（场景化）与进程启动全部委托跨平台 Python。
# 用法: bash start-remote-node.sh [--install]   (--install = 先装控制台运行集依赖再启动)
# 注: 所有 $VAR 一律 ${VAR} 边界明确——避免变量紧邻多字节字符时 bash 在
#     非 UTF-8 locale 下把后续字节误吞进变量名（unbound variable 报错根因）。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${HERE}/.opencode/control/backend"

# 定位 Python: 优先项目 venv（install 子命令自举创建）; 回退系统 python3
PY="${BACKEND}/.venv/bin/python"
[ -x "${PY}" ] || PY="$(command -v python3)"

if [[ "${1:-}" == "--install" ]]; then
  echo "==> 安装控制台运行依赖 tags=console_runtime"
  (cd "${BACKEND}" && PYTHONPATH="${BACKEND}" "${PY}" services/detect_py_deps.py install --tags console_runtime)
fi

echo "==> 启动控制台 backend=${BACKEND}"
exec "${PY}" "${BACKEND}/server.py"
