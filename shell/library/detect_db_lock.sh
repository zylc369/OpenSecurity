#!/usr/bin/env bash
set -euo pipefail

_derive_id0_path() {
    local input_path="$1"
    if [[ "$input_path" == *.i64 ]]; then
        echo "${input_path%.i64}.id0"
    elif [[ "$input_path" == *.idb ]]; then
        echo "${input_path%.idb}.id0"
    else
        echo "${input_path}.id0"
    fi
}

_is_file_locked() {
    local target_file="$1"

    # 主策略: lsof 检查是否有进程打开该文件
    if command -v lsof &>/dev/null; then
        if lsof "$target_file" 2>/dev/null | grep -q .; then
            return 0
        fi
    fi

    # 备用策略: python3 fcntl 非阻塞锁测试
    if command -v python3 &>/dev/null; then
        if python3 -c "
import fcntl, sys
try:
    f = open(sys.argv[1], 'r')
except FileNotFoundError:
    sys.exit(1)
try:
    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fcntl.flock(f, fcntl.LOCK_UN)
    f.close()
    sys.exit(1)
except (IOError, OSError):
    f.close()
    sys.exit(0)
" "$target_file" 2>/dev/null; then
            return 0
        fi
    fi

    return 1
}

check_db_lock() {
    local input_path="$1"
    local id0_path
    id0_path=$(_derive_id0_path "$input_path")

    # .id0 不存在 → 数据库从未被打开，不锁定
    if [[ ! -f "$id0_path" ]]; then
        return 0
    fi

    # 检查文件是否被锁定
    if _is_file_locked "$id0_path"; then
        echo "[!] 警告: IDA 数据库可能已被占用: $id0_path" >&2
        echo "[!] 如果 IDA 非正常退出，可能残留了锁文件，请确认后再试" >&2
        echo "[!] 提示: 可以尝试删除以下文件后重试: $id0_path" >&2
        return 1
    fi

    return 0
}
