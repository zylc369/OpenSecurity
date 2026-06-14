# 需求：IDA 内置调试器动态分析能力

## 1. 背景与目标

### 1.1 来源

用户在 CRACKME3 复盘后的讨论中提出：IDA 自带调试器（`ida_dbg` 模块）和 Windows 调试 API 可以完成动态分析/脱壳，无需安装 Frida。

### 1.2 现状问题

| 问题 | 说明 |
|------|------|
| 当前动态分析完全依赖 Frida | `dynamic-analysis.md` 全部内容为 Frida 专用（JS API、Frida 版本适配等） |
| Frida 有安装门槛 | 需 `pip install frida frida-tools`，用户可能没装 |
| Frida 有反检测风险 | 部分壳检测 Frida 存在后拒绝解壳 |
| IDA 调试器被忽视 | IDA 自带 `ida_dbg` 模块，可直接在 idat headless 中使用，零额外依赖 |

### 1.3 目标

1. 新增 IDA 内置调试器作为动态分析**首选方案**（覆盖脱壳、断点追踪、算法验证）
2. Frida 降级为**后备方案**（IDA 调试器失败时使用）
3. 重构知识库文件结构，使通用动态分析与 Frida 专用内容分离

### 1.4 评估维度

| 维度 | 改进 |
|------|------|
| 减少上下文 | 不变（都是加载知识库） |
| 减少对话轮次 | 消除"Frida 未安装 → 安装 → 版本不兼容 → 换方案"的轮次 |
| 提升速度 | 省去 Frida 安装时间；IDA 调试器 dump 后数据已在 IDA 内，无需重新加载 |
| 提升准确度 | IDA 调试器使用标准 Windows debug API，不被反 Frida 检测 |

---

## 2. 技术方案

### 2.1 改动总览

| ID | 方案 | 改动文件 | 类型 |
|----|------|---------|------|
| A | 重命名 Frida 知识库文件 | `dynamic-analysis.md` → `dynamic-analysis-frida.md` | 重命名 |
| B | 新建通用动态分析知识库 | `dynamic-analysis.md`（新） | 新增（~80 行） |
| C | 新增 IDA 调试器 dump 脚本 | `scripts/debug_dump.py` | 新增（~200 行） |
| D | 更新 packer-handling.md 阶段 2.5.3 和 3.5 | `packer-handling.md` | 修改 |
| E | 更新主 prompt 动态分析触发描述 | `ida-pro-analysis.md` | 修改（+2 行） |

### 2.2 依赖关系

```
E（主 prompt 触发描述更新）
  └── 引用 B（新的 dynamic-analysis.md）

B（通用动态分析知识库）
  ├── 引用 C（debug_dump.py 脚本）
  └── 引用 A（dynamic-analysis-frida.md，作为后备方案）

D（packer-handling.md 更新）
  ├── 阶段 2.5.3：优先 IDA 调试器 dump → Frida → 静态分析
  └── 阶段 3.5：拆分为 3.5a（IDA 调试器）+ 3.5b（Frida）

C（debug_dump.py 脚本）
  └── 独立 IDAPython 脚本，在 idat headless 中运行
```

### 2.3 方案 A：重命名 Frida 知识库文件

将 `ida-pro-analysis-knowledge-base/dynamic-analysis.md` 重命名为 `dynamic-analysis-frida.md`。

文件内部标题从"动态分析策略（Frida）"改为"动态分析策略 — Frida 模式"。

### 2.4 方案 B：新建通用动态分析知识库

新建 `ida-pro-analysis-knowledge-base/dynamic-analysis.md`，内容为通用动态分析指引：

