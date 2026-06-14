# 需求：query 增强 — thunk 自动追踪与数据读取

## 1. 背景与目标

### 1.1 背景

在对 `lesson1.exe.i64` 的实际分析中（详见 `docs/需求/需求-IDA-Pro-AI智能分析命令.md` 端到端场景），暴露了两个效率瓶颈：

**瓶颈 1：thunk 函数链导致大量无效 idat 调用**

MSVC 编译的二进制中，大量函数通过 thunk 间接调用（如 `validate_credentials` → `sub_140008AB0`）。当前 `decompile` 查询只返回 thunk 包装：
```c
// attributes: thunk
__int64 __fastcall validate_credentials(__int64 a1, __int64 a2) {
  return sub_140008AB0(a1, a2);
}
```
AI 必须再发起一次 idat 调用才能看到真正逻辑。本次分析中 7 次反编译调用有 3 次是 thunk 追踪，每次开销 ~15 秒 + 上下文占用。

**瓶颈 2：无法读取全局数据，被迫手写 IDAPython 脚本**

`Str2` 存储在 `.rdata` 段的全局变量中，现有 query 类型均无法读取：
- `strings` 搜索 → IDA 未将其识别为字符串，搜索不到
- `xrefs_to` → 只返回引用位置，不返回数据内容

最终手写了 2 个 IDAPython 脚本才读出值（第 1 个误读为原始字节，第 2 个才发现是指针需要解引用）。

### 1.2 目标

通过两个增强，将分析型任务的 idat 调用次数减少 ~50%，消除 AI 手写 IDAPython 脚本的需求：

| 指标 | 增强前（lesson1 分析实测） | 增强后预估 |
|------|--------------------------|----------|
| idat 调用次数 | ~16 | ~6-8 |
| AI 手写脚本次数 | 2 | 0 |
| 对话轮次 | ~12 | ~6-7 |

### 1.3 设计原则

1. **收益必须大**：每个改动必须能显著减少 idat 调用或消除手写脚本
2. **不能改坏现有功能**：所有现有查询类型的输入/输出格式不变，仅扩展
3. **通用抽象**：thunk 追踪和数据读取作为共享工具函数，供所有脚本复用
4. **架构可扩展**：新工具模块的设计支持后续功能追加（如未来可能的 crypto 常量检测等）

---

## 2. 技术方案

### 2.1 新增共享工具模块 `_utils.py`

**动机**：thunk 追踪和数据读取是通用的逆向分析原语，不应仅存在于 `query.py` 中。`update.py` 和未来沉淀脚本也可能需要这些能力（如 `update.py` 的 `_resolve_addr` 和 `query.py` 的 `_resolve_addr` 目前已有重复）。

**位置**：`.opencode/commands/ida-pro-analysis-scripts/_utils.py`

**提供的工具函数**：

```
_utils.py 提供的功能：
1. resolve_thunk(start_ea, max_depth=10) — thunk 链追踪，返回 (chain, real_func)
2. read_string_at(ea, max_len=4096) — 读取 null-terminated 字符串
3. read_bytes_at(ea, length) — 读取原始字节（返回 hex + ASCII）
4. read_pointer(ea) — 读取指针值（根据数据库位数自适应 4/8 字节）
5. read_data_auto(ea, size_hint=256) — 自动判断数据类型并读取
6. resolve_addr(addr_str) — 统一的地址解析（替代 query.py 和 update.py 中的重复实现）
7. hex_addr(ea) — 格式化地址为 "0x..." 字符串（替代两处重复的 _hex）
8. get_func_name_safe(ea) — 安全获取函数名（替代 query.py 中的重复实现）
```

**依赖关系更新**：

```
_base.py （基础设施：日志、环境变量、headless 入口、JSON 输出）
    ↑
_utils.py （业务工具：thunk 追踪、数据读取、地址解析）
    ↑
query.py / update.py / scripts/*.py （具体业务逻辑）
```

### 2.2 方案 A：decompile / disassemble 自动追踪 thunk 链

#### 2.2.1 thunk 检测算法

通过两个条件判断函数是否为 thunk：

