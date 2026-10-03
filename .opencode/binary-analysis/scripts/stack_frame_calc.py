"""summary: 栈布局计算器 — 帧表提取 / 调用链帧距 / 环组合可达性

description:
  消除栈帧距手算错误（多级 16 进制累计 AI 心算不可靠）与环半群可达性心算不可靠问题。
  三模式:
    1. --elf <binary>                     提取帧表（函数名 → sub rsp 值）
    2. --elf <binary> --chain a,b,c       调用链帧距（每层 rbp 相对初始 rbp 偏移）
       或 --subs 0x110,0x170 --chain a,b  直接给 caller 的 sub 值序列
    3. --reach --loops 0x120,0x400 --target 0x690 [--fixed-step 0x440]
       环组合可达性 BFS（含可选固定步进任意倍数），输出组合方案；不可达时输出
       模相位证据（仅当 target 与增量模 16 不同余才有区分力）或完备穷举证明

usage:
  $PYTHON_CMD "$SHARED_DIR/scripts/stack_frame_calc.py" --elf ./target
  $PYTHON_CMD "$SHARED_DIR/scripts/stack_frame_calc.py" --elf ./target --chain main,menu_a,menu_b
  $PYTHON_CMD "$SHARED_DIR/scripts/stack_frame_calc.py" --subs 0x110,0x110,0x170 --chain f1,f2,f3
  $PYTHON_CMD "$SHARED_DIR/scripts/stack_frame_calc.py" --reach --loops 0x120,0x400 --target 0x5A0

level: intermediate

packages: 无第三方依赖（objdump 为系统命令）
"""

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class FrameInfo:
    """单个函数的栈帧信息"""
    name: str
    sub_size: int  # prologue 的 sub rsp 立即数


@dataclass
class ChainNode:
    """调用链中的一层"""
    name: str
    caller_sub: int   # 该层作为 caller 调下一层时的 sub（决定到下一层的距离）
    rbp_offset: int   # 本层 rbp 相对链首 rbp 的偏移（负值 = 更深）


@dataclass
class ChainResult:
    """调用链帧距计算结果"""
    nodes: list[ChainNode] = field(default_factory=list)

    def render(self) -> str:
        lines = ["调用链帧距（rbp 相对链首）:"]
        for n in self.nodes:
            lines.append(f"  {n.name:24s} caller_sub={n.caller_sub:#x}  rbp_offset={n.rbp_offset:#x}")
        if len(self.nodes) >= 2:
            first, last = self.nodes[0], self.nodes[-1]
            lines.append(f"链首→链尾总距离: {first.rbp_offset - last.rbp_offset:#x}（{first.name} rbp - {last.name} rbp）")
        return "\n".join(lines)


@dataclass
class ReachResult:
    """环组合可达性结果"""
    target: int
    reachable: bool
    solution: list[tuple[int, int]] = field(default_factory=list)  # [(增量, 次数), ...]
    mod_phase: str = ""                             # 不可达时的相位证据

    def render(self) -> str:
        if self.reachable:
            combo = " + ".join(f"{v:#x}×{c}" for v, c in self.solution if c > 0)
            return f"target={self.target:#x} 可达: {combo or '0（无需任何环）'}"
        return f"target={self.target:#x} 不可达。{self.mod_phase}"


def parse_size(v: str) -> int:
    try:
        return int(v, 0)  # 自动识别 0x 前缀 / 十进制
    except ValueError:
        sys.exit(f"错误: 非法数值 {v!r}（支持 0x 前缀十六进制或十进制; 负数请用等号形式 --target=-0x10）")


def extract_frames(elf_path: str) -> list[FrameInfo]:
    """objdump 反汇编提取每函数 sub rsp 值（同函数多次 sub 累计——栈探测/分段扩帧）

    已知启发式边界（异常值回 gdb 校验）: ① 同函数 sub 序列为 [小(<0x10), 大] 时首个小 sub
    被忽略（[大, 小] 顺序则累计正确，顺序敏感）; ② `and rsp, -16` 类对齐调整与
    非立即数动态栈分配不建模。
    """
    try:
        out = subprocess.run(
            ["objdump", "-d", "-M", "intel", elf_path],
            capture_output=True, text=True, timeout=120, check=True).stdout
    except FileNotFoundError:
        sys.exit("错误: 未找到 objdump（系统命令）")
    except subprocess.TimeoutExpired:
        sys.exit("错误: objdump 超时（120s）——目标二进制过大或 objdump 挂起")
    except subprocess.CalledProcessError as e:
        sys.exit(f"错误: objdump 失败: {e.stderr[:200]}")

    frames: dict[str, FrameInfo] = {}
    cur_func = None
    for line in out.splitlines():
        m = re.match(r"^[0-9a-f]+ <(.+)>:", line.strip())
        if m:
            cur_func = m.group(1)
            continue
        if cur_func is None:
            continue
        m2 = re.search(r"sub\s+rsp,\s*0x([0-9a-f]+)", line)
        if m2:
            val = int(m2.group(1), 16)
            if cur_func in frames:
                # 同函数多次 sub（栈探测/分段扩帧）→ 累计
                frames[cur_func].sub_size += val
            elif val >= 0x10:  # 首个 <0x10 视为对齐垫片忽略
                frames[cur_func] = FrameInfo(name=cur_func, sub_size=val)
    result = list(frames.values())
    if not result:
        sys.exit("错误: 未提取到任何 sub rsp 帧信息（目标无带栈帧的函数符号——纯数据对象或符号被剥离）")
    return result


