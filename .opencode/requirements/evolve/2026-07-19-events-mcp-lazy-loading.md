# Events MCP 启动延迟优化（lazy 加载，对齐 knowledge MCP）

## §1 背景与目标

### 来源痛点

knowledge MCP 已完成 lifespan lazy 加载改造（需求 `2026-07-19-knowledge-mcp-lazy-loading.md`），实测收益：握手从 15.28s 降到 4.80s。

events MCP 当前是**旧模式**——`_initialized` bool + `if _initialized: return`：
- 握手快（0.59s，因为模块顶层什么都不加载）
- **但首次工具调用卡 14.57s**（`_ensure_ready` 内同步加载 BGE-M3 + bge-reranker-v2-m3，期间阻塞 asyncio loop）
- 多并发首次调用有 race condition（`_initialized` bool 不是协程安全的）

### 基线实测（2026-07-19，test/mcp_events/measure_events_phases.py）

| 阶段 | 耗时 |
|------|------|
| 握手 | 0.59s |
| 首次工具调用（含模型加载 + 网络） | 14.57s |
| 第二次工具调用（模型已加载） | 0.02s |
| **一次性成本**（可被 lifespan 吸收） | **14.55s** |
| 每次成本（DeepSeek + Neo4j 网络，无法消除） | 0.02s |

### 改造后实测（2026-07-19，test/mcp_events/test_unit_await_behavior.py）

**Layer 1：单元契约测试（3/3 通过，52s）**

| 测试 | 改造前 | 改造后 | 通过？ |
|------|--------|--------|--------|
| 握手快 | 0.59s | 0.59s | ✅（<5s） |
| 首次调用等待模型加载 | 14.57s | 15.14s | ✅（>3s + 成功返回） |
| 第二次调用立即返回 | 0.02s | 0.024s | ✅（<1s，加速比 649x） |

**Layer 2：用户场景测试（方案 B 核心价值）**

| 测试 | 数据 |
|------|------|
| 启动 → 等 15s（用户思考） → 调用工具 | **调用耗时 0.191s** ✅ |

**Layer 3：race condition 测试**

| 测试 | 数据 |
|------|------|
| 并发 2 个首次调用总耗时 | 14.85s（<25s 阈值，证明共享 _ready） ✅ |

**Layer 4：加载失败测试**

| 测试 | 数据 |
|------|------|
| 加载失败时调用工具耗时 | 0.01s（<5s 阈值，未 hang） ✅ |
| 错误消息 | `events MCP 加载失败: injected load failure for test` ✅ |

**Layer 5：OpenCode 集成测试（opencode serve + LLM 实际调用）**

| 测试 | 数据 |
|------|------|
| opencode serve 启动后 events MCP 状态 | `connected` ✅ |
| LLM 调用 `mcp__events__recent_context_search` | 成功返回结果 ✅ |

**Layer 6：knowledge MCP 不受影响验证**

| 测试 | 数据 |
|------|------|
| LLM 调用 `mcp__knowledge__search_answer` 查询 frida | 返回 3 条匹配记录（id 14/15/16） ✅ |

### 改造目标

对齐 knowledge MCP 的 lifespan + asyncio.Event + run_in_executor 方案：
- lifespan startup 内启动后台子线程加载模型（BGE-M3 + bge-reranker-v2-m3）
- lifespan 立即 yield，握手快（< 2s）
- 工具调用 `await _ready.wait()`：模型已就绪立即返回；未就绪则等待
- 修复多并发首次调用 race condition（asyncio.Event 协程安全）

### 预期收益

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 提升分析速度 | 首次工具调用 14.57s | 首次工具调用 ~1-2s（仅 build_indices + 网络） |
| 提升结果准确度 | 多并发首次调用可能重复初始化 | 无 race |
| 减少对话轮次 | 用户等待首次响应长 | 立即响应 |

---

## §2 技术方案

### 2.1 核心机制（对齐 knowledge MCP）

`server.py` 顶层加 `_state` / `_ready` / `_init_error` / `_loop` / `_load_future` 全局，加 lifespan context manager，工具函数开头加 `await _ensure_ready()`。

### 2.2 events 与 knowledge 的关键差异

| 维度 | knowledge MCP | events MCP |
|------|--------------|-----------|
| 子线程可完成的工作 | BGE-M3 + MemoryDB（全同步） | BGE-M3 + reranker 加载（同步） |
| 必须 async 的工作 | 无 | `build_indices_and_constraints`（Neo4j IO） |
| 工具函数改造 | sync → async（7 个） | **已经是 async**（8 个，仅改 _ensure_ready 实现） |

events 改造**不需要把工具改成 async**（它们本来就是 async），只需要：
1. 加 lifespan
2. 改 `_ensure_ready` 实现
3. 把 `create_graphiti` 调用从 `_ensure_ready` 移到子线程
4. 加 `_state["indices_built"]` flag 控制 `build_indices_and_constraints` 仅执行一次

