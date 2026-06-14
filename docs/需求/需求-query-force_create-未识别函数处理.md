# 需求：query.py decompile 增加 force_create 能力

## 1. 背景与目标

### 1.1 来源

复盘 CRACKME3（UPX 加壳）分析过程，发现脱壳后的二进制中部分地址的代码未被 IDA 识别为函数。当前 `decompile` 查询对未识别函数地址直接报错（`"无法解析函数: <addr>"`），AI 被迫手写临时脚本 `create_and_decompile.py` 来手动创建函数后再反编译。

### 1.2 痛点

| 痛点 | 浪费时间 | 根因 |
|------|---------|------|
| 手写 create_and_decompile.py 临时脚本 | ~10 分钟 | decompile 查询无法处理未识别函数 |
| 脚本调试（参数传递、路径问题） | ~5 分钟 | 每次都需要从头构造 |
| 上下文占用（临时脚本源码在对话中） | ~500 tokens | 临时脚本代码挤占分析上下文 |

### 1.3 目标

当 `decompile` 查询目标地址不在任何函数内时，自动（或通过环境变量控制）调用 `ida_funcs.add_func()` 创建函数后重试反编译，消除手写临时脚本的需要。

### 1.4 评估维度

| 维度 | 改进 |
|------|------|
| 减少上下文 | 消除临时脚本源码（~50 行 → 0） |
| 减少对话轮次 | 手写脚本→调试 占 2-3 轮 → 0 轮 |
| 提升速度 | 省去 15 分钟手写脚本时间 |
| 提升准确度 | 直接使用内置能力，减少手动操作出错 |

---

## 2. 技术方案

### 2.1 核心思路

在 `query.py` 的 `_query_decompile()` 函数中，当地址解析失败（不在任何函数内）时，检查 `IDA_FORCE_CREATE` 环境变量。若为 `1`，则自动调用 `ida_funcs.add_func()` 在该地址创建函数，然后重新尝试反编译。

### 2.2 影响范围

同样适用于 `_query_disassemble()` 和 `_query_func_info()`，因为它们都依赖 `_resolve_func_with_thunk()` 进行地址解析。只要地址解析阶段能处理未识别函数，所有查询类型都能受益。

**方案选择**：在 `_resolve_func_with_thunk()` 中处理（所有依赖该函数的查询类型自动受益），而非在每个 `_query_xxx` 中单独处理。

### 2.3 实现细节

#### 2.3.1 环境变量

| 环境变量 | 说明 | 默认值 |
|---------|------|--------|
| `IDA_FORCE_CREATE` | 设为 `1` 时，对未识别函数地址自动调用 `add_func()` | `0`（不自动创建） |

#### 2.3.2 修改 `_resolve_func_with_thunk()` 逻辑

**返回值变更**：当前返回 `(func, chain)`。修改后返回 `(func, chain, force_created)`，第三个参数为 `bool`，指示是否通过 force_create 创建了函数。

**算法**：

```
_resolve_func_with_thunk(addr_str) → (func, chain, force_created):
    force_created = False
    1. 解析地址 ea = resolve_addr(addr_str)
    2. 正常 thunk 追踪: (real_ea, chain) = resolve_thunk(ea)
    3. 查找函数 func = ida_funcs.get_func(real_ea)
    4. 如果 func 为 None 且 real_ea != BADADDR:
       a. 检查 IDA_FORCE_CREATE == "1"（通过 env_bool）
       b. 如果是:
          - 调用 ida_funcs.add_func(real_ea)
          - 调用 ida_auto.auto_wait()（等待 IDA 完成对新函数的分析）
          - 重新查找 func = ida_funcs.get_func(real_ea)
          - 如果仍为 None → 记录错误日志，返回 (None, [], False)
          - force_created = True
       c. 如果不是 → 记录错误日志，返回 (None, [], False)
    5. 返回 (func, chain, force_created)
```

**设计说明**：force_create 应用于 thunk 追踪后的真实地址（`real_ea`），而非输入地址（`ea`）。这解决了"输入是 thunk → 真实目标未识别"的场景。如果输入地址本身就是未识别代码（非 thunk），`resolve_thunk()` 会返回 `(ea, [])`，force_create 仍然生效。

**已知的局限性**（可接受）：如果输入是 thunk 且 thunk 本身未被 IDA 识别为函数，`resolve_thunk()` 无法追踪 thunk 链，会直接返回 `(ea, [])`。此时 force_create 在输入地址 `ea` 上创建函数，创建后是 thunk 函数，后续 thunk 追踪可以再次执行。这需要两次 force_create，但实际场景中极少发生。

#### 2.3.3 日志输出

```
[*] 地址 {hex_addr(real_ea)} 不在任何函数内，IDA_FORCE_CREATE=1，正在尝试创建函数...
[+] 函数创建成功: {func_name} ({hex_addr(start_ea)} - {hex_addr(end_ea)}, {size} 字节)
```

或失败时：

```
[!] 函数创建失败: {hex_addr(real_ea)}，该地址处可能不是有效的函数入口
```

#### 2.3.4 输出格式

当 force_create 生效时，在返回结果中追加 `force_created` 字段：

```json
{
  "success": true,
  "query": "decompile",
  "data": {
    "func_name": "sub_4047CB",
    "addr": "0x4047CB",
    "source": "(反编译代码)",
    "source_type": "decompiled",
    "size": 480,
    "force_created": true
  },
  "error": null
}
```

