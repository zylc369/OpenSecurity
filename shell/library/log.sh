#!/usr/bin/env bash
# shell/library/log.sh — 通用控制台日志打印函数
#
# 提供 log_debug / log_info / log_warn / log_error 四个级别，
# 时间戳精确到毫秒（本地时区）。
#
# 使用方式（source 后直接调用）：
#   source "shell/library/log.sh"
#   LOG_LEVEL=DEBUG log_info "开始执行"
#   log_warn "磁盘空间不足"
#   log_error "文件不存在: $path"
#
# 环境变量：
#   LOG_LEVEL — 日志级别阈值，支持 DEBUG / INFO / WARN / ERROR（默认 INFO）

set -euo pipefail

_LOG_LEVEL_DEBUG=0
_LOG_LEVEL_INFO=1
_LOG_LEVEL_WARN=2
_LOG_LEVEL_ERROR=3

LOG_LEVEL="${LOG_LEVEL:-INFO}"

_log_level_num() {
    case "${1^^}" in
        DEBUG) echo $_LOG_LEVEL_DEBUG ;;
        INFO)  echo $_LOG_LEVEL_INFO ;;
        WARN)  echo $_LOG_LEVEL_WARN ;;
        ERROR) echo $_LOG_LEVEL_ERROR ;;
        *)     echo $_LOG_LEVEL_INFO ;;
    esac
}

_timestamp_ms() {
    python3 -c "
from datetime import datetime
print(datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3])
"
}

_log() {
    local level="$1"
    shift
    local msg="$*"
    local msg_num
    msg_num=$(_log_level_num "$level")
    local threshold_num
    threshold_num=$(_log_level_num "$LOG_LEVEL")
    if (( msg_num >= threshold_num )); then
        local ts
        ts=$(_timestamp_ms)
        printf "[%-5s] [%s] %s\n" "$level" "$ts" "$msg" >&2
    fi
}

log_debug() { _log "DEBUG" "$@"; }
log_info()  { _log "INFO"  "$@"; }
log_warn()  { _log "WARN"  "$@"; }
log_error() { _log "ERROR" "$@"; }