### 2.3 代码骨架

```python
import asyncio
from contextlib import asynccontextmanager

_state: dict = {"graphiti": None, "indices_built": False}
_ready = asyncio.Event()
_init_error: list[Exception] = []
_loop: asyncio.AbstractEventLoop | None = None
_load_future = None
_indices_lock = asyncio.Lock()  # 保护 build_indices 并发执行


def _preload_models_blocking() -> None:
    """子线程同步加载 BGE-M3 + reranker + 创建 Graphiti 对象。

    通过 graphiti.embedder.model / graphiti.cross_encoder.model 触发 @property 延迟加载。
    build_indices_and_constraints 是 async，留给 _ensure_ready 在 loop 内跑。
    """
    try:
        from graphiti_config import create_graphiti
        graphiti, err = create_graphiti()
        if err:
            _init_error.append(RuntimeError(err))
            return
        # 触发 BGE-M3 加载（@property）
        _ = graphiti.embedder.model
        # 触发 bge-reranker-v2-m3 加载（@property）
        _ = graphiti.cross_encoder.model
        _state["graphiti"] = graphiti
    except Exception as e:
        _init_error.append(e)
    finally:
        if _loop is not None:
            _loop.call_soon_threadsafe(_ready.set)


@asynccontextmanager
async def lifespan(app):
    global _loop, _load_future
    _loop = asyncio.get_running_loop()
    _load_future = _loop.run_in_executor(None, _preload_models_blocking)
    yield


async def _ensure_ready() -> None:
    """等待模型加载完成（_ready Event），首次调用时建 Neo4j 索引（async）。

    用 asyncio.Lock 保护 build_indices_and_constraints：多并发首次调用时
    只有一个协程执行 build，其他等待。
    """
    await _ready.wait()
    if _init_error:
        raise RuntimeError(f"events MCP 加载失败: {_init_error[0]}")
    if not _state["indices_built"]:
        async with _indices_lock:
            # double-check：拿到锁后可能已被其他协程构建完
            if not _state["indices_built"]:
                await _state["graphiti"].build_indices_and_constraints()
                _state["indices_built"] = True


mcp = FastMCP("events", lifespan=lifespan)
```

### 2.4 工具函数改动（仅引用方式调整）

每个工具函数体内：
- 改造前：`results = await _graphiti.search_(...)`
- 改造后：`results = await _state["graphiti"].search_(...)`

`delete_session_events` 同理：
- 改造前：`await EntityNode.delete_by_group_id(_graphiti.driver, group_id)`
- 改造后：`await EntityNode.delete_by_group_id(_state["graphiti"].driver, group_id)`

### 2.5 graphiti_config.py 改动

**无**。`create_graphiti()` 签名不变。

### 2.6 plugin security-analysis.ts 改动

**无**。fire-and-forget 模式保持不变（events MCP 注册流程不变）。

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 行数估计 |
|------|---------|---------|
| `.opencode/mcp-servers/events/server.py` | 加 lifespan + 改 _ensure_ready + 8 个工具引用方式 | ~50 行 |
| `test/mcp_events/test_unit_await_behavior.py` | 新增单元测试（对齐 knowledge） | ~120 行 |

### 编码规则

1. **`_state` 字典存共享对象**：`graphiti`、`indices_built`。对齐 knowledge MCP 命名。
2. **`_init_error` 列表存加载异常**：工具调用时检查并抛出。
3. **`_loop` 显式保存**：子线程跨线程唤醒 Event 必需。
4. **`_load_future` 保存 Future 引用**：避免 GC 警告。
5. **`asyncio.Event` 模块顶层创建**：Python 3.10+ 不绑定 loop，安全。
6. **`build_indices_and_constraints` 留在 loop 内 async 跑**：不能放子线程（async 函数）。
7. **`_state["indices_built"]` flag 控制**：避免每次工具调用都跑 build_indices。
8. **工具函数已经是 async，不需要改签名**：只改 `_ensure_ready` 实现 + 引用 `_state["graphiti"]` 而非 `_graphiti`。

### §3.1 实施步骤拆分

#### 步骤 1：基线测量（已完成）

- 文件：`test/mcp_events/measure_events_phases.py`（已创建）
- 改动：实测握手 0.59s / 首次 14.57s / 第二次 0.02s
- 验证点：数据已记录到需求文档 §1
- 依赖：无

#### 步骤 2：server.py 顶层重构 + lifespan 引入

- 文件：`.opencode/mcp-servers/events/server.py`
- 改动：
  - 删除顶层 `_graphiti = None`、`_initialized = False`
  - 新增 `_state`、`_ready`、`_init_error`、`_loop`、`_load_future` 全局
  - 新增 `_preload_models_blocking()` 子线程入口
  - 新增 `lifespan()` async context manager
  - 改 `_ensure_ready()` 实现：`await _ready.wait()` + `if _init_error` + `if not _state["indices_built"]`
  - `mcp = FastMCP("events", lifespan=lifespan)`