1. **IDA 标记**：`func.flags & ida_funcs.FUNC_THUNK`（最可靠）
2. **启发式补充**：函数体 ≤ 5 字节 且 仅有 1 个代码引用目标（处理 IDA 未正确标记的边缘情况）

#### 2.2.2 thunk 追踪策略

```
输入地址 ea
    ↓
get_func(ea)
    ↓
是 thunk？──否──→ 返回原函数
    ↓ 是
遍历 CodeRefsFrom(start_ea) 找到跳转目标
    ↓
get_func(目标地址)
    ↓
是 thunk？──是──→ 继续追踪（最多 max_depth=10 层）
    ↓ 否
返回: { chain: [...], target: real_func }
```

#### 2.2.3 影响的查询类型

| 查询类型 | 追踪 thunk？ | 原因 |
|---------|-------------|------|
| `decompile` | **是** | thunk 的反编译结果无分析价值，浪费上下文 |
| `disassemble` | **是** | 同上 |
| `func_info` | **是** | 用户关心的是真实函数的信息 |
| `xrefs_to` | 否 | 用户可能特意查询 thunk 本身的引用 |
| `xrefs_from` | 否 | 同上 |
| 其他 | 否 | 不涉及函数级别的操作 |

#### 2.2.4 输出格式变更

当 thunk 追踪发生时，在返回结果中追加 `thunk_chain` 字段：

**`thunk_chain` 语义**：记录从用户请求的函数到真实函数所经过的所有中间 thunk（不包含最终真实函数）。`data.func_name` 和 `data.addr` 直接指向真实函数。

```json
{
  "success": true,
  "query": "decompile",
  "data": {
    "func_name": "sub_140008AB0",
    "addr": "0x140008AB0",
    "source": "(真实函数的反编译代码)",
    "source_type": "decompiled",
    "size": 370,
    "thunk_chain": [
      {"name": "validate_credentials", "addr": "0x140001596"}
    ]
  },
  "error": null
}
```

上例中：用户请求反编译 `validate_credentials`，thunk 追踪发现它是 thunk，真实函数是 `sub_140008AB0`。`thunk_chain` 记录了中间经过的 thunk（`validate_credentials`），`func_name`/`addr` 直接指向真实函数。

**向后兼容**：当函数不是 thunk 时，不包含 `thunk_chain` 字段。现有解析逻辑不受影响。

### 2.3 方案 B：新增 `read_data` 查询类型

#### 2.3.1 功能定义

读取指定地址处的全局数据。支持四种读取模式：

| 模式（`IDA_READ_MODE`） | 说明 | 输出 |
|------------------------|------|------|
| `string` | 读取 null-terminated 字符串 | `{value, length, addr}` |
| `bytes` | 读取指定长度的原始字节 | `{hex, ascii, length, addr}` |
| `pointer` | 读取指针值并可选解引用 | `{pointer_value, dereferenced, ...}` |
| `auto`（默认） | 自动判断数据类型 | 根据实际类型返回上述之一 |

#### 2.3.2 参数

| 环境变量 | 说明 | 必填 |
|---------|------|------|
| `IDA_QUERY` | 固定为 `read_data` | 是 |
| `IDA_ADDR` | 目标地址（函数名或十六进制地址） | 是 |
| `IDA_READ_MODE` | 读取模式：`string`/`bytes`/`pointer`/`auto`，默认 `auto` | 否 |
| `IDA_READ_SIZE` | 读取长度（仅 `bytes` 模式有效，默认 64） | 否 |
| `IDA_DEREF` | 设为 `1` 时跟解引用指针（仅 `pointer` 模式，默认 `0`） | 否 |
| `IDA_OUTPUT` | 输出文件路径 | 是 |

#### 2.3.3 `auto` 模式的判断逻辑

按以下优先级依次尝试：

