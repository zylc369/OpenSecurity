#!/usr/bin/env bash
# summary: 启动浏览器自动化服务（detach 模式）
#
# description:
#   用 detach 模式启动 web_render_server.py 常驻服务。
#   服务监听 localhost:8888，提供浏览器自动化 API。
#   PID 写入 $TASK_DIR/browser_server.pid，用完 kill 清理。
#
# usage:
#   bash $SHARED_DIR/scripts/start_browser_server.sh
#   # → 输出: http://localhost:8888

set -euo pipefail

PORT="${BROWSER_SERVER_PORT:-8888}"
HOST="127.0.0.1"
SERVICE_URL="http://${HOST}:${PORT}"
PID_FILE="${TASK_DIR:-/tmp}/browser_server.pid"
LOG_FILE="${TASK_DIR:-/tmp}/browser_server.log"

# 检测服务是否已在运行
HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/health" 2>/dev/null || echo "000")
if [ "$HEALTH" = "200" ]; then
    echo "$SERVICE_URL"
    exit 0
fi

# 检测 $PYTHON_CMD（由 Plugin 注入）
if [ -z "${PYTHON_CMD:-}" ]; then
    echo "ERROR: \$PYTHON_CMD 未设置。请在 opencode 环境中运行。" >&2
    exit 1
fi

# 检测脚本路径
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SERVER_SCRIPT="${SCRIPT_DIR}/web_render_server.py"
if [ ! -f "$SERVER_SCRIPT" ]; then
    echo "ERROR: web_render_server.py 未找到: $SERVER_SCRIPT" >&2
    exit 1
fi

# 用 detach 模式启动（setsid + timeout + 日志重定向 + PID 写入）
setsid timeout -k 5 3600 "$PYTHON_CMD" "$SERVER_SCRIPT" --port "$PORT" --host "$HOST" > "$LOG_FILE" 2>&1 &
echo $! > "$PID_FILE"

# 等待服务就绪（轮询 /health，最多 15 秒）
for i in $(seq 1 30); do
    HEALTH=$(curl -s -o /dev/null -w "%{http_code}" "${SERVICE_URL}/health" 2>/dev/null || echo "000")
    if [ "$HEALTH" = "200" ]; then
        echo "$SERVICE_URL"
        exit 0
    fi
    sleep 0.5
done

# 服务未就绪
echo "ERROR: 服务未在 15 秒内就绪。检查日志: $LOG_FILE" >&2
cat "$LOG_FILE" >&2 2>/dev/null || true
exit 1