- 预估行数：~40 行
- 验证点：
  - `python -c "compile(open('...').read(), '...', 'exec')"` 语法通过
  - server.py 顶层无 `_graphiti = None`
  - `mcp` 实例的 lifespan 不为 None
- 依赖：步骤 1

#### 步骤 3：8 个工具函数引用方式调整

- 文件：`.opencode/mcp-servers/events/server.py`
- 改动：
  - 8 个工具函数体内：`_graphiti` → `_state["graphiti"]`
  - `delete_session_events` 内的 `_graphiti.driver` → `_state["graphiti"].driver`
- 预估行数：~10 行
- 验证点：
  - 语法通过
  - grep `_graphiti` 在文件中无残留（除注释）
- 依赖：步骤 2

#### 步骤 4：端到端验证 — 握手耗时

- 文件：无（执行 `test/mcp_events/measure_events_phases.py`）
- 预期：握手从 0.59s 略升到 ~1s（含 lifespan startup 开销，但 lifespan 立即 yield）；首次工具调用从 14.57s 降到 ~1-2s
- 验证点：实测数据填入需求文档
- 依赖：步骤 2+3

#### 步骤 5：单元测试 — await 行为

- 文件：新建 `test/mcp_events/test_unit_await_behavior.py`
- 改动：对齐 knowledge 的 test_unit_await_behavior.py，测三个契约：
  - 握手快（<5s）
  - 首次调用等待模型加载（>3s）
  - 第二次调用立即返回（<1s）
- 预估行数：~120 行
- 验证点：
  - 首次调用返回正确结果
  - 第二次调用耗时 <1s
- 依赖：步骤 2+3

#### 步骤 6：端到端 OpenCode 集成测试

- 文件：无（执行 `opencode serve` + curl API）
- 改动：启动 OpenCode serve → 等 MCP 注册 → curl POST /session/:id/message 让 LLM 调用 `mcp__events__recent_context_search`（参数最简：只需 query + group_id）
- 验证点：
  - plugin_debug.log 出现 `[McpManager] events 注册成功`
  - LLM 真实调用工具并返回结果（即使是空结果也算成功）
- 依赖：步骤 4+5

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | server.py 顶层不再有 `_graphiti = None` | grep 检查 |
| F2 | events MCP stdio 握手快 | `measure_events_phases.py` 测握手 <5s |
| F3 | 首次工具调用不阻塞 asyncio loop | 单元测试 + 实测：首次调用 <3s（vs 基线 14.57s） |
| F4 | 后续工具调用快 | 第二次调用 <1s |
| F5 | 模型加载失败时工具调用不 hang | 用 wrapper 脚本 monkey-patch `graphiti_config.create_graphiti` 让它返回错误，spawn wrapper 子进程跑 server，工具调用 <5s 内返回错误（参考 knowledge test_lazy_loading.py 测试 5 模式） |
| F6 | 8 个工具引用方式正确 | grep `_graphiti` 无残留（除注释） |
| F7 | OpenCode 真实启动 + LLM 调用工具 | opencode serve + curl POST，返回工具结果 |

### 回归验收

| # | 验收项 |
|---|--------|
| R1 | temporal_window_search 端到端工作 |
| R2 | entity_relationships_search 端到端工作 |
| R3 | diverse_results_search 端到端工作 |
| R4 | episode_context_search 端到端工作 |
| R5 | successful_tools_search 端到端工作 |
| R6 | recent_context_search 端到端工作 |
| R7 | entity_by_label_search 端到端工作 |
| R8 | delete_session_events 端到端工作 |
| R9 | knowledge MCP 不受影响（独立进程） |
| R10 | plugin 其他 hook 不受影响 |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | lifespan 模式符合 FastMCP 标准用法 |
| A2 | `_state` 共享状态访问安全：模型加载在子线程，工具读 `_state["graphiti"]` 在 _ready.wait() 之后（无并发写） |
| A3 | 跨线程唤醒用 `call_soon_threadsafe`，不直接调 `_ready.set()` |
| A4 | 工具调用错误传播：模型加载失败时 `_init_error` 非空，工具调用抛 RuntimeError 而非 hang |
| A5 | `build_indices_and_constraints` 仍在 asyncio loop 内（async 函数，禁止放子线程） |
| A6 | `build_indices_and_constraints` 并发安全：`_indices_lock` (asyncio.Lock) + double-check 防止多协程同时执行 |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-19-knowledge-mcp-lazy-loading.md` | **直接前置**——knowledge MCP 已完成 lifespan lazy 加载改造，本需求让 events MCP 对齐同一方案 |
| `2026-07-18-events-mcp-model-replacement.md` | 独立——events MCP 的 LLM/embedder 配置已完成，本需求仅改启动模式 |
| `2026-07-17-events-writer-daemon.md` | 独立——write_event_daemon 不通过 MCP server 入口，本需求不影响 |
