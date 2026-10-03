#!/bin/bash
# run_sigwrap_tests.sh — sigwrap_tracer.c 全量回归（9 模式 22 断言; 在 Linux x86-64 容器内执行）
# 前置: gcc -shared -fPIC -O2 -Wall -o /tmp/sigwrap.so sigwrap_tracer.c -ldl
#       gcc -O0 -Wall -o /tmp/edge sigwrap_tracer_test.c
# 宿主调用示例: docker run --rm -v $SHARED_DIR/scripts:/s:ro ubuntu:24.04 bash -c '<上面两行编译> && bash /s/run_sigwrap_tests.sh' 
S=/tmp/sigwrap.so; E=/tmp/edge
pass=0; fail=0
chk() { if [ "$2" = "$3" ]; then echo "  [$1] PASS ($2)"; pass=$((pass+1)); else echo "  [$1] FAIL (got=$2 want=$3)"; fail=$((fail+1)); fi; }

echo "== T1 gptr =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t1.log $E gptr >/dev/null 2>&1
chk "S行内容" "$(grep -c '887766554433221100ffeeddccbbaa99' /tmp/t1.log)" "1"
echo "== T2 max =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t2.log $E max 2>/tmp/t2.err >/dev/null; ec=$?
chk "exit" "$ec" "1"; chk "TOO_MANY" "$(grep -c TOO_MANY /tmp/t2.log)" "1"
chk "stderr泄漏" "$(grep -c RESTORE_LEAK /tmp/t2.err)" "0"
echo "== T3 page =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t3.log $E page >/dev/null 2>&1; ec=$?
chk "exit" "$ec" "0"
chk "code长度18/30" "$(grep '^T#' /tmp/t3.log | sed 's/.*code=\([0-9a-f]*\) .*/\1/' | awk '{print length($0)}' | tr '\n' ',')" "18,30,"
echo "== T4 mixed =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t4.log $E mixed >/dev/null 2>&1; ec=$?
chk "exit" "$ec" "0"; chk "三信号" "$(grep '^T#' /tmp/t4.log | awk '{print $2}' | tr '\n' ' ')" "s=5 s=4 s=8 "
echo "== T5 ign =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t5.log $E ign >/dev/null 2>&1; ec=$?
chk "exit" "$ec" "0"; chk "仅1行s=5" "$(grep -c '^T#' /tmp/t5.log)" "1"; chk "无s=10" "$(grep -c 's=10 ' /tmp/t5.log)" "0"
echo "== T6 multi (Bug1 每信号槽) =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t6.log $E multi 2>/tmp/t6.err >/dev/null; ec=$?
chk "exit" "$ec" "0"; chk "WHICH=3" "$(grep WHICH /tmp/t6.err)" "WHICH=3"
chk "traps=2" "$(grep -c '^T#' /tmp/t6.log)" "2"
echo "== T7 nosiginfo (Bug2 SA_SIGINFO 防护) =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t7.log $E nosiginfo 2>/tmp/t7.err >/dev/null; ec=$?
chk "exit" "$ec" "0"; chk "NSI=1(handler执行)" "$(grep NSI /tmp/t7.err)" "NSI=1"
chk "无s=10行(透传)" "$(grep -c '^T#' /tmp/t7.log)" "0"
echo "== T8 savere (Bug3 oldact 修正) =="
timeout 10 env LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t8.log $E savere 2>/tmp/t8.err >/dev/null; ec=$?
chk "exit" "$ec" "0"; chk "SAVED=1(真handler)" "$(grep SAVED /tmp/t8.err)" "SAVED=1"
chk "traps有限(≤3)" "$([ $(grep -c '^T#' /tmp/t8.log) -le 3 ] && echo yes)" "yes"
echo "== T9 unmapped (问题4 pread 安全读) =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t9.log $E unmapped >/dev/null 2>&1; ec=$?
chk "exit" "$ec" "0"; chk "code=?行存在" "$(grep -c 'code=?' /tmp/t9.log)" "1"
echo "== T10 lowaddr (GPTR 不可读地址防御) =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t10.log $E lowaddr >/dev/null 2>&1; ec=$?
chk "exit" "$ec" "0"; chk "无S行不崩" "$(grep -c '^S ' /tmp/t10.log)" "0"; chk "trap仍记录" "$(grep -c '^T#' /tmp/t10.log)" "1"
echo "== T11 altstack (SA_ONSTACK) =="
LD_PRELOAD=$S SIGWRAP_LOG=/tmp/t11.log $E altstack >/dev/null 2>&1; ec=$?
chk "exit" "$ec" "0"; chk "1行s=5" "$(grep -c '^T#' /tmp/t11.log)" "1"
echo "== 汇总 =="
echo "PASS=$pass FAIL=$fail"
