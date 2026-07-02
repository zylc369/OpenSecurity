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
| 反调试/CRC 校验 | ptrace/rdtsc/TracerPid 检测 + 完整性校验 | Frida hook（返假）/ patch 检测函数 | IDA 条件断点改返回值 |
| 无混淆纯逻辑 | 反编译可读 | 反编译直读 / angr 反向求解 | — |
| 自定义密码 | 高熵查找表 / S-box / 魔数常量 | FindCrypt/Signsrch 识别 + Unicorn 建表 | angr 反向爆破 |
| 自修改代码 (SMC) | `.text` 段运行时被解密/改写；静态看是加密/乱码块，含写代码区的 XOR/解密循环 | **动态 dump 解密后 .text** | Unicorn 模拟解密 routine |

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

## §3 VM 去虚拟化

### 识别
```
特征: 
  - dispatcher 循环（读字节码 → 查 handler 表 → 跳转）
  - 大量连续的 handler 函数（每个对应一条虚拟指令）
  - 数据段中不可读的字节码序列
```

### 方法 1：Triton + QSynth（符号去虚拟化）
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
- `.text` 段是否有写操作（非只读，违反 W^X）
- 解密 routine 的入口/出口（确定 dump 时机：解密完成、执行前）
- 是否多层解密（逐层 dump，每层解密后再找下一层）

---

## §7 关联文件

- `$SHARED_DIR/knowledge-base/packer-handling.md` — 加壳/脱壳处理（本文件不含加壳）
- `$SHARED_DIR/knowledge-base/unicorn-templates.md` — Unicorn 批量模拟模板
- `$SHARED_DIR/knowledge-base/crypto-validation-patterns.md` — 自定义密码识别
- `$SHARED_DIR/knowledge-base/idapython-conventions.md` — IDAPython 编码规范
