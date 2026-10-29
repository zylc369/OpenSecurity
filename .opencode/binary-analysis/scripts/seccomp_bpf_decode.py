#!/usr/bin/env python3
"""seccomp BPF 手解码器 — 从 idat 反汇编输出提取"运行时栈上构造"的 sock_filter 数组并解码。

适用场景: seccomp-tools 不可用时（macOS 主机无法执行 Linux ELF / 容器内 gem 安装失败），
且 filter 不是静态数据而是在 main/初始化函数里用一串 `mov reg, imm64` + `mov [rsp+..], reg`
写到栈上再传给 prctl(2)/seccomp(317) 的形态。

输入: idat `IDA_QUERY=disassemble` 产出的 JSON（取 disassembly 字段），或等价纯文本反汇编文件。
原理: 顺序扫描指令流，追踪 64 位寄存器的立即数赋值；`mov [rsp+X+Y], reg64`（无 word/dword 前缀）
视为 qword 栈槽写入；对收集到的 qword 做 sock_filter 合法性过滤（code/jt/jf/k 结构约束），
按指令顺序输出指令表、RET 动作、syscall 白名单候选。

用法:
    python3 seccomp_bpf_decode.py --file main_disas.json
    python3 seccomp_bpf_decode.py --file disas.txt --json false
"""
import argparse
import json
import re
import sys
from dataclasses import dataclass, field

# 常见 x86_64 syscall 号→名（白名单场景高频项; 未收录显示号）
SYSCALL_NAMES = {
    0: "read", 1: "write", 2: "open", 3: "close", 4: "stat", 5: "fstat", 6: "lstat",
    7: "poll", 8: "lseek", 9: "mmap", 10: "mprotect", 11: "munmap", 12: "brk",
    13: "rt_sigaction", 14: "rt_sigprocmask", 15: "rt_sigreturn", 16: "ioctl",
    17: "pread64", 18: "pwrite64", 19: "readv", 20: "writev", 21: "access",
    22: "pipe", 23: "select", 24: "sched_yield", 32: "dup", 33: "dup2",
    34: "pause", 35: "nanosleep", 39: "getpid", 41: "socket", 42: "connect",
    43: "accept", 44: "sendto", 45: "recvfrom", 46: "sendmsg", 47: "recvmsg",
    49: "bind", 50: "listen", 54: "setsockopt", 55: "getsockopt", 56: "clone",
    57: "fork", 58: "vfork", 59: "execve", 60: "exit", 61: "wait4", 62: "kill",
    63: "uname", 72: "fcntl", 73: "flock", 79: "getcwd", 80: "chdir",
    85: "creat", 86: "link", 87: "unlink", 88: "symlink", 89: "readlink",
    90: "chmod", 92: "chown", 96: "gettimeofday", 101: "ptrace", 102: "getuid",
    104: "getgid", 105: "setuid", 106: "setgid", 107: "geteuid", 108: "getegid",
    125: "capget", 131: "sigaltstack",
    137: "statfs", 158: "arch_prctl", 160: "setrlimit", 186: "gettid",
    218: "set_tid_address", 231: "exit_group", 232: "epoll_wait",
    233: "epoll_ctl", 257: "openat", 258: "mkdirat", 262: "newfstatat",
    273: "set_robust_list", 302: "prlimit64", 306: "syncfs", 317: "seccomp",
    318: "getrandom", 319: "memfd_create", 322: "execveat", 437: "openat2",
}

RET_ACTIONS = {
    0x7FFF0000: "ALLOW", 0x80000000: "KILL_PROCESS", 0x00000000: "KILL_THREAD",
    0x00030000: "TRAP", 0x7FF00000: "TRACE", 0x7FFC0000: "LOG",
    0x7FC00000: "USER_NOTIF",
}
BPF_CODES = {0x20: "LD_W_ABS", 0x15: "JEQ_K", 0x25: "JGT_K", 0x35: "JGE_K",
             0x45: "JSET_K", 0x05: "JA", 0x06: "RET", 0x28: "LD_H_ABS",
             0x30: "LD_B_ABS"}
LD_OFFSET_MEANING = {0: "nr(syscall号)", 4: "arch", 8: "instruction_pointer+0"}
REG64 = {"rax", "rbx", "rcx", "rdx", "rsi", "rdi", "rbp", "rsp",
         "r8", "r9", "r10", "r11", "r12", "r13", "r14", "r15"}

