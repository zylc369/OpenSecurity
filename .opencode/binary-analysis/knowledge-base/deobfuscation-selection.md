# 反混淆技术选型 — 识别特征与首选工具链

> 遇到代码混淆（OLLVM/MBA/VM/Tigress）时通过 Read 工具加载。
> 加壳处理见 `$SHARED_DIR/knowledge-base/packer-handling.md`（本文件不含加壳）。

## 触发条件

- IDA 反编译结果包含大量无效逻辑/不可读代码/巨型 switch
- 或已知二进制使用了 OLLVM / Tigress / VMProtect（代码段）/ 自定义 VM

## §1 混淆类型识别 + 工具决策表

| 混淆类型 | 识别特征 | 首选工具 | 回退方案 |
|---------|---------|---------|---------|
| OLLVM 指令替换 | 简单运算被展开成复杂等价表达式（如 `a+b` → 多次 xor/and/sub） | **z3 simplify**（表达式等价化简） | — |
| OLLVM 虚假控制流 (BCF) | 大量永真/永假条件的分支（`x*(x-1)%2==0`） | **IDAPython 识别永真分支 + patch NOP** | — |
| 控制流平坦化 (CFF) | 一个大 `switch(state_var)` 调度器，真实块散落各 case | **deflat.py**（静态 patch）或 angr 符号重建 | IDAPython trace 状态变量取值序列 |
| MBA（混合布尔算术） | 大量 `^` `&` `\|` 混 `+` `-` 的表达式 | **z3 simplify** | QSynth 离线合成 |
| VM 混淆（虚拟化） | dispatcher 循环 + handler 表 + 字节码数据段 | **Triton + QSynth**（符号去虚拟化） | Unicorn 逐 handler 提语义 |
| Tigress | 学术混淆器，多种 pass 组合 | angr（按具体 pass 处理） | — |
| 反调试/CRC 校验 | ptrace/rdtsc/TracerPid 检测 + 完整性校验 | Frida hook（返假）/ patch 检测函数（全谱系见 anti-debugging-bypass.md） | IDA 条件断点改返回值 |
| 无混淆纯逻辑 | 反编译可读 | 反编译直读 / angr 反向求解 | — |
| 自定义密码 | 高熵查找表 / S-box / 魔数常量 | FindCrypt/Signsrch 识别 + Unicorn 建表 | angr 反向爆破 |
| 自修改代码 (SMC) | `.text` 段运行时被解密/改写；静态看是加密/乱码块，含写代码区的 XOR/解密循环 | **动态 dump 解密后 .text** | Unicorn 模拟解密 routine |
| obfusheader.h（编译期混淆） | constexpr/模板元编程: OBFUSCATE 宏字符串加密（key 立即数在密文旁）+ switch 分发表 + 无壳无反调试 | **静态直析: 提 key 解 XOR / Ghidra 反编译（比 Hex-Rays 处理平坦化好）** | angr 消不透明谓词 / Frida hook strlen 抓解密串 |
| movfuscator | 函数只含 mov 指令（无 add/jmp/call）+ 数据段大查找表 + 无 dispatcher | **demovfuscator 工具** | Pin/DynamoRIO trace+taint / 符号执行整函数求解 |
| 不透明谓词（孤立型） | 恒真/恒假条件四族: 算术 x²≥0 / 数论 x*(x+1)%2==0 / 指针别名 / 哈希常量 | **Z3 证明谓词否定 unsat → 删分支**（见 §8） | 抽象解释 / 模式匹配 / 动态 trace |
| 垃圾代码 (junk code) | 写后不读的寄存器/无副作用被弃调用的函数/不变边界循环算无用值 | **def-use 链标死码清除**（见 §8） | trace 比对验证 |
| 字符串加密 | 全部字符串不可读; 含 XOR 循环/栈字符串逐字节 mov/RC4 blob/多层编码链 | **hook 解密函数出口或 Unicorn 模拟**（五模式恢复表见 §9） | 提取 key 离线解密 |
| 导入表隐藏 | IAT 为空但明显调用 API + 比较 32 位哈希常量 + 无 GetProcAddress 字符串 | **识别哈希算法→建 hash→API 名查找表→批注**（见 §9） | trace GetProcAddress 等价调用 |
| 反反汇编 | 函数重叠/指令错位/`jz $+5; jnz $+3` 条件对/push+ret 当跳转 | **U/C 键在正确偏移重分析**（六技巧见 §10） | Edit→Patch→Assemble 永久修复 |

