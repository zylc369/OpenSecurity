# 反混淆技术选型 — 识别特征与首选工具链

> 遇到代码混淆（OLLVM/MBA/VM/Tigress）时通过 Read 工具加载。
> 加壳处理见 `$SHARED_DIR/knowledge-base/packer-handling.md`（本文件不含加壳）。

## 触发条件

- IDA 反编译结果包含大量无效逻辑/不可读代码/巨型 switch
- 或已知二进制使用了 OLLVM / Tigress / VMProtect（代码段）/ 自定义 VM

## §1 混淆类型识别 + 工具决策表

| 混淆类型 | 识别特征 | 首选工具 | 回退方案 |
|---------|---------|---------|---------|
| OLLVM 指令替换 | 简单运算被展开成复杂等价表达式（如 `a+b` → 多次 xor/and/sub） | **D-810**（F5 自动化简） | z3 simplify |
| OLLVM 虚假控制流 (BCF) | 大量永真/永假条件的分支（`x*(x-1)%2==0`） | **D-810** | 手动 patch 永真分支 |
| 控制流平坦化 (CFF) | 一个大 `switch(state_var)` 调度器，真实块散落各 case | **deflat.py**（静态 patch）或 angr 符号重建 | 手动 trace 状态变量取值序列 |
| MBA（混合布尔算术） | 大量 `^` `&` `\|` 混 `+` `-` 的表达式 | **D-810** 内置规则 / z3 simplify | QSynth 离线合成 |
| VM 混淆（虚拟化） | dispatcher 循环 + handler 表 + 字节码数据段 | **Triton + QSynth**（符号去虚拟化） | Unicorn 逐 handler 提语义 |
| Tigress | 学术混淆器，多种 pass 组合 | D-810（部分）+ angr | 按具体 pass 对照处理 |
| 反调试/CRC 校验 | ptrace/rdtsc/TracerPid 检测 + 完整性校验 | Frida hook（返假）/ patch 检测函数 | IDA 条件断点改返回值 |
| 无混淆纯逻辑 | 反编译可读 | 反编译直读 / angr 反向求解 | — |
| 自定义密码 | 高熵查找表 / S-box / 魔数常量 | FindCrypt/Signsrch 识别 + Unicorn 建表 | angr 反向爆破 |

## §2 D-810（Hex-Rays microcode 层反混淆）

> D-810 在 Hex-Rays 把汇编提升到 microcode、再降到 ctree 的**中间阶段**注册改写规则，把混淆等价变换掉。比改汇编/patch 更安全、可复用。

### 安装
```bash
# 1. 复制到 IDA 插件目录
cp -r d810 ~/.idapro/plugins/   # 或 IDA 安装目录的 plugins/

# 2. 安装 Z3（D-810 多个规则依赖）
pip3 install z3-solver
```
- 要求 IDA ≥ 7.5 + Python ≥ 3.7（需 microcode Python API）

### 使用步骤
1. F5 确认混淆存在（反编译结果包含上述识别特征）
2. `Ctrl-Shift-D` 打开 D-810 配置 GUI
3. 选择配置文件：不确定时用 `default_instruction_only.json`
4. 点 `Start` 启用反混淆
5. 重新 F5 → 伪代码应被简化
6. 用完点 `Stop` 关闭

### 支持的混淆
- OLLVM：指令替换、虚假控制流 (BCF)
- MBA：混合布尔算术化简
- 部分商业混淆

### ⚠ 注意
- 修改 microcode **可能导致 IDA 崩溃** → **频繁保存数据库**（Ctrl+W）
- 误改会破坏反编译结果 → 对比 Start/Stop 前后的输出
- 仅在 Linux 上测试过（Windows 应该也能用）

## §3 控制流平坦化 (CFF) 还原

### 识别
```
特征: 一个主循环内嵌大 switch(state_var)
  while(true) { switch(state) { case 0x12345: ...; state=0x67890; ... } }
```
state_var 的取值序列即真实执行顺序。

### 方法 1：deflat.py（静态 patch）
定位 dispatcher 主循环、识别真实块/虚假块，把分发跳转 patch 成直接跳转。
- 适用：标准 OLLVM -fla
- 局限：需手动定位 main_b/true_b/ret_b 块

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

## §4 VM 去虚拟化

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

### 方法 2：Unicorn 逐 handler 提语义（手动）
```
步骤:
  1. 从 IDA 导出每个 handler 的字节码
  2. Unicorn 映射 + 批量灌入不同输入，记录输出 → 建语义表
  3. 对目标字节码逐条查表翻译回原始操作
```

## §5 MBA（混合布尔算术）化简

### 识别
表达式包含大量布尔运算（`^` `&` `|`）混合算术（`+` `-` `*`），如：
```
x + y = (x ^ y) + 2 * (x & y)   // 被 OLLVM 展开成这种形式
```

### 化简
- **D-810**：内置 MBA 规则，F5 时自动化简（首选）
- **z3**：`z3.simplify(expr)` 对简单 MBA 有效
- **QSynth**：复杂 MBA 用程序合成离线化简

## §6 Go/Rust 符号恢复

### Go（strip 后仍可恢复）
```bash
# GoReSym 恢复 pclntab/moduledata 中的符号信息
GoReSym -t -d -p -strings <binary> > symbols.json
# 然后用 IDAPython 脚本导入（goresym_rename.py）
```
- IDA 9.0+ 内置 Golang FLIRT（1.10-1.23）自动识别
- pclntab 被 UPX/魔改时，GoReSym 基于 `runtime_modulesinit` 签名扫描修复

### Rust
- IDA 9.0+ 内置 Rust FLIRT（1.77-1.81）
- 关键：demangle + 识别 panic/Option/Result 模式

## §7 工具速查

| 工具 | 用途 | 安装 |
|------|------|------|
| D-810 | microcode 层反混淆 | `git clone https://gitlab.com/eshard/d810 ~/.idapro/plugins/d810` + `pip3 install z3-solver` |
| HexRaysDeob | D-810 前身 | `github.com/RolfRolles/HexRaysDeob` |
| GoReSym | Go 符号恢复 | `github.com/mandiant/GoReSym` |
| angr | 符号执行/去平坦化 | `pip install angr` | — |
| Triton + QSynth | VM 去虚拟化 | `pip install triton` + `github.com/quarkslab/qsynthesis` | — |
| Unicorn | 批量模拟 | `pip install unicorn` | `$SHARED_DIR/knowledge-base/unicorn-templates.md` |

## §8 关联文件

- `$SHARED_DIR/knowledge-base/packer-handling.md` — 加壳/脱壳处理（本文件不含加壳）
- `$SHARED_DIR/knowledge-base/unicorn-templates.md` — Unicorn 批量模拟模板
- `$SHARED_DIR/knowledge-base/crypto-validation-patterns.md` — 自定义密码识别
- `$SHARED_DIR/knowledge-base/idapython-conventions.md` — IDAPython 编码规范（含 IDA 9.0 API 变化）
