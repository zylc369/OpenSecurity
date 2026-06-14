#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"}"

_validate_ida_dir() {
    local dir="$1"
    [[ -x "$dir/ida" && -x "$dir/idat" ]]
}

_read_config() {
    local config_file="$REPO_ROOT/.config/ida_config.json"
    if [[ -f "$config_file" ]]; then
        jq -r '.ida_path' "$config_file" 2>/dev/null || echo ""
    fi
}

_save_config() {
    local ida_path="$1"
    local config_file="$REPO_ROOT/.config/ida_config.json"
    mkdir -p "$REPO_ROOT/.config"
    echo "{\"ida_path\":\"$ida_path\"}" | jq . > "$config_file"
}

_prompt_user() {
    local ida_dir
    if read -r -p "请输入 IDA Pro 可执行文件目录路径: " ida_dir; then
        echo "$ida_dir"
    else
        echo ""
    fi
}

detect_ida_path() {
    local explicit_path="${1:-}"

    # 显式路径：直接校验，跳过 config/prompt
    if [[ -n "$explicit_path" ]]; then
        if ! _validate_ida_dir "$explicit_path"; then
            echo "[!] 错误: 在目录 '$explicit_path' 中未找到 ida 和 idat 命令" >&2
            return 1
        fi
        echo "$explicit_path"
        return 0
    fi

    # 自动检测：config → prompt
    if ! command -v jq &>/dev/null; then
        echo "[!] 错误: 需要安装 jq 命令 (brew install jq)" >&2
        return 1
    fi

    local config_path
    config_path=$(_read_config)

    if [[ -n "${config_path:-}" && "${config_path:-}" != "null" ]]; then
        if _validate_ida_dir "$config_path"; then
            echo "[*] 从配置文件读取 IDA Pro 路径: $config_path" >&2
            echo "$config_path"
            return 0
        fi
    fi

    local user_path
    user_path=$(_prompt_user)

    if [[ -z "$user_path" ]]; then
        echo "[!] 错误: 未输入 IDA Pro 路径" >&2
        return 1
    fi

    if ! _validate_ida_dir "$user_path"; then
        echo "[!] 错误: 在目录 '$user_path' 中未找到 ida 和 idat 命令" >&2
        return 1
    fi

    _save_config "$user_path"
    echo "[+] 已保存 IDA Pro 路径: $user_path" >&2
    echo "$user_path"
    return 0
}