def calc_chain(names: list[str], subs: list[int]) -> ChainResult:
    """链式帧距: 第 k 层 rbp = 前层 rbp - 前层.sub - 0x10 (ret + push rbp)

    subs[i] 是第 i 层作为 caller 调用第 i+1 层时的 sub 值。
    链尾（最后一层）的 sub 不影响任何 rbp，填 0 即可。
    """
    if len(names) != len(subs):
        sys.exit(f"错误: --chain 名单({len(names)}) 与 --subs 序列({len(subs)}) 长度不一致")
    result = ChainResult()
    offset = 0
    for i, (name, sub) in enumerate(zip(names, subs)):
        if i > 0:
            offset -= subs[i - 1] + 0x10
        result.nodes.append(ChainNode(name=name, caller_sub=sub, rbp_offset=offset))
    return result


def calc_reach(loops: list[int], target: int, fixed_step: int) -> ReachResult:
    """BFS: target 能否表示为 Σ(c_i × loop_i) + k × fixed_step (c_i, k ≥ 0)

    搜索上界 target + max(loops, default=fixed_step)，防死循环。
    """
    if target < 0:
        return ReachResult(target, False, mod_phase="target 为负")
    steps = sorted(set(loops) | ({fixed_step} if fixed_step > 0 else set()))
    steps = [s for s in steps if s > 0]
    if not steps:
        return ReachResult(target, reachable=(target == 0), solution=[(0, 1)] if target == 0 else [],
                           mod_phase="" if target == 0 else "无可用增量")
    upper = target + max(steps)
    # BFS: parent[sum] = (prev_sum, step) 用于回溯组合
    parent: dict = {0: None}
    queue = [0]
    while queue:
        cur = queue.pop(0)
        if cur == target:
            break
        for s in steps:
            nxt = cur + s
            if nxt <= upper and nxt not in parent:
                parent[nxt] = (cur, s)
                queue.append(nxt)
    if target not in parent:
        # BFS 穷举是完备证明: 所有步进为正且搜索上界覆盖全部可达部分和，无解即严格不可达
        residues = sorted({s % 16 for s in steps})
        t_mod = target % 16
        if t_mod not in residues:
            note = (f"模相位证据: target mod 16 = {t_mod} 不在各增量 mod 16 集合 {residues} 内——"
                    f"结构性不可达; 数值上界 {upper:#x} 内 BFS 全空间亦无解")
        else:
            note = (f"完备穷举证明: 数值上界 {upper:#x} 内 BFS 全空间无解"
                    f"（mod 16 无区分力: target 与增量同余 {t_mod}，不可达源于数值组合而非相位）")
        return ReachResult(target, False, mod_phase=note)
    # 回溯组合
    counter: dict = {}
    cur = target
    while parent[cur] is not None:
        prev, s = parent[cur]
        counter[s] = counter.get(s, 0) + 1
        cur = prev
    return ReachResult(target, True, solution=sorted(counter.items()))


def main():
    ap = argparse.ArgumentParser(description="栈布局计算器: 帧表/链距/环可达性")
    ap.add_argument("--elf", help="目标 ELF（提取帧表 / 为 --chain 提供帧数据）")
    ap.add_argument("--chain", help="调用链函数名序列, 逗号分隔（首层为链首）")
    ap.add_argument("--subs", help="直接给各层 caller 的 sub rsp 值序列, 逗号分隔（与 --elf 二选一）")
    ap.add_argument("--reach", action="store_true", help="环组合可达性模式")
    ap.add_argument("--loops", help="环增量列表, 逗号分隔（--reach 模式必填）")
    ap.add_argument("--target", help="目标偏移（--reach 模式必填）")
    ap.add_argument("--fixed-step", dest="fixed_step", default="0",
                    help="额外允许的固定步进（如每层递归帧深），可取任意倍数")
    args = ap.parse_args()

    # 参数组合校验: 模式互斥，防止静默忽略
    if args.reach and (args.elf or args.chain or args.subs):
        sys.exit("错误: --reach 与 --elf/--chain/--subs 互斥（不同时使用）")
    if args.elf and args.subs:
        sys.exit("错误: --elf 与 --subs 互斥（帧表来源二选一）")
    if args.chain and not (args.elf or args.subs):
        sys.exit("错误: --chain 需要 --elf（帧表来源）或 --subs（直接序列）之一")

    if args.reach:
        if not args.loops or not args.target:
            sys.exit("错误: --reach 需要 --loops 与 --target")
        loops = [parse_size(x) for x in args.loops.split(",") if x.strip()]
        print(calc_reach(loops, parse_size(args.target), parse_size(args.fixed_step)).render())
        return

    frames: dict[str, FrameInfo] = {}
    if args.elf:
        frames = {f.name: f for f in extract_frames(args.elf)}
        if not args.chain:
            print("帧表（函数名 → sub rsp）:")
            for f in frames.values():
                print(f"  {f.name:32s} {f.sub_size:#x}")
            return
    if args.chain:
        names = [x.strip() for x in args.chain.split(",") if x.strip()]
        if args.subs:
            subs = [parse_size(x) for x in args.subs.split(",") if x.strip()]
        else:  # 前置校验保证: 无 --subs 时 --chain 必伴随 --elf（frames 已就绪）
            subs = []
            for i, n in enumerate(names):
                if n not in frames:  # 链尾 sub 虽不参与计算，名字拼错同样必须报错
                    sys.exit(f"错误: 帧表中无函数 {n}（用 --elf 提取后核对名称）")
                if i < len(names) - 1:  # 链尾 sub 不参与，补 0
                    subs.append(frames[n].sub_size)
                else:
                    subs.append(0)
        print(calc_chain(names, subs).render())
        return

    ap.print_help()


if __name__ == "__main__":
    main()