```
步骤 1: 尝试作为字符串读取（地址处是否有可打印字符 + null 结尾？）
    ↓ 是                              ↓ 否
返回: { type: "string" }    步骤 2: 尝试作为指针解引用
                                    ↓
                              读取地址处的指针值 ptr（根据数据库位数读取 4/8 字节）
                                    ↓
                              ptr 是否在合法地址范围内 且指向可读内存？
                                    ↓ 是                              ↓ 否
                              ptr 指向的内容是否像字符串？      返回: { type: "bytes",
                                    ↓ 是          ↓ 否              hex: "...",
                              返回:            返回:              ascii: "..." }
                              { type: "pointer", { type: "pointer",
                                dereferenced:     dereferenced: null }
                                {type:"string"} }
```

**优先级**：bytes → string → pointer。避免将普通字符串数据误判为指针。

#### 2.3.4 输出格式

**string 模式**：
```json
{
  "success": true,
  "query": "read_data",
  "data": {
    "type": "string",
    "addr": "0x140108F70",
    "value": "cm9vdA==",
    "length": 8
  },
  "error": null
}
```

**bytes 模式**：
```json
{
  "success": true,
  "query": "read_data",
  "data": {
    "type": "bytes",
    "addr": "0x14013F008",
    "hex": "70 8F 10 40 01 00 00 00",
    "ascii": "p..@....",
    "length": 8
  },
  "error": null
}
```

**pointer 模式（带解引用）**：
```json
{
  "success": true,
  "query": "read_data",
  "data": {
    "type": "pointer",
    "addr": "0x14013F008",
    "pointer_value": "0x140108F70",
    "dereferenced": {
      "type": "string",
      "addr": "0x140108F70",
      "value": "cm9vdA==",
      "length": 8
    }
  },
  "error": null
}
```

#### 2.3.5 调用方式

```bash
# 自动模式（推荐）
IDA_QUERY=read_data IDA_ADDR=0x14013F008 IDA_OUTPUT="$TASK_DIR/result.json" \
  idat -A -S".../query.py" -L"$TASK_DIR/idat.log" target.i64

# 指针模式 + 解引用
IDA_QUERY=read_data IDA_ADDR=Str2 IDA_READ_MODE=pointer IDA_DEREF=1 IDA_OUTPUT="$TASK_DIR/result.json" \
  idat -A -S".../query.py" -L"$TASK_DIR/idat.log" target.i64
```

---

## 3. 实现规范

### 3.1 改动范围

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `_utils.py` | **新建** | 共享业务工具模块（thunk 追踪、数据读取、地址解析） |
| `_base.py` | **不变** | 基础设施层不动 |
| `query.py` | **修改** | 1. 引用 `_utils` 替代内联重复代码<br>2. `_query_decompile` / `_query_disassemble` 加入 thunk 追踪<br>3. 新增 `_query_read_data` 处理函数 |
| `update.py` | **修改** | 引用 `_utils` 替代内联重复的 `_resolve_addr` / `_hex` |
| `ida-pro-analysis.md` | **修改** | 工具脚本清单新增 `read_data` 查询类型 |
| `README.md` | **修改** | 查询类型表格新增 `read_data` |

### 3.2 `_utils.py` 函数签名

```python
def resolve_thunk(start_ea, max_depth=10):
    """追踪 thunk 链到真实函数。

    参数:
        start_ea: 起始地址
        max_depth: 最大追踪深度（防无限循环）

    返回:
        (chain, real_func_ea)
        chain: [{"name": str, "addr": str}] — 经过的中间 thunk 列表（不含最终真实函数）
        real_func_ea: 最终真实函数的起始地址，BADADDR 表示追踪失败
    """

def read_string_at(ea, max_len=4096):
    """读取 null-terminated 字符串。

    返回:
        {"value": str, "length": int, "addr": str} 或 None（不可读）
    """

def read_bytes_at(ea, length):
    """读取原始字节。

    返回:
        {"hex": str, "ascii": str, "length": int, "addr": str}
    """

def read_pointer(ea):
    """读取指针值（根据数据库位数自适应 4/8 字节）。

    返回:
        {"pointer_value": str, "addr": str}
    """

def read_data_auto(ea, size_hint=256):
    """自动判断数据类型并读取。

    返回:
        dict — 包含 "type" 字段和对应类型的数据
    """

def resolve_addr(addr_str):
    """统一地址解析（函数名或十六进制地址）。

    返回:
        ea (int) — 解析后的地址，BADADDR 表示失败
    """

def hex_addr(ea):
    """格式化地址为 "0x..." 字符串。"""

def get_func_name_safe(ea):
    """安全获取函数名，失败返回空字符串。"""
```