```markdown
# 动态分析策略

> AI 编排器在需要动态分析时通过 Read 工具按需加载。

## 触发条件

1. **动态脱壳**：阶段 2.5 定位到 OEP 后，需要 dump 解壳后的内存
2. **算法验证**：静态分析推导出算法后，需要用实际输入/输出对比验证
3. **运行时数据追踪**：需要追踪特定函数的参数、返回值、内存状态
4. **GUI 程序交互**：需要向 GUI 控件输入数据并读取结果

## 方案选择

| 方案 | 优先级 | 适用场景 | 前置条件 |
|------|--------|---------|---------|
| IDA 内置调试器 | **首选** | 本地可执行文件、脱壳、断点追踪、算法验证 | 无（IDA 自带） |
| Frida | 后备 | IDA 调试器失败（强反调试）、需要注入远程进程 | pip install frida |

**优先使用 IDA 内置调试器**。仅当 IDA 调试器不可用或失败时，才切换到 Frida：
- 读取 `$SCRIPTS_DIR/ida-pro-analysis-knowledge-base/dynamic-analysis-frida.md`

## IDA 内置调试器

### 核心优势

- 零额外依赖（IDA 自带调试器模块）
- dump 后数据直接在 IDA 内，无需重新加载
- 使用标准 OS 调试 API（Windows: Win32 Debug API, Linux: ptrace），不被反 Frida 检测
- 可在 idat headless 模式下运行（`idat -A -S<script>`）

### 核心 IDAPython 调试 API

| API | 用途 |
|-----|------|
| `ida_dbg.start_process()` | 启动调试（挂起在入口点） |
| `ida_dbg.set_breakpoint(ea)` | 设断点 |
| `ida_dbg.del_breakpoint(ea)` | 删断点 |
| `ida_dbg.resume_process()` | 继续运行 |
| `ida_dbg.suspend_process()` | 暂停 |
| `ida_dbg.step_into()` | 单步进入 |
| `ida_dbg.step_over()` | 单步跳过 |
| `ida_dbg.exit_process()` | 终止进程 |
| `ida_dbg.get_reg_val(name)` | 读寄存器（EIP/RIP/EAX/RAX 等） |
| `ida_dbg.set_reg_val(name, val)` | 写寄存器 |
| `ida_dbg.is_debug_on()` | 调试器是否激活 |

配合 `ida_bytes.get_bytes(ea, size)` 在断点命中时读取任意内存。

### 脱壳场景：debug_dump.py

项目内置 IDA 调试器脱壳脚本：`$SCRIPTS_DIR/scripts/debug_dump.py`

**使用方式**：
```bash
IDA_OEP_ADDR=0x401000 IDA_OUTPUT="$TASK_DIR/unpacked.exe" \
  "$IDAT" -A -S"$SCRIPTS_DIR/scripts/debug_dump.py" \
  -L"$TASK_DIR/debug_dump.log" "<目标文件>.i64"
```

**脚本功能**：
1. 读取 `IDA_OEP_ADDR` 环境变量获取 OEP 地址
2. 在 OEP 设断点
3. 启动 IDA 调试器，运行到断点
4. dump 所有段内存
5. 从 dump 数据重建 PE 文件（修正段表、入口点）
6. 写入 `IDA_OUTPUT` 指定路径
7. 终止调试进程并退出

**环境变量**：

| 变量 | 必填 | 说明 |
|------|------|------|
| `IDA_OEP_ADDR` | 是 | OEP 地址（十六进制，如 `0x401000`） |
| `IDA_OUTPUT` | 是 | 输出文件路径 |
| `IDA_DEBUG_TIMEOUT` | 否 | 等待断点超时（秒），默认 60 |

### 断点追踪场景

在已加载的 IDA 数据库中（非脱壳），通过 IDAPython 脚本设断点追踪：

1. **追踪函数参数**：在目标函数入口设断点，命中后读取参数寄存器（ECX/RCX、EDX/RDX 等）
2. **追踪返回值**：在函数出口设断点（`ret` 指令处），读取 EAX/RAX
3. **追踪内存写入**：在关键地址设硬件断点（`ida_dbg.set_bpt(ea, ida_dbg.BPT_WRITE)`）

通用追踪脚本模板：
```python
import ida_dbg
import ida_bytes

# 设断点
ida_dbg.set_breakpoint(target_addr)

# 启动调试
ida_dbg.start_process()

# 等待命中后读取数据
# reg_val = ida_dbg.get_reg_val("EAX")
# mem_data = ida_bytes.get_bytes(addr, size)
```

### GUI 程序交互（仅 Windows）

IDA 调试器启动程序后，GUI 窗口正常显示。分析者可：
1. 手动在 GUI 中输入数据（程序在断点处暂停时无法交互，需要 resume 后操作）
2. 通过 IDAPython 脚本调用 Win32 API 自动化：
   - `SetDlgItemTextA` 设置编辑框内容
   - `PostMessageA(WM_COMMAND)` 触发按钮点击
3. 设断点在目标函数，让程序运行到断点后读取状态

### 限制

- **反调试检测**：部分壳使用 `IsDebuggerPresent`、`NtQueryInformationProcess` 等检测调试器。遇到时切换到 Frida
- **仅限本地**：IDA 调试器只能调试本机进程
- **平台绑定**：Windows 调试器只能调试 Windows 程序，Linux 只能调试 Linux 程序
- **headless 限制**：idat headless 模式下，调试器事件循环可能需要手动驱动（`process_ui_actions()`）
```

### 2.5 方案 C：新增 debug_dump.py 脚本

**文件位置**：`$SCRIPTS_DIR/scripts/debug_dump.py`（沉淀脚本，注册到 registry.json）

**核心逻辑**：

