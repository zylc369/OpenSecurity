#!/usr/bin/env bats
# test_detect_db_lock.bats — detect_db_lock.sh 的测试

load "test_helper"

DETECT_DB_LOCK_SH="$TEST_REPO_ROOT/shell/library/detect_db_lock.sh"

setup() {
    setup_test_env
    # shellcheck disable=SC1090
    source "$DETECT_DB_LOCK_SH"
}

teardown() {
    # 确保清理后台锁进程
    jobs -p 2>/dev/null | xargs -r kill 2>/dev/null || true
    wait 2>/dev/null || true
    teardown_test_env
}

# ---------- _derive_id0_path 测试 ----------

@test "_derive_id0_path: raw binary path appends .id0" {
    run _derive_id0_path "/tmp/test_binary"
    [ "$status" -eq 0 ]
    [ "$output" = "/tmp/test_binary.id0" ]
}

@test "_derive_id0_path: .i64 path replaces extension with .id0" {
    run _derive_id0_path "/tmp/test.i64"
    [ "$status" -eq 0 ]
    [ "$output" = "/tmp/test.id0" ]
}

@test "_derive_id0_path: .idb path replaces extension with .id0" {
    run _derive_id0_path "/tmp/test.idb"
    [ "$status" -eq 0 ]
    [ "$output" = "/tmp/test.id0" ]
}

@test "_derive_id0_path: path with multiple dots handles correctly for .i64" {
    run _derive_id0_path "/tmp/my.app.v2.i64"
    [ "$status" -eq 0 ]
    [ "$output" = "/tmp/my.app.v2.id0" ]
}

# ---------- check_db_lock 测试 ----------

@test "check_db_lock: .id0 does not exist returns 0" {
    run check_db_lock "$TEST_TMPDIR/nonexistent_binary"
    [ "$status" -eq 0 ]
}

@test "check_db_lock: .id0 exists but not locked returns 0" {
    touch "$TEST_TMPDIR/test.id0"
    run check_db_lock "$TEST_TMPDIR/test"
    [ "$status" -eq 0 ]
}

@test "check_db_lock: .i64 path with unlocked .id0 returns 0" {
    touch "$TEST_TMPDIR/test.id0"
    run check_db_lock "$TEST_TMPDIR/test.i64"
    [ "$status" -eq 0 ]
}

@test "check_db_lock: locked .id0 returns 1 and prints warning" {
    local id0_file="$TEST_TMPDIR/locked.id0"
    touch "$id0_file"

    # 用 python3 持有独占锁
    python3 -c "
import fcntl, time, sys
f = open(sys.argv[1], 'w')
fcntl.flock(f, fcntl.LOCK_EX)
time.sleep(30)
" "$id0_file" &
    local lock_pid=$!
    # 等待锁进程启动
    sleep 0.5

    run check_db_lock "$TEST_TMPDIR/locked"

    # 清理锁进程
    kill "$lock_pid" 2>/dev/null || true
    wait "$lock_pid" 2>/dev/null || true

    [ "$status" -eq 1 ]
    # 验证输出包含中文警告
    echo "$output" | grep -q "警告"
}

@test "check_db_lock: locked .id0 warning includes id0 path hint" {
    local id0_file="$TEST_TMPDIR/locked2.id0"
    touch "$id0_file"

    python3 -c "
import fcntl, time, sys
f = open(sys.argv[1], 'w')
fcntl.flock(f, fcntl.LOCK_EX)
time.sleep(30)
" "$id0_file" &
    local lock_pid=$!
    sleep 0.5

    run check_db_lock "$TEST_TMPDIR/locked2"

    kill "$lock_pid" 2>/dev/null || true
    wait "$lock_pid" 2>/dev/null || true

    [ "$status" -eq 1 ]
    echo "$output" | grep -q "$id0_file"
}

@test "check_db_lock: .idb path derivation works for lock check" {
    local id0_file="$TEST_TMPDIR/test_db.id0"
    touch "$id0_file"

    # 未锁定状态，使用 .idb 路径
    run check_db_lock "$TEST_TMPDIR/test_db.idb"
    [ "$status" -eq 0 ]
}