### 3.3 代码迁移规范

从 `query.py` 和 `update.py` 中迁移到 `_utils.py` 的重复代码：

| 原位置 | 迁移到 | 说明 |
|--------|-------|------|
| `query.py::_resolve_addr` | `_utils.py::resolve_addr` | 统一地址解析逻辑 |
| `query.py::_resolve_func` | 保留在 `query.py`，内部调用 `resolve_addr` | 函数级解析仍由 query 负责 |
| `query.py::_hex` | `_utils.py::hex_addr` | 统一格式化 |
| `update.py::_resolve_addr` | 删除，引用 `_utils.resolve_addr` | 消除重复 |
| `update.py::_hex` | 删除，引用 `_utils.hex_addr` | 消除重复 |
| `query.py::_get_func_name_safe` | `_utils.py::get_func_name_safe` | 消除重复 |

### 3.4 编码规则

继承项目 AGENTS.md 的所有编码规范，额外强调：

- `_utils.py` 仅依赖 `_base.py` 的 `log` 函数和 IDAPython 模块
- `_utils.py` 不依赖 `query.py` 或 `update.py`（避免循环依赖）
- 所有函数包含中文日志（`[*]`/`[+]`/`[!]` 前缀）
- 新增查询类型的处理函数遵循现有 `_query_xxx` 命名模式

---

## 4. 验收标准

### 4.1 功能验收

- [ ] `decompile` 查询 thunk 函数时，自动返回真实函数的反编译代码
- [ ] `disassemble` 查询 thunk 函数时，自动返回真实函数的反汇编
- [ ] `func_info` 查询 thunk 函数时，自动返回真实函数的信息
- [ ] thunk 追踪结果包含 `thunk_chain` 字段记录完整链路
- [ ] `read_data` 查询支持 `string`/`bytes`/`pointer`/`auto` 四种模式
- [ ] `read_data` 的 `auto` 模式能正确识别指针指向的字符串
- [ ] 用 `lesson1.exe.i64` 验证：读取 `Str2` 地址 `0x14013F008` 返回 `"cm9vdA=="`
- [ ] 用 `lesson1.exe.i64` 验证：反编译 `validate_credentials` 直接返回 `sub_140008AB0` 的代码

### 4.2 回归验收

- [ ] 所有现有查询类型（`entry_points`/`functions`/`decompile`/`disassemble`/`func_info`/`xrefs_to`/`xrefs_from`/`strings`/`imports`/`exports`/`segments`）的输出格式不变
- [ ] `update.py` 所有操作类型正常工作
- [ ] pytest 测试通过
- [ ] 所有脚本通过 `python3 -c "compile(...)"` 语法检查

### 4.3 架构验收

- [ ] `_utils.py` 不依赖 `query.py` 或 `update.py`
- [ ] `query.py` 和 `update.py` 中的重复代码已消除（地址解析、hex 格式化、函数名获取）
- [ ] 新增工具函数有完整的 docstring
- [ ] 命令 prompt 和 README 已更新

---

## 5. 与现有需求文档的关系

本需求是 `需求-IDA-Pro-AI智能分析命令.md` Phase 3（增强体验）的延伸，聚焦于**查询效率优化**。

Phase 3 原始条目为：
1. 根据实际使用反馈优化命令 prompt
2. 完善沉淀脚本库
3. 添加执行超时保护
4. 增加生成脚本的质量校验
5. 优化输出格式

本需求基于 Phase 1/2 的端到端实测（`lesson1.exe.i64`），发现了 thunk 追踪和数据读取两个效率瓶颈，属于 Phase 3 第 1 条"根据实际使用反馈优化"的具体落地。与 Phase 3 其他条目无冲突，可独立实施。