**向后兼容**：正常情况下（函数已存在或 IDA_FORCE_CREATE 未设置），输出格式完全不变。

### 2.4 主 prompt 变更

在 `ida-pro-analysis.md` 的 query.py 查询类型表格中，`decompile` 行的"额外参数"列增加 `IDA_FORCE_CREATE`：

```
| `decompile` | 反编译函数 | `IDA_FUNC_ADDR` + `IDA_FORCE_CREATE` |
| `disassemble` | 反汇编函数 | `IDA_FUNC_ADDR` + `IDA_FORCE_CREATE` |
| `func_info` | 函数详情 | `IDA_FUNC_ADDR` + `IDA_FORCE_CREATE` |
```

### 2.5 templates.md 变更

在 query 调用模板中增加 `IDA_FORCE_CREATE` 说明：

```bash
# 反编译未识别函数（脱壳后常见）
IDA_QUERY=decompile IDA_FUNC_ADDR=0x4047CB IDA_FORCE_CREATE=1 IDA_OUTPUT="$TASK_DIR/result.json" \
  "$IDAT" -A -S"$SCRIPTS_DIR/query.py" -L"$TASK_DIR/idat.log" "<目标文件>"
```

---

## 3. 实现规范

### 3.1 改动范围

| 文件 | 改动类型 | 行数变化 | 影响范围 |
|------|---------|---------|---------|
| `query.py` | 修改 | ~40 行（`_resolve_func_with_thunk()` 重写 + 所有调用方更新返回值处理） | 核心查询逻辑 |
| `ida-pro-analysis.md` | 修改 | ~3 行（查询表格更新） | 主 prompt |
| `templates.md` | 修改 | ~5 行（增加 force_create 调用示例） | 知识库 |

### 3.2 不修改的文件

- `_base.py` — 无变更
- `_utils.py` — 无变更
- `update.py` — 无变更
- `scripts/debug_dump.py` — 无变更

### 3.3 编码规则

- 遵循 AGENTS.md 所有编码规范
- `ida_funcs.add_func()` 的返回值必须检查（成功/失败）
- `add_func()` 后必须调用 `ida_auto.auto_wait()` 等待 IDA 完成对新函数的分析
- 日志用中文，`[*]` / `[+]` / `[!]` 前缀
- `IDA_FORCE_CREATE` 通过 `_base.env_bool()` 读取（与 `IDA_DEREF` 等布尔型环境变量保持一致）
- `_resolve_func_with_thunk()` 返回值从 `(func, chain)` 变更为 `(func, chain, force_created)`，所有调用方需更新

---

## 4. 验收标准

### 4.1 功能验收

- [ ] `IDA_FORCE_CREATE=1` + `IDA_QUERY=decompile` + 未识别函数地址 → 自动创建函数并反编译
- [ ] `IDA_FORCE_CREATE=1` + `IDA_QUERY=disassemble` + 未识别函数地址 → 自动创建函数并反汇编
- [ ] `IDA_FORCE_CREATE=1` + `IDA_QUERY=func_info` + 未识别函数地址 → 自动创建函数并返回信息
- [ ] `add_func()` 失败时返回清晰错误信息（不是崩溃）
- [ ] `add_func()` 成功后调用 `ida_auto.auto_wait()` 等待分析完成
- [ ] `_resolve_func_with_thunk()` 返回 3 元组 `(func, chain, force_created)`，所有调用方正确处理
- [ ] `IDA_FORCE_CREATE` 未设置（默认 `0`）时行为不变
- [ ] 成功创建函数时返回结果包含 `force_created: true` 字段

### 4.2 回归验收

- [ ] 所有现有查询类型（`entry_points`/`functions`/`decompile`/`disassemble`/`func_info`/`xrefs_to`/`xrefs_from`/`strings`/`imports`/`exports`/`segments`/`read_data`/`packer_detect`）的输出格式不变
- [ ] `IDA_FORCE_CREATE=0`（默认）时，未识别函数地址仍返回错误
- [ ] 已识别函数地址不受 `IDA_FORCE_CREATE` 影响
- [ ] pytest 测试通过

### 4.3 架构验收

- [ ] 依赖方向合规：`query.py` → `_utils.py` → `_base.py`（不变）
- [ ] 不引入新的模块依赖（仅使用已有的 `ida_funcs`）
- [ ] 修改集中在 `_resolve_func_with_thunk()` 函数内

---

## 5. 与现有文档的关系

| 现有文档 | 关系 |
|---------|------|
| [需求-query增强-thunk追踪与数据读取](需求-query增强-thunk追踪与数据读取.md) | 本次需求是 query.py 增强的延续：thunk 追踪解决了"找错函数"问题，force_create 解决了"找不到函数"问题 |
| [需求-加壳二进制静态分析脱壳流程](需求-加壳二进制静态分析脱壳流程.md) | 脱壳后的二进制中未识别函数是常见场景，force_create 让后续分析无需手写脚本 |
| [AGENTS.md](../../AGENTS.md) | 遵循编码规范 |

---

## 6. 不做的事

1. **不做自动 force_create** — 必须显式设置 `IDA_FORCE_CREATE=1`，避免在正常场景下误创建函数
2. **不做函数边界优化** — `add_func()` 使用 IDA 默认的函数边界检测，不手动指定大小
3. **不做批量 force_create** — 一次只处理一个地址，不扫描整个代码段自动创建函数
