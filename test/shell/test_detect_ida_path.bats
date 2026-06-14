#!/usr/bin/env bats

load "test_helper"

setup() {
    setup_test_env
    source "$TEST_REPO_ROOT/shell/library/detect_ida_path.sh"
}

teardown() {
    teardown_test_env
}

_run_detect() {
    _stderr_file=$(mktemp)
    if [[ $# -gt 0 ]]; then
        _stdout=$(detect_ida_path <<< "$1" 2>"$_stderr_file") && _exit_status=0 || _exit_status=$?
    else
        _stdout=$(detect_ida_path 2>"$_stderr_file") && _exit_status=0 || _exit_status=$?
    fi
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"
}

@test "config missing, user provides valid path: saves JSON and returns path" {
    local mock_dir="$TEST_TMPDIR/ida_dir"
    create_mock_ida_dir "$mock_dir"

    _run_detect "$mock_dir"

    [[ "$_exit_status" -eq 0 ]]
    [[ "$_stdout" == "$mock_dir" ]]
    [[ "$_stderr" == *"已保存"* ]]

    local saved
    saved=$(jq -r '.ida_path' "$REPO_ROOT/.config/ida_config.json")
    [[ "$saved" == "$mock_dir" ]]
}

@test "config missing, user provides invalid path: error and exit 1" {
    _run_detect "/nonexistent/path/that/does/not/exist"

    [[ "$_exit_status" -eq 1 ]]
    [[ "$_stderr" == *"未找到 ida 和 idat"* ]]
}

@test "config exists with valid path: returns stored path without prompting" {
    local mock_dir="$TEST_TMPDIR/ida_dir"
    create_mock_ida_dir "$mock_dir"
    mkdir -p "$REPO_ROOT/.config"
    echo "{\"ida_path\":\"$mock_dir\"}" > "$REPO_ROOT/.config/ida_config.json"

    _run_detect

    [[ "$_exit_status" -eq 0 ]]
    [[ "$_stdout" == "$mock_dir" ]]
    [[ "$_stderr" == *"从配置文件读取"* ]]
}

@test "config exists but ida binary removed: re-prompts user" {
    local old_dir="$TEST_TMPDIR/old_ida"
    local new_dir="$TEST_TMPDIR/new_ida"
    create_mock_ida_dir "$old_dir"
    create_mock_ida_dir "$new_dir"
    mkdir -p "$REPO_ROOT/.config"
    echo "{\"ida_path\":\"$old_dir\"}" > "$REPO_ROOT/.config/ida_config.json"
    rm "$old_dir/ida" "$old_dir/idat"

    _run_detect "$new_dir"

    [[ "$_exit_status" -eq 0 ]]
    [[ "$_stdout" == "$new_dir" ]]

    local saved
    saved=$(jq -r '.ida_path' "$REPO_ROOT/.config/ida_config.json")
    [[ "$saved" == "$new_dir" ]]
}

@test "path contains spaces: handled correctly" {
    local mock_dir="$TEST_TMPDIR/IDA Professional 9.1.app"
    create_mock_ida_dir "$mock_dir"

    _run_detect "$mock_dir"

    [[ "$_exit_status" -eq 0 ]]
    [[ "$_stdout" == "$mock_dir" ]]

    local saved
    saved=$(jq -r '.ida_path' "$REPO_ROOT/.config/ida_config.json")
    [[ "$saved" == "$mock_dir" ]]
}

@test "jq not installed: error message and exit" {
    _stderr_file=$(mktemp)
    _stdout=$(PATH="/tmp/no_jq_$$" detect_ida_path 2>"$_stderr_file") && _exit_status=0 || _exit_status=$?
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"

    [[ "$_exit_status" -eq 1 ]]
    [[ "$_stderr" == *"需要安装 jq"* ]]
}

@test "user cancels input (empty string): error and exit" {
    _run_detect ""

    [[ "$_exit_status" -eq 1 ]]
    [[ "$_stderr" == *"未输入 IDA Pro 路径"* ]]
}

@test "explicit valid path: returns path without config or prompt" {
    local mock_dir="$TEST_TMPDIR/ida_explicit"
    create_mock_ida_dir "$mock_dir"

    _stderr_file=$(mktemp)
    _stdout=$(detect_ida_path "$mock_dir" 2>"$_stderr_file") && _exit_status=0 || _exit_status=$?
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"

    [[ "$_exit_status" -eq 0 ]]
    [[ "$_stdout" == "$mock_dir" ]]
    [[ -z "$_stderr" ]]
}

@test "explicit invalid path: error and exit" {
    _stderr_file=$(mktemp)
    _stdout=$(detect_ida_path "/nonexistent/explicit/path" 2>"$_stderr_file") && _exit_status=0 || _exit_status=$?
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"

    [[ "$_exit_status" -eq 1 ]]
    [[ "$_stderr" == *"未找到 ida 和 idat"* ]]
}

@test "explicit valid path: does not create config file" {
    local mock_dir="$TEST_TMPDIR/ida_explicit_nosave"
    create_mock_ida_dir "$mock_dir"
    rm -f "$REPO_ROOT/.config/ida_config.json"

    detect_ida_path "$mock_dir" >/dev/null 2>&1

    [[ ! -f "$REPO_ROOT/.config/ida_config.json" ]]
}

@test "no explicit path, config exists: still reads config (backward compat)" {
    local mock_dir="$TEST_TMPDIR/ida_config_compat"
    create_mock_ida_dir "$mock_dir"
    mkdir -p "$REPO_ROOT/.config"
    echo "{\"ida_path\":\"$mock_dir\"}" > "$REPO_ROOT/.config/ida_config.json"

    _stderr_file=$(mktemp)
    _stdout=$(detect_ida_path "" 2>"$_stderr_file") && _exit_status=0 || _exit_status=$?
    _stderr=$(cat "$_stderr_file")
    rm -f "$_stderr_file"

    [[ "$_exit_status" -eq 0 ]]
    [[ "$_stdout" == "$mock_dir" ]]
    [[ "$_stderr" == *"从配置文件读取"* ]]
}
