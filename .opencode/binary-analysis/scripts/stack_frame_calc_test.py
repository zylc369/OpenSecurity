#!/usr/bin/env python3
"""stack_frame_calc.py 边界测试矩阵——触发全部错误分支与边界输入

路径自包含: TOOL 从本文件位置推导; ELF 回归样本从仓库根推导，
样本缺失时自动 SKIP 该批用例（不判 FAIL，退出码仍 0）。
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL = os.path.join(HERE, "stack_frame_calc.py")
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))  # scripts -> binary-analysis -> .opencode -> root
ELF = os.path.join(REPO_ROOT, "docs", "分析", "二进制安全", "分析-RoboCall", "robocall")
ELF_AVAILABLE = os.path.exists(ELF)

PY = sys.executable
passed, failed, skipped = [], [], []


def run(args, desc, expect_exit_zero, expect_out=None, forbid_out=None, max_sec=None):
    if ("--elf" in args) and not ELF_AVAILABLE:
        skipped.append((desc, "ELF 回归样本缺失"))
        return
    t0 = time.time()
    r = subprocess.run([PY, TOOL] + args, capture_output=True, text=True, timeout=max_sec or 30)
    dt = time.time() - t0
    ok = True
    why = []
    if expect_exit_zero and r.returncode != 0:
        ok, why = False, [f"exit={r.returncode} 预期0, stderr={r.stderr.strip()[:120]}"]
    if not expect_exit_zero:
        if r.returncode == 0:
            ok, why = False, ["预期非零退出但 exit=0"]
        elif not (r.stdout.strip() + r.stderr.strip()):
            ok, why = False, ["非零退出但无任何输出"]
    if expect_out and expect_out not in (r.stdout + r.stderr):
        ok, why = False, why + [f"未含预期输出 {expect_out!r}"]
    if forbid_out and forbid_out in (r.stdout + r.stderr):
        ok, why = False, why + [f"含禁用输出 {forbid_out!r}"]
    (passed if ok else failed).append((desc, why or "OK", f"{dt:.2f}s"))


# === 错误分支 ===
run(["--subs", "0x110,0x170", "--chain", "a,b,c"], "chain/subs 长度不一致", False, "长度不一致")
run(["--elf", ELF, "--chain", "main,no_such_fn"], "chain 引用帧表外函数(含链尾)", False, "无函数 no_such_fn")
run(["--reach", "--target", "0x120"], "reach 缺 --loops", False, "--loops")
run(["--reach", "--loops", "0x120"], "reach 缺 --target", False, "--target")
run(["--chain", "a,b"], "chain 无帧表来源", False, "--elf")
run(["--elf", "/nonexistent/path/binary"], "elf 文件不存在", False, None)
run(["--reach", "--loops", "0x120", "--target", "0xZZ"], "非法数值输入", False, "非法数值")

with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
    f.write("this is not an elf\n" * 10)
    txt_path = f.name
run(["--elf", txt_path], "elf 非 ELF 文本文件", False, "not recognized")
os.unlink(txt_path)

# === 边界输入 ===
run(["--reach", "--loops", "", "--target", "0x120"], "空 loops 视为参数缺失(CLI 拦截)", False, "--loops")
run(["--reach", "--loops", "0x120", "--target", "0"], "target=0 零环即达", True, "无需任何环")
run(["--reach", "--loops", "0x120", "--target=-0x10"], "负 target(等号形式绕 argparse 负号)", True, "target 为负")
run(["--reach", "--loops", "0,0x120", "--target", "0x360"], "loops 含 0 值被过滤", True, "0x120×3", forbid_out="0x0×")
run(["--reach", "--loops", "0x120", "--target", "0x5A0", "--fixed-step", "0"], "fixed-step=0 等价无步进", True, "0x120×5")
run(["--reach", "--loops", "0x120", "--target", "1440"], "十进制参数 1440=0x5A0", True, "0x120×5")
run(["--reach", "--loops", "0x120,0x400", "--target", "0x690"], "不可达输出穷举证明而非相位", True,
    "完备穷举证明", forbid_out="模相位证据")
run(["--elf", ELF, "--chain", "main"], "单函数链", True, "rbp_offset=0x0")
run(["--subs", "0x100", "--chain", "solo"], "单函数链(subs)", True, "rbp_offset=0x0")

# === 性能边界 ===
run(["--reach", "--loops", "0x10,0x18", "--target", "0x100000"], "大 target(1MB 空间) BFS 性能", True,
    "可达", max_sec=60)

total = len(passed) + len(failed) + len(skipped)
print(f"\n通过 {len(passed)}/{total}" + (f"（SKIP {len(skipped)}）" if skipped else ""))
for d, w, t in passed:
    print(f"  PASS {d} ({t})")
for d, w in skipped:
    print(f"  SKIP {d}: {w}")
for d, w, t in failed:
    print(f"  FAIL {d}: {w} ({t})")
sys.exit(1 if failed else 0)
