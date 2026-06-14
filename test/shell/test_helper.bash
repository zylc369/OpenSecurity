#!/usr/bin/env bash
# test_helper.bash — bats 测试共享辅助函数

# 项目根目录（相对于 test/shell/）
readonly TEST_REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# 创建临时测试环境
setup_test_env() {
    TEST_TMPDIR="$(mktemp -d)"
    export TEST_TMPDIR
    export REPO_ROOT="$TEST_TMPDIR/repo"
    mkdir -p "$REPO_ROOT/.config"
    mkdir -p "$REPO_ROOT/shell/library"
}

# 清理临时测试环境
teardown_test_env() {
    if [[ -n "${TEST_TMPDIR:-}" && -d "${TEST_TMPDIR:-}" ]]; then
        rm -rf "$TEST_TMPDIR"
    fi
}

# 创建模拟 IDA Pro 目录（含 ida 和 idat 可执行文件）
# 用法: create_mock_ida_dir <dir_path>
create_mock_ida_dir() {
    local ida_dir="$1"
    mkdir -p "$ida_dir"
    # 创建模拟可执行文件
    touch "$ida_dir/ida"
    touch "$ida_dir/idat"
    chmod +x "$ida_dir/ida"
    chmod +x "$ida_dir/idat"
}

# 模拟用户输入（通过 stdin 管道）
# 用法: mock_read_input "user input value"
mock_read_input() {
    echo "$1"
}

# 断言字符串包含子串
# 用法: assert_contains "haystack" "needle"
assert_contains() {
    local haystack="$1"
    local needle="$2"
    if [[ "$haystack" != *"$needle"* ]]; then
        echo "FAIL: expected '$haystack' to contain '$needle'" >&2
        return 1
    fi
}

# 断言文件存在
# 用法: assert_file_exists <path>
assert_file_not_exists() {
    if [[ -f "$1" ]]; then
        echo "FAIL: expected file NOT to exist: $1" >&2
        return 1
    fi
}