_TAIL = r"(?:\s*;.*)?$"
_STK = r"\[rsp\+[0-9A-Fa-f]+h\+\w+\]"
RE_MOV_IMM = re.compile(r"^\s*(?:0x[0-9A-Fa-f]+\s+)?mov\s+(%s),\s*((?:0x)?[0-9A-Fa-f]+h?)" % "|".join(REG64) + _TAIL)
RE_MOV_STK = re.compile(r"^\s*(?:0x[0-9A-Fa-f]+\s+)?mov\s+(?:qword ptr )?%s,\s*(%s)" % (_STK, "|".join(REG64)) + _TAIL)
RE_MOV_STK_IMM = re.compile(r"^\s*(?:0x[0-9A-Fa-f]+\s+)?mov\s+(?:qword ptr )?%s,\s*((?:0x)?[0-9A-Fa-f]+h?)" % _STK + _TAIL)
# 值失效形态: lea 装地址 / 寄存器间 mov（源非常量）/ xor|sub 同寄存器清零——命中即从常量追踪中移除
RE_LEA = re.compile(r"^\s*(?:0x[0-9A-Fa-f]+\s+)?lea\s+(%s)," % "|".join(REG64))
RE_MOV_REG = re.compile(r"^\s*(?:0x[0-9A-Fa-f]+\s+)?mov\s+(%s),\s*(%s)" % ("|".join(REG64), "|".join(REG64)))
RE_SELF_CLEAR = re.compile(r"^\s*(?:0x[0-9A-Fa-f]+\s+)?(?:xor|sub)\s+(\w+),\s*(\w+)" + _TAIL)


def _canon_reg(name: str) -> str:
    """eax→rax、r8d→r8（32 位名归一到 64 位名）; 非寄存器名原样返回。"""
    base = {"eax": "rax", "ebx": "rbx", "ecx": "rcx", "edx": "rdx", "esi": "rsi",
            "edi": "rdi", "ebp": "rbp", "esp": "rsp"}
    if name in base:
        return base[name]
    if len(name) >= 3 and name.endswith("d") and name[:-1] in REG64:
        return name[:-1]
    return name


@dataclass
class DecodeResult:
    """解码产物: 指令表 + 白名单候选 + 对账信息。"""
    instructions: list = field(default_factory=list)   # list[tuple[int, str, int, int, int]]: (pc, code_name, jt, jf, k)
    syscall_candidates: list = field(default_factory=list)  # list[int]: JEQ 的 k（排除 arch 常量）
    ret_actions: list = field(default_factory=list)    # list[tuple[int, str]]: (pc, action)
    arch_check: bool = False
    dropped_qwords: int = 0


def parse_value(tok: str) -> int:
    """'0x...' / 'ABh' / 十进制 / 纯十六进制串（A 开头无 0x 前缀）→ int。"""
    tok = tok.strip()
    if tok.endswith("h") or tok.endswith("H"):
        return int(tok[:-1], 16)
    if tok.startswith("0x") or tok.startswith("0X"):
        return int(tok, 16)
    try:
        return int(tok, 10)
    except ValueError:
        return int(tok, 16)


def is_plausible_filter(val: int) -> bool:
    """qword 是否像一个合法 sock_filter（code/jt/jf/k 结构约束）。"""
    code = val & 0xFFFF
    jt = (val >> 16) & 0xFF
    jf = (val >> 24) & 0xFF
    k = (val >> 32) & 0xFFFFFFFF
    if code not in BPF_CODES:
        return False
    if code == 0x06:  # RET: k 必须是已知 action 或 ERRNO 族 (0x00050000|errno)
        if k in RET_ACTIONS:
            return True
        return (k & 0xFFFF0000) == 0x00050000
    if code == 0x20:  # LD W ABS: 偏移在 seccomp_data 范围内 (0..63)
        return k <= 63
    # JEQ/JGT/JGE/JSET: k 是 syscall 号(<512)、arch 常量或掩码; jt/jf 上限 255 结构上恒真，
    # 跳转合法性由长度对账提示，不在此拒绝
    return k <= 0xFFFFFFFF


def decode(text: str) -> DecodeResult:
    res = DecodeResult()
    regs: dict = {}
    for line in text.splitlines():
        m = RE_MOV_IMM.match(line)
        if m:
            regs[m.group(1)] = parse_value(m.group(2))
            continue
        if RE_LEA.match(line):
            regs.pop(RE_LEA.match(line).group(1), None)   # 寄存器装地址，常量失效
            continue
        m = RE_MOV_REG.match(line)
        if m:
            if m.group(2) in regs:
                regs[m.group(1)] = regs[m.group(2)]       # 寄存器间传常量
            else:
                regs.pop(m.group(1), None)                # 源未知则目标也失效
            continue
        m = RE_SELF_CLEAR.match(line)
        if m:
            r = _canon_reg(m.group(1))
            if r == _canon_reg(m.group(2)) and r in REG64:
                regs.pop(r, None)                         # xor/sub 同名自清零（32 位形式清整个寄存器）
            continue
        m = RE_MOV_STK.match(line)
        if m:
            val = regs.get(m.group(1))
            if val is None:
                continue
            _absorb(res, val)
            continue
        m = RE_MOV_STK_IMM.match(line)
        if m:
            _absorb(res, parse_value(m.group(1)))
    return res


