#!/usr/bin/env bats

load "test_helper"

SCRIPT_UNDER_TEST="$TEST_REPO_ROOT/disassembler/dump_func_disasm.sh"
CAPTURE_FILE=""
MOCK_IDA_DIR=""

setup() {
    setup_test_env
    CAPTURE_FILE="$TEST_TMPDIR/mock_idat_capture.txt"
    MOCK_IDA_DIR="$TEST_TMPDIR/mock_ida_dir"

    mkdir -p "$MOCK_IDA_DIR"
    cat > "$MOCK_IDA_DIR/idat" << 'MOCK_EOF'
#!/usr/bin/env bash
{
    echo "IDA_FUNC_ADDR=$IDA_FUNC_ADDR"
    echo "IDA_OUTPUT=$IDA_OUTPUT"
    printf 'ARG|%s\n' "$@"
} > "$MOCK_IDA_DIR/capture.txt"
exit 0
MOCK_EOF
    chmod +x "$MOCK_IDA_DIR/idat"
    touch "$MOCK_IDA_DIR/ida"
    chmod +x "$MOCK_IDA_DIR/ida"

    mkdir -p "$REPO_ROOT/.config"
    echo "{\"ida_path\":\"$MOCK_IDA_DIR\"}" > "$REPO_ROOT/.config/ida_config.json"

    touch "$TEST_TMPDIR/binary.i64"

    source "$SCRIPT_UNDER_TEST"
}

teardown() {
    teardown_test_env
}

@test "--addr --input: constructs correct idat command with env vars" {
    run main --addr main --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 0 ]
    grep -q "IDA_FUNC_ADDR=main" "$CAPTURE_FILE"
    grep -q "IDA_OUTPUT=" "$CAPTURE_FILE"
}

@test "--addr hex --output --input: IDA_OUTPUT set correctly" {
    run main --addr 0x401000 --output /tmp/out.asm --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 0 ]
    grep -q "IDA_FUNC_ADDR=0x401000" "$CAPTURE_FILE"
    grep -q "IDA_OUTPUT=/tmp/out.asm" "$CAPTURE_FILE"
}

@test "--addr --log --input: -L flag set correctly" {
    run main --addr main --log /custom/log.log --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 0 ]
    grep -q "ARG|-L/custom/log.log" "$CAPTURE_FILE"
}

@test "missing --addr: error and exit 1" {
    run main --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 1 ]
    [[ "$output" == *"必须指定 --addr 参数"* ]]
}

@test "missing --input: error and exit 1" {
    run main --addr main
    [ "$status" -eq 1 ]
    [[ "$output" == *"必须指定 --input 参数"* ]]
}

@test "non-existent input file: error and exit 1" {
    run main --addr main --input "$TEST_TMPDIR/nonexistent.i64"
    [ "$status" -eq 1 ]
    [[ "$output" == *"目标文件不存在"* ]]
}

@test "--output omitted: defaults to script directory" {
    run main --addr main --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 0 ]
    local captured_output
    captured_output=$(grep "IDA_OUTPUT=" "$CAPTURE_FILE" | cut -d= -f2-)
    [[ "$captured_output" == *"/disassembler" ]]
}

@test "--log omitted: defaults to dump_func_disasm.log" {
    run main --addr main --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 0 ]
    grep -q "ARG|-L.*dump_func_disasm.log" "$CAPTURE_FILE"
}

@test "directories auto-created via mkdir -p" {
    local deep_dir="$TEST_TMPDIR/deep/nested"
    run main --addr main --output "$deep_dir/output.asm" --input "$TEST_TMPDIR/binary.i64"
    [ "$status" -eq 0 ]
    [ -d "$deep_dir" ]
}

@test "spaces in input path: handled correctly" {
    mkdir -p "$TEST_TMPDIR/path with spaces"
    touch "$TEST_TMPDIR/path with spaces/binary.i64"
    run main --addr main --input "$TEST_TMPDIR/path with spaces/binary.i64"
    [ "$status" -eq 0 ]
    grep -q "IDA_FUNC_ADDR=main" "$CAPTURE_FILE"
    grep -q "binary.i64" "$CAPTURE_FILE"
}
