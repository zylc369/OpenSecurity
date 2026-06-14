# 需求：debug_dump.py 三个致命 Bug 修复

## 1. 背景与目标

### 1.1 来源

复盘 CRACKME3（UPX 加壳）分析过程（11 次 idat 调用、3 个手写临时脚本、7 次失败/重试），发现 `debug_dump.py` 存在 3 个致命 bug，导致脚本完全无法工作。AI 被迫手写临时脚本绕过，浪费约 40 分钟。

### 1.2 Bug 列表

| Bug | 位置 | 症状 | 根因 |
|-----|------|------|------|
| A | `_dump_segments()` L60-62 | `AttributeError: NoneType has no attribute 'start_ea'` | 调试器模式下 IDA 段数据库未初始化，`ida_segment.get_first_seg()` 返回 `None`，直接访问 `.start_ea` 崩溃 |
| B | `_main()` L238 | "无效 DOS header" — `image_base = 0` | `ida_ida.inf_get_baseaddr()` 在调试器模式下返回 0，后续读取 MZ 签名在地址 0 处失败 |
| C | `run_headless()` JSON 输出 | PE dump 文件被覆盖为 JSON | `_base.py` 的 `run_headless()` 将 JSON 结果写入 `IDA_OUTPUT` 环境变量指向的路径，但 `IDA_OUTPUT` 同时也用于 PE dump 输出，导致 PE 文件被 JSON 覆盖 |

### 1.3 目标

修复全部 3 个 bug，使 `debug_dump.py` 在调试器模式下能正确 dump 内存段并重建 PE 文件。

### 1.4 评估维度

| 维度 | 改进 |
|------|------|
| 减少上下文 | 消除手写临时脚本的需要（~500 行临时代码 → 0） |
| 减少对话轮次 | debug_dump 失败→手写脚本→调试 占 4-5 轮 → 0 轮 |
| 提升速度 | 省去 40 分钟手写临时脚本时间 |
| 提升准确度 | 从 PE header 直接读取段表，比依赖 IDA 段数据库更可靠 |

---

## 2. 技术方案

### 2.1 Bug A 修复：基于 PE Header 的段读取

**问题**：`_dump_segments()` 依赖 `ida_segment.get_first_seg()` / `ida_segment.get_next_seg()` 遍历段，但调试器模式下段数据库可能未初始化。

**修复方案**：不再依赖 IDA 段数据库，改为从 PE header 的 section table 直接定位段。

**算法**：

```
输入: image_base
输出: [(start_ea, bytes_data), ...]

1. 从 image_base 读取 DOS header (64 字节)
2. 解析 e_lfanew → 定位 PE signature
3. 解析 COFF File Header: NumberOfSections (offset +2, 2B), SizeOfOptionalHeader (offset +16, 2B)
4. 计算段表偏移 = e_lfanew + 4 + 20 + SizeOfOptionalHeader
5. 遍历每个 section header (每个 40 字节):
   a. 读取 VirtualSize (offset +8, 4 bytes)
   b. 读取 VirtualAddress (offset +12, 4 bytes)
   c. 计算段起始地址 = image_base + VirtualAddress
   d. 用 ida_bytes.get_bytes(start_ea, VirtualSize) 读取段数据
6. 返回段数据列表
```

**变更**：

- 新增函数 `_dump_segments_from_pe(image_base)` — 内部自行解析 PE header 获取段表参数
- 原 `_dump_segments()` 保留为降级路径（PE header 读取失败时尝试 IDA 段遍历，含 None 检查）
- 调用方优先使用新函数，失败时降级

**影响文件**：`scripts/debug_dump.py`

### 2.2 Bug B 修复：Image Base 自动检测（必须在调试器运行后执行）

**问题**：`ida_ida.inf_get_baseaddr()` 在调试器模式下返回 0，导致后续 PE header 读取全部失败。

**关键时序**：image_base 检测**不能在 `_main()` 中、调试器启动前执行**。调试器模式下进程内存在 `refresh_debugger_memory()` 后才可见。检测必须放在 `DumpHook.dbg_run_to()` 中 `refresh_debugger_memory()` 之后。

**修复方案**：在 `DumpHook.dbg_run_to()` 中自动检测 image base。

**算法**：

```
_detect_image_base() — 在 refresh_debugger_memory() 之后调用:
1. 尝试 ida_ida.inf_get_baseaddr()
2. 如果返回 0:
   a. 根据位数检测:
      - 32-bit: 检查 0x400000 处是否有 MZ 签名（读取前 2 字节）
      - 64-bit: 检查 0x140000000 处是否有 MZ 签名
   b. 标准地址未找到时，尝试 IDA 段数据库降级:
      seg = ida_segment.get_first_seg()
      if seg is not None:
          return seg.start_ea  ← 注意 None 检查，避免复现 Bug A
3. 都失败 → 返回 BADADDR
```

**影响文件**：`scripts/debug_dump.py`

### 2.3 Bug C 修复：分离 PE 输出与 JSON 输出路径