```python
"""summary: IDA 调试器脱壳 dump 脚本

description:
  在 IDA 调试器中运行目标程序到 OEP 断点，dump 内存段并重建 PE 文件。
  适用于任何壳（UPX/ASPack/自定义壳），只要壳不检测调试器。

  使用方式（idat headless）：
    IDA_OEP_ADDR=0x401000 IDA_OUTPUT=/tmp/unpacked.exe \
      idat -A -S"scripts/debug_dump.py" -L/tmp/debug.log target.i64

  环境变量：
    IDA_OEP_ADDR: OEP 地址（十六进制，必填）
    IDA_OUTPUT: 输出文件路径（必填）
    IDA_DEBUG_TIMEOUT: 等待断点超时秒数（默认 60）

level: intermediate
"""

# 实现要点：
# 1. _main()：读取环境变量 → 设断点 → 启动调试 → 等待断点 → dump → 重建 PE → 退出
# 2. _wait_for_breakpoint(timeout)：轮询 ida_dbg.get_reg_val("EIP"/"RIP") 直到等于 OEP
# 3. _dump_segments()：遍历所有段，ida_bytes.get_bytes() 读取
# 4. _rebuild_pe(seg_data, oep)：从 image base 读 PE header，修正段表和入口点，写入文件
# 5. 使用 from _base import ... 复用基础设施（log、env_str、run_headless 等）
```

**PE 重建策略**：
1. 从 IDA 的 image base 读取 PE header（`ida_bytes.get_bytes()`）
2. 解析 section table，获取每个 section 的 VirtualAddress、VirtualSize
3. 用 dump 的段数据填充每个 section 的 raw data
4. 修正 `AddressOfEntryPoint` 为 OEP
5. 修正 section header 的 `SizeOfRawData` = VirtualSize（对齐到 FileAlignment）
6. 修正 `PointerToRawData` 为连续排列
7. 写入输出文件

### 2.6 方案 D：更新 packer-handling.md

#### 2.6.1 阶段 2.5.3 策略 2.5.3：动态 dump

替换现有内容为：

```markdown
### 策略 2.5.3：动态 dump

定位 OEP 后，使用动态方法 dump 解壳后的内存：

1. **首选 IDA 调试器 dump**：使用 `scripts/debug_dump.py`
   ```bash
   IDA_OEP_ADDR=0x401000 IDA_OUTPUT="$TASK_DIR/<文件名>_unpacked" \
     "$IDAT" -A -S"$SCRIPTS_DIR/scripts/debug_dump.py" \
     -L"$TASK_DIR/debug_dump.log" "<目标文件>.i64"
   ```
2. **IDA 调试器失败**（反调试 / 无法启动 / 超时）→ 尝试 Frida（`disassembler/frida_unpack.py`）
3. **Frida 也失败**（未安装 / 非 PE 格式 / 反 Frida）→ 回退到阶段 3（静态分析）
```

#### 2.6.2 阶段 3.5：拆分为 3.5a + 3.5b

替换现有"阶段 3.5：动态脱壳（Frida 进程 dump）"为：

```markdown
## 阶段 3.5：动态脱壳

### 阶段 3.5a：IDA 调试器 dump（首选）

使用 IDA 内置调试器运行到 OEP 并 dump 内存。详见 `dynamic-analysis.md` 中"脱壳场景：debug_dump.py"。

**优势**：零额外依赖；dump 后数据在 IDA 内；不被反 Frida 检测

**使用 debug_dump.py**：
```bash
IDA_OEP_ADDR=<OEP地址> IDA_OUTPUT="$TASK_DIR/<文件名>_unpacked" \
  "$IDAT" -A -S"$SCRIPTS_DIR/scripts/debug_dump.py" \
  -L"$TASK_DIR/debug_dump.log" "<目标文件>.i64"
```

**验证输出**：
- 输出文件存在且非空
- `file` 命令显示合法可执行文件格式

### 阶段 3.5b：Frida 进程 dump（后备）

IDA 调试器失败时使用 Frida。详见 `dynamic-analysis-frida.md`。

项目内置 Frida PE 脱壳脚本：`disassembler/frida_unpack.py`
```bash
python disassembler/frida_unpack.py <目标二进制> -o "$TASK_DIR/<文件名>_unpacked" -w 30
```

### 前置条件

- IDA 调试器：无额外依赖（IDA 自带）
- Frida：`pip install frida frida-tools`（仅在使用 3.5b 时需要）
```

### 2.7 方案 E：更新主 prompt

在 `ida-pro-analysis.md` 的"动态分析触发"小节（第 217-218 行）替换为：

