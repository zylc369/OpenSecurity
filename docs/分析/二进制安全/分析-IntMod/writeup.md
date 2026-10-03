# IntMod 解题报告 (Writeup)

> SunshineCTF 2026 · Reverse · Author: Bradley Fernandez
> FLAG: `sun{I_L0v3_Int3rrupts&SelfMod!!!}` (真机验证输出 Correct)

## 题目

"IntMod?? Do you mean integer modulus??" — 不是整数取模，是 **Int**errupt + **Mod**ification（中断与自修改代码）。

## 程序架构（静态分析）

ELF x64 stripped，导入表极简（`sigaction/sigaltstack/mmap/fgetc/...`）：

```
main: 读 33 字节输入 → state(v19, 128B: 输入5块×u64 + PC/hash16/expected/version 的 vmctx)
  → 模块解析(kind=1, data=0x4055C0, size=203块×64B, hash16, expected8)
  → JIT 容器(RWX mmap 16B 槽) → 信号注册(SIGTRAP/SIGILL/SIGFPE, SA_SIGINFO|SA_ONSTACK)
  → 主循环: 按 mode 触发 int3/ud2/div0 → handler(sub_4037A0) 解码执行 VM 指令
  → PC==203 正常退出 → state+72==0 → "Correct"
```

## VM 机制（三层混淆）

1. **信号驱动**：主循环按 mode 轮流触发 int3/ud2/div0，handler 作为 VM dispatcher
2. **JIT 槽自修改**：handler 生成 `mov r15,r10 / and / or / sub...` 3 字节真 x86 指令写入 RWX 槽，**置 EFLAGS.TF 单步**，每条指令触发 SIGTRAP（"指令执行" = TF 单步 + 槽重写循环）
3. **状态化指令解密**：模块 203×64B 块，每块 **XTEA**（key=vmctx 的 hash16）+ wyhash 种子（f(PC, hash16, expected)）解密，magic="ITM6"+块号自校验；hash16/expected 被每条指令更新 → **解密依赖运行时状态**

## VM ISA（sub_400AE0，8 opcodes）

| op | 语义 |
|----|------|
| 0-4 | `reg[d] += ^= *=imm ROL / swap`（reg0-4 = R8-R12 = 输入 5 块）|
| 5 | `hash40(regs, salt) - target (mod 65521)` → 差值存 hashreg |
| 6 | `R14 |= imm ^ hashreg`（**校验置位**，全过 ⟺ diff==imm 每组）|
| 7 | nop |

程序结构：**18 轮 × 5 op 混合**（90 条，全可逆）+ **40 组校验**（作用于同一混合后 40 字节）。

## 求解流程

1. **动态观测**（Docker 原生 + LD_PRELOAD 信号包装器）：包装 sigaction 捕获 handler，dump 每 trap 的全 gregs/槽内容/vmctx(44B)——250 trap 全量 ground truth
2. **指令解码**（Unicorn 单函数调用 sub_4020E0 × 250，逐条用真实 vmctx）：250/250 解码成功，Python VM 模拟与真机终态**完全校准**
3. **代数求解**（核心弱点：哈希是 mod 65521 线性）：
   - 40 组校验 → 40×40 线性方程组（mod 65521）→ 高斯消元唯一解 X（40 字节全部 ≤255 = 正确性强信号）
   - X 逆推 18 轮混合链（mul 奇常数用模 2⁶⁴ 逆元，add→sub，rol→ror，swap/xor 自逆）
   - 逆推结果尾部 = `0x07×7` padding 完美匹配 → 输入即 flag

## 关键踩坑

- Unicorn 全模拟不可行（TF 不触发 + SMC 页 TB 不续 + until 语义）→ LD_PRELOAD 原生环境是正解
- Z3 直接解 264bit×40 约束 unknown → 线性代数秒解
- hash 递推权重方向（`r^i` 非 `r^(39-i)`）搞反会解出寄存器镜像序——用已知输入代入方程 40/40 自检定位

## 工具产物（$TASK_DIR）

`traplog.c`（信号包装器）· `decode_all.py`（Unicorn 解码）· `solve_intmod.py`（Python VM 校准）· `algebra_solve.py`（线性求解+逆推）

## 复现

```bash
echo 'sun{I_L0v3_Int3rrupts&SelfMod!!!}' | ./intmod   # → Correct
```