**问题**：`run_headless()` 将 JSON 结果写入 `IDA_OUTPUT`，而 `_rebuild_pe()` 也写入 `IDA_OUTPUT`，后者覆盖前者（或反过来）。

**修复方案**：PE dump 输出使用独立的环境变量 `IDA_PE_OUTPUT`。`_main()` 不再从 `IDA_OUTPUT` 获取 PE 输出路径，仅使用 `IDA_PE_OUTPUT`（或其推导值）。

**参数变更**：

| 环境变量 | 说明 | 必填 |
|---------|------|------|
| `IDA_OEP_ADDR` | OEP 地址（十六进制） | 是 |
| `IDA_PE_OUTPUT` | PE dump 输出文件路径 | 否（缺省取 `IDA_OUTPUT` 去掉 `.json` 后缀 + `.pe`，或 `IDA_OUTPUT` + `.pe`） |
| `IDA_OUTPUT` | JSON 结果输出路径 | 是（`run_headless()` 内部使用，debug_dump 不再将其用于 PE 输出） |

**降级逻辑**：

```python
pe_output = env_str("IDA_PE_OUTPUT", "")
if not pe_output:
    json_output = env_str("IDA_OUTPUT", "")
    if not json_output:
        return ""
    if json_output.endswith(".json"):
        pe_output = json_output[:-5] + ".pe"
    else:
        pe_output = json_output + ".pe"
```

**影响文件**：
- `scripts/debug_dump.py` — 使用 `IDA_PE_OUTPUT`，不再将 `IDA_OUTPUT` 传入 `_rebuild_pe()`
- `scripts/registry.json` — 更新 params 列表（增加 `IDA_PE_OUTPUT`）和 `example_call`
- `ida-pro-analysis-knowledge-base/templates.md` — **新增** debug_dump 调用模板（当前无此模板）

### 2.4 整体修复后的流程

**`_main()` 中（调试器启动前）**：

```
_main():
    1. 解析 IDA_OEP_ADDR
    2. 确定 PE 输出路径（IDA_PE_OUTPUT 或从 IDA_OUTPUT 推导），为空时返回错误
    3. 确定 JSON 输出路径（IDA_OUTPUT，仅传给 run_headless 用于 JSON 输出）
    4. 参数验证（OEP 有效 + PE 输出路径非空）
    5. 加载调试器
    6. 设置 DumpHook(oep_addr, pe_output_path)
    7. 运行到 OEP
    8. 等待调试器完成
    9. 返回 hook.result（JSON 由 run_headless 写入 IDA_OUTPUT）
```

**`DumpHook.dbg_run_to()` 中（调试器命中 OEP 后）**：

```
dbg_run_to():
    1. refresh_debugger_memory()
    2. 检测 PC 是否等于 OEP，不等于则继续运行
    3. _detect_image_base() — 此时内存已映射
    4. image_base 有效 → _dump_segments_from_pe(image_base) 优先
    5. 失败 → 降级到 IDA 段遍历（含 None 检查）
    6. _rebuild_pe(seg_data, image_base, oep_addr, self.pe_output_path)
    7. 返回结果
```

---

## 3. 实现规范

### 3.1 改动范围

| 文件 | 改动类型 | 行数变化 | 影响范围 |
|------|---------|---------|---------|
| `scripts/debug_dump.py` | 修改 | ~120 行改动（新增 3 个函数 + 重构 `_main` 和 `DumpHook`） | 核心逻辑 |
| `scripts/registry.json` | 修改 | params 增加 `IDA_PE_OUTPUT` + 更新 `example_call` | 注册表 |
| `templates.md` | 修改 | **新增** debug_dump 调用模板（当前文件无此模板） | 知识库 |

### 3.2 不修改的文件

- `_base.py` — `run_headless()` 的 JSON 写入逻辑不变
- `_utils.py` — 无变更
- `query.py` — 无变更
- `update.py` — 无变更
- `ida-pro-analysis.md` — 无变更（debug_dump 的调用方式由 templates.md 定义）

### 3.3 编码规则

- 遵循 AGENTS.md 所有编码规范
- 禁止 `import idc` / `import idaapi` / `from ... import ...`
- 字符串用双引号
- 中文日志，`[*]` / `[+]` / `[!]` 前缀
- 辅助函数以 `_` 前缀
- 返回 `True/False` 表示成功/失败

### 3.4 新增/修改函数签名