def _absorb(res: DecodeResult, val: int) -> None:
    """一个写入栈槽的 qword，若形态合法则解码为一条 sock_filter。"""
    if is_plausible_filter(val):
        code = val & 0xFFFF
        jt = (val >> 16) & 0xFF
        jf = (val >> 24) & 0xFF
        k = (val >> 32) & 0xFFFFFFFF
        pc = len(res.instructions)
        res.instructions.append((pc, BPF_CODES[code], jt, jf, k))
        if code == 0x06:
            act = RET_ACTIONS.get(k, f"ERRNO({k & 0xFFFF})")
            res.ret_actions.append((pc, act))
        elif code == 0x15:
            if k == 0xC000003E:
                res.arch_check = True
            elif k < 512:
                res.syscall_candidates.append(k)
    elif val >> 32 != 0 or (val & 0xFFFF) in BPF_CODES:
        res.dropped_qwords += 1


def render(res: DecodeResult) -> str:
    out = []
    out.append(f"=== sock_filter 指令（{len(res.instructions)} 条，按构造指令序，非数组执行序）===")
    out.append("（编译器会重排初始化指令，此表 pc 列与跳转目标仅供形态参考; "
               "条数请与 prctl 调用点的 sock_fprog.len 对账; 下方白名单/RET 分布是集合级结论，与顺序无关）")
    out.append(f"{'pc':>3}  {'code':<9} {'jt':>3} {'jf':>3}  {'k':>12}  语义")
    for pc, name, jt, jf, k in res.instructions:
        if name == "RET":
            act = RET_ACTIONS.get(k, f"ERRNO({k & 0xFFFF})")
            meaning = f"RET {act}"
        elif name == "LD_W_ABS":
            meaning = f"A = seccomp_data[{k}] ({LD_OFFSET_MEANING.get(k, 'arg')})"
        elif name == "JEQ_K":
            meaning = f"A == {k} ({SYSCALL_NAMES.get(k, '?') if k < 512 else hex(k)})? true->pc{pc + 1 + jt} false->pc{pc + 1 + jf}"
        else:
            meaning = f"{name} k={k}"
        out.append(f"{pc:>3}  {name:<9} {jt:>3} {jf:>3}  {k:>12}  {meaning}")
    out.append("")
    out.append(f"=== arch 检查（JEQ 0xC000003E）: {'存在' if res.arch_check else '未见'}")
    out.append(f"=== RET 动作分布: " + ", ".join(f"pc{p}:{a}" for p, a in res.ret_actions))
    if res.syscall_candidates:
        names = [f"{n}({SYSCALL_NAMES.get(n, '?')})" for n in res.syscall_candidates]
        out.append("=== JEQ 比较的 syscall 号（白名单形态 filter 即允许清单; "
                   "黑名单形态（默认 ALLOW + JEQ→KILL）则此表为封禁清单，以 RET 分布为准）:")
        out.append("    " + ", ".join(names))
    if res.dropped_qwords:
        out.append(f"=== 注意: {res.dropped_qwords} 个 qword 形态可疑被丢弃（若白名单缺项，检查是否为非 mov-立即数形态构造）")
    return "\n".join(out)


def load_text(path: str, as_json: bool) -> str:
    with open(path, encoding="utf-8", errors="replace") as f:
        raw = f.read()
    if not as_json:
        return raw
    data = json.loads(raw)
    for key in ("disassembly", "source"):
        if isinstance(data, dict) and isinstance(data.get(key), str):
            return data[key]
        if isinstance(data, dict) and isinstance(data.get("data"), dict) \
                and isinstance(data["data"].get(key), str):
            return data["data"][key]
    raise SystemExit("[!] JSON 中未找到 disassembly/source 字段（确认是 IDA_QUERY=disassemble 产物）")


def main() -> int:
    ap = argparse.ArgumentParser(description="从 idat 反汇编输出解码栈上构造的 seccomp BPF filter")
    ap.add_argument("--file", required=True, help="反汇编文件路径（idat disassemble JSON 或纯文本）")
    ap.add_argument("--json", default="true", choices=["true", "false"],
                    help="输入是否为 idat JSON（默认 true）")
    args = ap.parse_args()
    text = load_text(args.file, args.json == "true")
    res = decode(text)
    if not res.instructions:
        print("[!] 未识别出 filter 指令——确认反汇编里存在 `mov reg64, imm64` + `mov [rsp+..], reg64` 构造形态")
        return 1
    print(render(res))
    return 0


if __name__ == "__main__":
    sys.exit(main())
