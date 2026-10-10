#!/usr/bin/env bash
# 远程节点（Mac Mini 等）一键启动 OpenSecurity 控制台。
# 薄壳: 仅定位仓库与 Python; 依赖检测/安装与进程启动全部委托跨平台 Python。
# 用法:
#   bash start-remote-node.sh             # 启动（依赖缺失时自动安装——首次可直接跑）
#   bash start-remote-node.sh --install   # 显式安装控制台运行集依赖后启动
# 注: 所有 $VAR 一律 ${VAR} 边界明确——避免变量紧邻多字节字符时 bash 在
#     非 UTF-8 locale 下把后续字节误吞进变量名。
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BACKEND="${HERE}/.opencode/control/backend"

# 定位 Python: 优先项目 venv（install 自举创建）; 回退系统 python3
resolve_py() {
  if [ -x "${BACKEND}/.venv/bin/python" ]; then
    echo "${BACKEND}/.venv/bin/python"
  else
    command -v python3
  fi
}
PY="$(resolve_py)"

do_install() {
  echo "==> 安装控制台运行依赖 tags=console_runtime"
  (cd "${BACKEND}" && PYTHONPATH="${BACKEND}" "${PY}" services/detect_py_deps.py install --tags console_runtime)
  PY="$(resolve_py)"  # install 可能自举了 venv——重解析解释器路径
}

if [[ "${1:-}" == "--install" ]]; then
  do_install
elif ! "${PY}" -c "import fastapi" 2>/dev/null; then
  echo "==> 检测到控制台依赖缺失（fastapi 不可导入）——自动安装"
  do_install
fi

echo "==> 启动控制台 backend=${BACKEND} python=${PY}"
exec "${PY}" "${BACKEND}/server.py"