## §2 控制流平坦化 (CFF) 还原

### 识别
```
特征: 一个主循环内嵌大 switch(state_var)
  while(true) { switch(state) { case 0x12345: ...; state=0x67890; ... } }
```
state_var 的取值序列即真实执行顺序。

### 方法 1：deflat.py（静态 patch）
定位 dispatcher 主循环、识别真实块/虚假块，把分发跳转 patch 成直接跳转。
- 适用：标准 OLLVM -fla
- 局限：需识别 main_b/true_b/ret_b 块

### 方法 2：angr 符号重建
```python
import angr
proj = angr.Project('./binary', auto_load_libs=False)
cfg = proj.analyses.CFGEmulated()
# 符号执行跟踪 state_var 取值序列
state = proj.factory.entry_state()
simgr = proj.factory.simulation_manager(state)
simgr.explore(find=目标地址, avoid=[失败分支])
# 重建 CFG
```
- 防爆炸：`LAZY_SOLVES=True` + 限 active stash + `SimProcedure` hook 库函数

### 方法 3：D-810（IDA 插件）
OLLVM 风格 CFF 自动去平坦化专用（规则驱动，对指令替换/MBA 也有规则集），与 deflat.py 互补——deflat.py 需人工识别 main_b/true_b/ret_b 块类型，D-810 自动化程度更高。

## §3 VM 去虚拟化

### 识别
```
特征: 
  - dispatcher 循环（读字节码 → 查 handler 表 → 跳转）
  - 大量连续的 handler 函数（每个对应一条虚拟指令）
  - 数据段中不可读的字节码序列
```

### 方法 1：Triton + QSynth（符号去虚拟化）

**Triton vs angr 选型**: Triton=concrete 驱动 DSE（喂具体 trace、只符号化关键输入、比较点 getPathConstraintsAst 求解）——单路径快、不易路径爆炸，线性代码/去污点优先; angr=全符号多路径探索。Miasm 同类 IR 框架（IR 提升+表达式化简）作替代。
```
步骤:
  1. 定位 VM entry / dispatch loop / handler 表
  2. 用 Triton 符号执行每个 handler，提取语义（输入→输出的符号关系）
  3. QSynth 对目标字节码做 BFS 搜索，合成等价的原始指令
  4. 差分测试验证合成结果
```

### 方法 2：Unicorn 逐 handler 提语义
```
步骤:
  1. 从 IDA 导出每个 handler 的字节码
  2. Unicorn 映射 + 批量灌入不同输入，记录输出 → 建语义表
  3. 对目标字节码逐条查表翻译回原始操作
```

## §4 MBA（混合布尔算术）化简

### 识别
表达式包含大量布尔运算（`^` `&` `|`）混合算术（`+` `-` `*`），如：
```
x + y = (x ^ y) + 2 * (x & y)   // 被 OLLVM 展开成这种形式
```

