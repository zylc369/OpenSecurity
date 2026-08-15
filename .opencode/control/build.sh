#!/usr/bin/env bash
# OpenSecurity 控制台前端构建脚本。
# 用法：bash .opencode/control/build.sh
#
# 检测包管理器（bun 优先，npm 兜底），自动安装依赖并构建。
# 构建产物在 frontend/dist/，由控制台后端 starlette.staticfiles 服务。

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/frontend"

# 检测包管理器
if command -v bun &>/dev/null; then
  PKG_MGR=bun
elif command -v npm &>/dev/null; then
  PKG_MGR=npm
else
  echo "[ERROR] 未找到 bun 或 npm。请安装 Node.js 或 bun。" >&2
  exit 1
fi

echo "[*] 安装依赖（$PKG_MGR install）..."
$PKG_MGR install

echo "[*] 构建前端（$PKG_MGR run build）..."
$PKG_MGR run build

echo "[+] dist/ 已生成"
echo "[*] 控制台启动时（CONTROL_FRONTEND_DEV=0 或未设置）会自动挂载 dist/"