```python
def _detect_image_base():
    """自动检测 image base。

    在 refresh_debugger_memory() 之后调用。
    调试器模式下内存此时已映射。

    检测顺序:
      1. ida_ida.inf_get_baseaddr() — 非零直接返回
      2. 标准加载地址检查（32-bit: 0x400000, 64-bit: 0x140000000）— 检查 MZ 签名
      3. IDA 段数据库降级 — seg = get_first_seg(); if seg: return seg.start_ea
         注意: 必须检查 None，避免复现 Bug A

    返回:
      int — image base 地址，BADADDR 表示检测失败
    """

def _dump_segments_from_pe(image_base):
    """从 PE section table 直接读取段数据。

    不依赖 IDA 段数据库。内部自行解析 DOS header → COFF header → section table。

    参数:
        image_base: image base 地址（必须有效，MZ 签名可读）

    返回:
        [(start_ea, bytes)] — 段数据列表，空列表表示失败
    """

def _dump_segments_ida():
    """降级：使用 IDA 段数据库遍历读取段数据。

    原 _dump_segments() 的修复版本，增加 None 检查。

    返回:
        [(start_ea, bytes)] — 段数据列表，空列表表示失败
    """

def _resolve_pe_output():
    """确定 PE 输出文件路径。

    从 IDA_PE_OUTPUT 环境变量读取，未设置时从 IDA_OUTPUT 推导。
    IDA_OUTPUT 和 IDA_PE_OUTPUT 均为空时返回空字符串。

    返回:
        str — PE 输出路径，空字符串表示失败
    """
```

**DumpHook 构造函数变更**：移除 `image_base` 参数（image_base 在 `dbg_run_to()` 内部检测），增加 `pe_output_path` 参数：

```python
class DumpHook(ida_dbg.DBG_Hooks):
    def __init__(self, oep_addr, pe_output_path):
        # 不再接收 image_base，改为在 dbg_run_to() 内部检测
```

### 3.5 降级策略

```
在 DumpHook.dbg_run_to() 中（refresh_debugger_memory() 之后）:

    image_base = _detect_image_base()
    if image_base == BADADDR:
        return {"success": False, "error": "无法检测 image base", ...}

    seg_data = _dump_segments_from_pe(image_base)  # 优先 PE header
    if not seg_data:
        seg_data = _dump_segments_ida()  # 降级到 IDA 段遍历（含 None 检查）
    if not seg_data:
        return {"success": False, "error": "dump 内存段失败", ...}

    _rebuild_pe(seg_data, image_base, oep_addr, pe_output_path)
```

---

## 4. 验收标准

### 4.1 功能验收

- [ ] Bug A: 调试器模式下 `_dump_segments()` 不再因 `get_first_seg()` 返回 None 而崩溃
- [ ] Bug A: 能从 PE header section table 正确读取段数据
- [ ] Bug A: PE header 读取失败时能降级到 IDA 段遍历（含 None 检查）
- [ ] Bug B: `ida_ida.inf_get_baseaddr()` 返回 0 时能自动检测 image base
- [ ] Bug B: 32-bit 场景下检测 `0x400000` 处的 MZ 签名
- [ ] Bug B: 64-bit 场景下检测 `0x140000000` 处的 MZ 签名
- [ ] Bug C: PE dump 输出到 `IDA_PE_OUTPUT` 指定的路径
- [ ] Bug C: JSON 结果输出到 `IDA_OUTPUT` 指定的路径
- [ ] Bug C: 两个输出路径不互相覆盖
- [ ] Bug C: `IDA_PE_OUTPUT` 未设置时自动从 `IDA_OUTPUT` 推导（去 `.json` + `.pe`）
- [ ] Bug C: `IDA_OUTPUT` 和 `IDA_PE_OUTPUT` 均为空时返回错误（不生成 `.pe` 空路径）
- [ ] Bug B: image_base 检测在 `refresh_debugger_memory()` 之后执行（不在 `_main()` 中）

### 4.2 回归验收

- [ ] 非调试器模式（普通静态分析）下 debug_dump.py 不受影响（PE header 读取仍有效）
- [ ] `registry.json` 的 `debug_dump` 条目 params 包含 `IDA_PE_OUTPUT`
- [ ] `templates.md` 的 debug_dump 调用模板包含 `IDA_PE_OUTPUT`
- [ ] 所有脚本通过 `python -c "compile(...)"` 语法检查
- [ ] `run_headless()` 的 JSON 输出格式不变（success/error/data 结构）

### 4.3 架构验收

- [ ] 依赖方向合规：`debug_dump.py` → `_base.py`（不变）
- [ ] 不引入新的模块依赖
- [ ] 新增函数有完整的中文 docstring

---

## 5. 与现有文档的关系

| 现有文档 | 关系 |
|---------|------|
| [需求-动态分析能力与脱壳流程增强](需求-动态分析能力与脱壳流程增强.md) | debug_dump.py 是动态脱壳流程（方案 D）的 IDA 调试器 dump 工具，本次修复其致命 bug |
| [需求-加壳二进制静态分析脱壳流程](需求-加壳二进制静态分析脱壳流程.md) | debug_dump.py 是 `analysis-planning.md` 中 packed 场景步骤 4 的执行工具 |
| [AGENTS.md](../../AGENTS.md) | 遵循编码规范 |

---

## 6. 不做的事

1. **不做 IAT 重建** — 输出 PE 仅用于 IDA 加载分析，不用于直接运行
2. **不做非 PE 格式支持** — 当前仅处理 PE（ELF/Mach-O 不在范围内）
3. **不做断点管理增强** — 仅修复 dump 逻辑，断点设置/管理不变
