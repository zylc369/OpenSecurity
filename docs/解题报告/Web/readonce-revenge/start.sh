#!/usr/bin/env bash
# 启动本地攻击者服务器（attacker.js）
# 依赖：Node.js 18+；机器人（容器内）会经 host.docker.internal:9975 访问它
# 用法：./start.sh   （前台运行，Ctrl+C 停止）
set -euo pipefail
cd "$(dirname "$0")"

command -v node >/dev/null 2>&1 || { echo "[!] 未找到 node，请先安装 Node.js（18+）"; exit 1; }

echo "[*] 启动 attacker.js（监听 9975）..."
exec node attacker.js