```markdown
**动态分析触发**（需要运行时验证/调试时）：
  读取 `$SCRIPTS_DIR/ida-pro-analysis-knowledge-base/dynamic-analysis.md`（含 IDA 调试器首选 + Frida 后备）
```

增加 1 行提示：

```markdown
**IDA 调试器触发**（脱壳后需要 dump 内存时）：
  使用沉淀脚本 `scripts/debug_dump.py`（通过 `IDA_OEP_ADDR` + `IDA_OUTPUT` 环境变量调用）
```

---

## 3. 实现规范

### 3.1 改动范围表

| 文件 | 改动类型 | 行数变化 | 影响范围 |
|------|---------|---------|---------|
| `dynamic-analysis.md` | 重命名为 `dynamic-analysis-frida.md` + 更新标题 | 0（内容不变） | 知识库文件名变更 |
| `dynamic-analysis.md`（新） | 新增 | ~80 行 | 通用动态分析知识库 |
| `scripts/debug_dump.py` | 新增 | ~200 行 | 沉淀脚本 |
| `scripts/registry.json` | 修改 | +10 行 | 注册新脚本 |
| `packer-handling.md` | 修改 | +30/-20 行 | 阶段 2.5.3 + 阶段 3.5 |
| `ida-pro-analysis.md` | 修改 | +2 行 | 动态分析触发描述 |

### 3.2 不修改的文件

- `_base.py`、`_utils.py`、`query.py`、`update.py` — 无变更
- `crypto-validation-patterns.md`、`script-generation.md` — 无变更
- `disassembler/frida_unpack.py` — 无变更

### 3.3 编码规则

- `scripts/debug_dump.py` 遵循 IDAPython 编码规范（`import ida_xxx`、双引号、中文日志）
- 使用 `from _base import ...` 复用基础设施
- PE 重建逻辑使用 `struct` 模块（标准库），不依赖第三方包
- 知识库 .md 文件必须自包含

---

## 4. 验收标准

### 4.1 功能验收

- [ ] A: `dynamic-analysis-frida.md` 为原 Frida 文件重命名，内容不变
- [ ] B: 新 `dynamic-analysis.md` 包含 IDA 调试器首选策略 + Frida 后备引用
- [ ] B: IDA 调试器章节覆盖：核心 API 表、脱壳场景、断点追踪场景、GUI 交互、限制
- [ ] C: `scripts/debug_dump.py` 可在 idat headless 中运行
- [ ] C: 脚本读取 `IDA_OEP_ADDR` + `IDA_OUTPUT` 环境变量
- [ ] C: 脚本输出重建后的 PE 文件
- [ ] C: 脚本注册到 `scripts/registry.json`
- [ ] D: `packer-handling.md` 阶段 2.5.3 优先 IDA 调试器
- [ ] D: 阶段 3.5 拆分为 3.5a（IDA）+ 3.5b（Frida）
- [ ] E: 主 prompt 包含 IDA 调试器触发描述

### 4.2 回归验收

- [ ] Frida 分析流程不受影响（`dynamic-analysis-frida.md` 内容不变）
- [ ] 非动态分析场景不受影响
- [ ] packer-handling.md 阶段 3（静态分析）内容不变
- [ ] 主 prompt 总行数 ≤ 520（当前 509 + 2 = 511）

### 4.3 架构验收

- [ ] 依赖方向合规：主 prompt → 知识库 → 脚本（单向）
- [ ] `debug_dump.py` 使用 `from _base import ...`，不反向依赖
- [ ] 知识库文件自包含
- [ ] registry.json 注册信息完整

---

## 5. 与现有文档的关系

| 现有文档 | 关系 |
|---------|------|
| [需求-逆向分析关键点优先策略](需求-逆向分析关键点优先策略.md) | 本次需求是其后续进化：阶段 2.5 定位 OEP 后，用 IDA 调试器 dump 而非 Frida |
| [需求-动态分析能力与脱壳流程增强](需求-动态分析能力与脱壳流程增强.md) | 本次需求增强其产出的 `dynamic-analysis.md`，从 Frida 专用改为通用方案 |
| [需求-加壳二进制静态分析脱壳流程](需求-加壳二进制静态分析脱壳流程.md) | 阶段 3 的定位不变（后备），本次增强阶段 2.5.3 和 3.5 |

---

## 6. 不做的事

1. **不删除 Frida 支持** — Frida 有独特优势（远程注入、不需要 IDA 环境），保留为后备
2. **不在 debug_dump.py 中实现反反调试** — 超出脚本职责范围，遇到反调试时切换到 Frida 或告知用户
3. **不支持 ELF/Mach-O dump** — 首版仅支持 PE 格式。ELF/Mach-O 需要不同的重建逻辑，后续按需扩展