### 化简
- **z3**：`z3.simplify(expr)` 对简单 MBA 有效
- **QSynth**：复杂 MBA 用程序合成离线化简
- **SiMBA**：`pip install simba-simplifier` 表达式级批量化简; **Arybo**（ANF 转换）; **D-810**（IDA，规则驱动）/**GOOMBA**（Ghidra）自动去混淆

常用恒等式速查:
```
(x & y) + (x | y)   == x + y
(x ^ y) + 2*(x & y) == x + y
(x | y) - (x & ~y)  == y
~(~x & ~y)          == x | y
(x | y) & ~(x & y)  == x ^ y
```

## §5 Go/Rust 符号恢复

### Go（strip 后仍可恢复）
```bash
# GoReSym 恢复 pclntab/moduledata 中的符号信息
GoReSym -t -d -p -strings <binary> > symbols.json
# stripped 二进制自动检测版本会失败 → 需显式指定 -v <version>（如 -v 1.20），否则类型解析直接失败
# pclntab 布局版本 ≤ runtime 版本（pre-1.2/1.2/1.16/1.18/1.20/1.24），moduledata 类型解析需 Go ≥ 1.5
# 然后用 IDAPython 脚本导入（IDAPython/goresym_rename.py）
```
- IDA 9.0+ 内置 Golang FLIRT（1.10-1.23）自动识别
- pclntab 被 UPX/魔改时，GoReSym 基于 `runtime_modulesinit` 签名扫描修复

### Rust
- IDA 9.0+ 内置 Rust FLIRT（1.77-1.81）
- 关键：demangle + 识别 panic/Option/Result 模式

## §6 自修改代码 (SMC)

### 识别
- 静态：`.text` 段含大块高熵/加密数据；存在解密循环（XOR/ADD/查表）且**写目标在 `.text` 段**；写完后跳转执行该区域
- 反汇编在加密区显示乱码/无效指令；运行后才显真实指令
- 常配套反调试（防运行时 dump）

### 方法 1：动态 dump（首选）
解密完成、真实代码执行前下断，dump `.text` 段：
1. 在解密循环结束处（通常是 `jmp`/`call` 到解密目标）下断
2. 运行到断点，dump 目标区内存
3. IDAPython 把 dump 的 bytes 写回 IDB 并重新分析：
```python
import idaapi
data = idaapi.get_bytes(ea, size)   # 运行时读解密后的字节（调试态）
# 或从外部 dump 文件读
idaapi.patch_bytes(ea, data)        # 写回 IDB
idaapi.auto_wait()                  # 重新分析
```

### 方法 2：Unicorn 模拟解密（无法动态跑时）
反调试强或环境缺失时，用 Unicorn 离线模拟解密 routine：
1. 提取解密函数代码 + 加密的 `.text` 数据段
2. Unicorn 映射内存，把加密数据和 key 载入，执行解密 routine
3. 从映射的 `.text` 区读出解密后 bytes，再静态分析
- 模拟执行模板见 `$SHARED_DIR/knowledge-base/unicorn-templates.md`

### 方法 3：静态分析解密算法（解密简单时）
解密是单字节 XOR / 固定 key / 简单变换时，离线逆运算：
1. 识别 key 与运算（从解密循环反编译）
2. IDAPython 对加密区应用逆运算后 `patch_bytes` 写回

### 检查清单

## §6a 指令计数侧信道——Pin inscount0

序列校验（逐字符比较、正确执行更深）的混淆二进制用 Pin 计总指令数当 oracle，逐字符贪心选指令数最大者（正确字符 ≈1000+ 条指令差）。movfuscator 产物适用（全 mov 静态不可读，比较深度仍可测——§1 表 movfuscator 行 Pin 路线的轻量形态）。

贪心失效场景（自修改逐段解密/字符相互作用）→ **遗传算法**: fitness=指令数（正确性单调升则计数单调升）、种群 100/幸存 20/变异率 0.1，40 字符约 30 分钟收敛（经验值）——GA 同时发现多个正确字符快于逐字符。

**计数失相关（表查找比较）→ 改计目标地址**: 重写 Pin inscount 的 INS_InsertCall 回调只计 success 分支地址执行次数（`if (ip == target_addr) target_count++`，IARG_INST_PTR），对该定向计数逐字符爆破。

与时间侧信道（pwn-methodology §4 时间盲族）同族，指令计数是精确度量免噪声。
- `.text` 段是否有写操作（非只读，违反 W^X）
- 解密 routine 的入口/出口（确定 dump 时机：解密完成、执行前）
- 是否多层解密（逐层 dump，每层解密后再找下一层）
- **输入即密钥变体**: 解密循环 key 来自输入缓冲（非常量）——每个输入字符解密下一代码块。破解: 块首已知 opcode（函数序言 `55` push rbp / `f3 0f 1e fa` endbr64）当已知明文 XOR 恢复 key=输入字符，逐块推进。自 dump 场景（程序读 /proc/self/mem）用 8 字节序言 `f3 0f 1e fa 55 48 89 e5` 恢复 XOR key

---

## §8 不透明谓词与垃圾代码

不透明谓词四族（恒真/恒假但不可直观看出）: 算术 `x² ≥ 0` / 数论 `x*(x+1) % 2 == 0`（连续整数积必偶）/ 指针别名 `ptr == ptr` / 哈希 `CRC32(常量) == 已知值`。

Z3 证明消除（谓词否定 unsat → 分支可删）:
```python
import z3
x = z3.BitVec('x', 32)
s = z3.Solver()
s.add(x * (x + 1) % 2 != 0)
print(s.check())   # unsat → 原谓词恒真
```

垃圾代码三特征: ①写后不读的寄存器/内存 ②返回值被弃且无副作用的调用 ③不变边界循环算无用结果。清除走 def-use 链标死码，删后 trace 比对验证。OLLVM BCF = 不透明谓词 + 垃圾块组合。

## §9 字符串加密五模式 + 导入表隐藏

| 字符串模式 | 形态 | 恢复 |
|---|---|---|
| XOR 循环 | 运行时 `s[i] ^= key` | hook/Unicorn 模拟，出口取明文 |
| 栈字符串 | `mov [esp+0],'H'; mov [esp+1],'e'` 逐字节 | 脚本按 esp 偏移序拼接 |
| RC4 blob | 加密块+内置 key | 提 key 离线解 |
| AES blob | 运行时派生 key | hook 派生后出口 |
| 编码链 | Base64+XOR+reverse 多层 | trace 解码函数 Python 复现 |

Ghidra 批注: getReferencesTo(decrypt_func) 遍历调用点 → 提参数模拟解密 → 明文写注释。

导入表隐藏恢复四步: ①识别哈希算法（移位 13/19=ROR13、*33=djb2、*0x01000193=FNV-1a、标准 CRC32）②算全部已知 API 名哈希 ③建 hash→API 查找表 ④IDA/Ghidra 批注调用点。原理: 运行时 walk PEB→LDR→InMemoryOrderModuleList 对导出名算哈希比对（IAT 为空 + 比较 32 位哈希常量 + 无 GetProcAddress 字符串 = 识别特征）。ROR13 为 Metasploit shellcode 标准，FNV-1a 现代恶意软件常用。在线速查: hashdb.openanalysis.net（哈希常数→API 名反查）; ShellcodeHasher 批量比对已知 Windows API。

## §10 反反汇编六技巧

| 技巧 | 机制 | 修复 |
|---|---|---|
| 重叠指令 | `jmp $+2; db 0xE8`（落在假 call 前缀中间） | 正确偏移 U 后 C 重分析 |
| 错位跳转 | 跳进多字节指令内部偏移 | 目标地址强制重定义代码 |
| 条件跳转对 | `jz $+5; jnz $+3`（互补恒跳，骗线性扫描） | patch 无条件 jmp |
| push+ret 当跳转 | `push addr; ret` 替代 jmp | 人工识别 |
| call+add [esp] | `call $+5; add [esp],N; ret` 计算跳转 | 手算目标 = call 下一条 + N |
| 异常流 | 真实代码在异常 handler 中 | 分析 VEH/SEH 链 |

IDA 操作: U（Undefine）→ 正确偏移 C（Code）→ Edit→Patch→Assemble 永久修复。异常流与反调试异常族（anti-debugging-bypass.md §3）同根。

---

## §7 关联文件

- `$SHARED_DIR/knowledge-base/packer-handling.md` — 加壳/脱壳处理（本文件不含加壳）
- `$SHARED_DIR/knowledge-base/unicorn-templates.md` — Unicorn 批量模拟模板
- `$SHARED_DIR/knowledge-base/crypto-validation-patterns.md` — 自定义密码识别
- `$SHARED_DIR/knowledge-base/idapython-conventions.md` — IDAPython 编码规范
