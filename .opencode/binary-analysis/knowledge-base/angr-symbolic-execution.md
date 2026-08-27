# 符号执行与约束求解 — angr / Z3 / Unicorn 用法体系

> 逆向自动化（求满足校验的输入/恢复密钥/模拟执行）时加载。
> Unicorn 的 IDA 集成模拟模板见 `unicorn-templates.md`（基础 setup）。

## 触发条件

- 需要自动求出使二进制到达目标分支的输入（flag/序列号/key）
- 校验逻辑是方程组/XOR/模运算——直接 Z3
- 需要模拟执行特定函数（脱壳/解密/爆破）

## §1 工具选型

纯数学→Z3 | 二进制控制流→angr | 特定区域模拟→Unicorn | 自定义 VM→angr+Unicorn | 固件→Qiling。
`pip install angr z3-solver unicorn capstone keystone-engine`。

## §2 angr 核心

`Project(bin, auto_load_libs=False)` → `entry_state/blank_state(addr=)/full_init_state(args=)` → `simulation_manager` → `explore(find=, avoid=)` → `found[0].solver.eval(sym, cast_to=bytes)`。
- claripy: `BVS("x", 64)` / `BVV` / `solver.add(约束)` / `eval` / `eval_upto(sym, 10)`
- 符号输入: stdin=`entry_state(stdin=sym)`（逐字节 0x20-0x7e 约束）; argv=`full_init_state(args=['./bin', sym])`; 文件=`SimFile` + `fs={}`
- find/avoid 可用地址或 stdout 内容 lambda（`b"Correct" in s.posix.dumps(1)`，PIE 用）
- **坑**: 反汇编器与 angr 的 PIE 加载基址不同（Ghidra 默认 0x100000 vs angr 0x400000）——搬地址前先对基址; 函数名可能是伪造符号（`__stack_chk_fail` 未必是真 stack_chk_fail，自定义函数可冒名）——不要按名字假设语义

## §3 hook 体系

```python
@proj.hook(0x401100, length=5)          # 跳过检查/反调试（length=原指令字节数）
def skip(state): state.regs.eax = 1

proj.hook_symbol('printf', angr.SIM_PROCEDURES['libc']['printf'])  # 内置
class MyScanf(angr.SimProcedure):       # 自定义——符号输入写内存+globals 暂存
    def run(self, fmt, ptr):
        buf = claripy.BVS("in", 8*32)
        self.state.memory.store(ptr, buf)
        self.state.globals['scanf_buf'] = buf; return 1
```
strcmp 泄漏期望值: hook 后存 s2 地址到 globals → found 后 load+eval 出正确串。rand/time 具体化消除非确定性。

## §4 路径爆炸管理

约束输入空间 / avoid 回环边 / hook 复杂函数 / **Veritesting**（分支合并，逐字符检查加速）/ DFS（深路径）/ LAZY_SOLVES / **Unicorn 混合**（`add_options={angr.options.unicorn}`——具体区原生跑）/ `signal.alarm` 超时包 explore / num_find=1。

## §5 高级模式

- **多阶段**: 每段 explore 后 `state = simgr.found[0]` 带约束进下一段
- **格式剪枝**: 前缀逐字节 `==`、尾字节 `==`、内容 `claripy.Or(And(...))` 字符集
- **blank_state 定点**: `blank_state(addr=CHECK_FUNC)` + `memory.store(BUF, sym)` + `regs.rdi/rsi` 手动设参 + `stack_push(0xDEADBEEF)` 假返回——跳过全部初始化

## §6 Z3 逆向模式

```python
key = [BitVec(f'k{i}', 8) for i in range(16)]   # 逐字符校验
s.add(p ^ key_byte == c)                         # XOR 密钥恢复（已知明密文）
s.add(3*a+5*b+7*c == 0x1234)                     # 模线性（BitVec 天然 mod 2^n）
opt = Optimize; opt.minimize(x)                # 最小/最大满足值
set_param("timeout", 5000)                       # unknown 时拆子问题
```

**求解器替代**: 位向量链 hash（bvxor/bvrol/bvadd）逆求解 Z3 爆慢时换 **boolector**（位向量类问题通常比 Z3 快 10-100 倍）。流程: lift 成 SMT2 + 可打印约束（`bvuge input #x20202020`/`bvule #x7e7e7e7e`）+ assert 目标 → `boolector -m --output-format=smt2 hash.smt2`。默认仍先 Z3（生态全），位级 hash 卡慢再切换。

**ILP 路线**: 输入字节是**线性**和差约束（`x[3]+x[7]==0xAB` 类，无位运算）时 ILP 专用求解器快于 Z3——PuLP `LpVariable(x_i, 32, 126, cat='Integer')` + `PULP_CBC_CMD` 求解; 约束经 GDB 断点逐比较提取，位置编码输入（input[i]=i）标定涉及位置。选型: 纯线性→PuLP，混合位运算→Z3，矩阵/乘法→格。

**布尔门网络 SAT（games-and-vms）**: keygen/注册码验证实现为门网络（AND/OR/XOR/NOT，百级门+百级输入 bit）时直接映射 Z3——输入 wire=Bool 变量，每门一表达式（And/Or/Xor/Not）写回 wires dict，`solver.add(wires[out]==True)` 全部要求真; 250 门 125 输入毫秒级解出。识别: product key/license/电路图/registration 验证逻辑可提取（二进制/抓包/规格）即建模 SAT。

## §7 Unicorn hook 追踪

```python
mu.hook_add(UC_HOOK_MEM_READ | UC_HOOK_MEM_WRITE, hook_mem)   # 读写观察
mu.hook_add(UC_HOOK_CODE, hook_code)   # 每指令回调+Capstone disasm → trace
```
用途: shellcode 脱壳（emulate 后 dump）/ 解密函数模拟 / 短密钥爆破循环 / 固件例程。syscall 未 hook 会崩。

## §7a Qiling OS 层模拟

Qiling = Unicorn（CPU）+ OS 层（syscall/文件系统/注册表），整程序模拟: `Qiling(["./bin"], "rootfs/x8664_linux").run`; Windows PE 免 Windows（rootfs/x86_windows）、ARM/MIPS 固件免硬件。

- **反调试天然绕过**: 模拟层无调试器痕迹; `ql.os.set_syscall("ptrace", hook)` 返回 0、`ql.hook_address(skip, addr)` 跳反 VM 检查; Windows API 级 `ql.set_api("IsDebuggerPresent", hook)` 返回 0
- **输入爆破**: verbose=DISABLED + stdin=候选 → `ql.os.stdout.read` 判输出; 快照/restore 支持回滚
- 选型: 反调试重/异架构/批量输入测试时优于 GDB/Frida; rootfs 取自 qilingframework/rootfs

## §8 关联文件

- `$SHARED_DIR/knowledge-base/unicorn-templates.md` — Unicorn 基础模板（IDA 集成）
- `$SHARED_DIR/knowledge-base/technology-selection.md` — 总选型
- crypto-analysis 的 Z3 密码学场景（PRNG/LCG）见 crypto-methodology §6a
