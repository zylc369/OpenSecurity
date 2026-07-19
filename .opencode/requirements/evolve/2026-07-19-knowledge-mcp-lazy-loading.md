# Knowledge MCP 启动延迟优化（lazy 加载）

## §1 背景与目标

### 来源痛点

调查 `security-analysis.ts` 中 `mcpManager.registerAll()` 的 fire-and-forget 异步模式时，发现根因是 **knowledge MCP 在 server.py 模块顶层同步加载 BGE-M3 模型（~16s），阻塞了 stdio 握手**：

```python
# knowledge/server.py:33（当前）
_embedder = SentenceTransformer("BAAI/bge-m3")  # ← 模块加载时同步执行，~16s
```

调用链：

```
plugin.setup
  └─ await registerAll()
      └─ client.mcp.add()  ← OpenCode 端发起（vendor mcp/index.ts:641）
          └─ connectLocal  ← spawn server 进程 + StdioClientTransport
              └─ 等 stdio 握手完成
                  └─ server.py 模块顶层执行（含 BGE-M3 加载，~16s）→ 阻塞
```

OpenCode 会 await plugin.setup（vendor `plugin/promise.ts:90`），如果 `registerAll` 改同步 await，启动延迟 16s+。当前用 fire-and-forget 规避，但带来首次调用 MCP 工具时可能尚未注册完成的时序风险。

### 调研验证（已完成）

| # | 验证项 | 验证方式 | 结果 |
|---|--------|---------|------|
| 1 | OpenCode 注册时与工具调用时是否同实例 | 读 `vendor mcp/index.ts:582 storeClient` + `mcp/index.ts:747 withClient` + `catalog.ts:54 client.callTool` | ✅ 同一个 mcpClient 实例、同一个 stdio pipe、同一个 server 进程 |
| 2 | FastMCP 是否支持 lifespan startup hook | 读 `mcp/server/fastmcp/server.py:173` 构造函数 | ✅ 原生支持，不传时用 default_lifespan（no-op） |
| 3 | lifespan 在 stdio `initialize` 之前执行 | 读 `mcp/server/lowlevel/server.py:663` lifespan 在 incoming_messages 循环之前 | ✅ lifespan 完成后才读 stdio |
| 4 | tools/list 是否依赖模型加载 | 读 `fastmcp/server.py:315 list_tools` | ✅ 只取 `_tool_manager.list_tools()` 元数据，不触碰模型 |
| 5 | 子线程加载 SentenceTransformer + 并发 encode 是否线程安全 | 实测脚本：`run_in_executor` 加载 + 3 个 `to_thread` 并发 encode | ✅ 加载 12.9s，并发 encode 全部成功，1024 维向量 |
| 6 | events MCP 是否需要同样改造 | 读 `events/server.py:22 _graphiti=None` + `graphiti_config.py:98 BgeM3Embedder.model` property | ✅ **已是延迟加载设计，无需改造** |

### 预期收益

| 维度 | 改进前 | 改进后 | 提升 |
|------|--------|--------|------|
| 提升分析速度 | OpenCode 启动卡 16s+（fire-and-forget 期间 MCP 不可用） | plugin.setup 几秒（见 §2.5，含 checkPackages + 两个 server 握手）；MCP 立即可用 | **首次 MCP 调用等待时间 -16s** |
| 提升结果准确度 | 极端场景：用户启动后立即调 MCP 工具，可能未注册完成返回错误 | 注册流程严格同步等待握手完成，无时序竞态 | 消除时序 bug |
| 减少对话轮次 | — | plugin 端可以从 fire-and-forget 改回 await，逻辑简化 | 维护成本下降 |

---

## §2 技术方案

### 2.1 核心机制：FastMCP lifespan + asyncio.Event

FastMCP lifespan 是一个 async context manager，在 stdio `initialize` 请求处理**之前**进入（`lowlevel/server.py:663`）。利用此特性：

- lifespan startup 内启动**后台线程**加载 BGE-M3（`loop.run_in_executor`）
- lifespan 立即 `yield`，stdio 握手快速完成
- 工具调用时 `await _ready.wait()`：模型已加载立即返回；未加载则等待

```python
import asyncio
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP

_state = {"embedder": None, "db": None}
_ready = asyncio.Event()
_init_error: list[Exception] = []
_loop: asyncio.AbstractEventLoop | None = None
_load_future = None  # 保存 run_in_executor 返回的 Future，避免 GC


def _load_blocking():
    """子线程同步加载模型 + 初始化 DB。完成后通过 call_soon_threadsafe 唤醒 Event。"""
    try:
        from sentence_transformers import SentenceTransformer
        embedder = SentenceTransformer("BAAI/bge-m3")
        db = MemoryDB(DB_PATH, embedder)
        _state["embedder"] = embedder
        _state["db"] = db
    except Exception as e:
        _init_error.append(e)
    finally:
        # Event 是主 loop 的对象，子线程必须用 call_soon_threadsafe 唤醒
        _loop.call_soon_threadsafe(_ready.set)


@asynccontextmanager
async def lifespan(app):
    global _loop, _load_future
    _loop = asyncio.get_running_loop()
    _load_future = _loop.run_in_executor(None, _load_blocking)  # fire-and-forget
    yield  # 立即返回，stdio initialize 可继续


mcp = FastMCP("knowledge", lifespan=lifespan)


async def _ensure_ready():
    """工具函数开头调用：等待模型加载完成或抛出加载错误。"""
    await _ready.wait()
    if _init_error:
        raise RuntimeError(f"BGE-M3 加载失败: {_init_error[0]}")
```

### 2.2 工具函数改造（sync → async）

所有 7 个工具改为 async，开头加 `await _ensure_ready()`：

```python
@mcp.tool(...)
async def search_answer(questions: list[str], type: str = "other", message: str = "") -> str:
    await _ensure_ready()
    db = _state["db"]
    # ... 原有逻辑，把 _db 替换为 db
```

FastMCP 支持 async 工具（直接 await 调用），客户端无感知（MCP 协议本身是 async）。

### 2.3 db.py 改动

无。`MemoryDB.__init__(db_path, embedder)` 签名不变，只是从模块顶层挪到 lifespan 内的子线程构造。

### 2.4 server.py 顶层 import 简化

```python
# 改造前（顶层加载）
from sentence_transformers import SentenceTransformer
_embedder = SentenceTransformer(MODEL_NAME)
_db = MemoryDB(DB_PATH, _embedder)

# 改造后（不在顶层加载）
# SentenceTransformer 在 _load_blocking 内 import（局部）
# MemoryDB 在 _load_blocking 内构造
```

顶层保留：FastMCP、anonymize、MemoryDB/DEFAULT_TOP_K（用于类型引用）、常量。

### 2.5 plugin 端保持 fire-and-forget（不能改 await）

**原计划改 await，但实测发现 OpenCode Plugin API 限制**：

- plugin.setup 在 Effect runtime 内 await（vendor `plugin/promise.ts:90` `yield* Effect.promise(() => Promise.resolve(plugin.setup(context2)))`）
- `client.mcp.add()` 内部依赖同一个 Effect runtime
- 如果 setup 内 `await client.mcp.add()`，Effect runtime 被阻塞无法处理 mcp.add 请求 → **死锁**
- 实测：plugin loaded 后 60s+ 无任何 McpManager 日志（被 timeout 杀掉）
- 对比：fire-and-forget 模式下，plugin loaded 后 8s 内 knowledge 注册成功、10s 内 events 注册成功

vendor `project/bootstrap.ts` 也用 `Effect.forkDetach` 让 service init() 是 fire-and-forget——印证了这是 OpenCode Plugin API 的根本约束。

**结论**：保持 fire-and-forget 模式不变。knowledge MCP 的 lifespan lazy 加载仍然有价值：
- 改造前：fire-and-forget 期间 ~15s（plugin 立即返回但 MCP 不可用窗口期长）
- 改造后：fire-and-forget 期间 ~8s（plugin 立即返回，MCP 更快可用）

时序竞态（用户启动后立即调 MCP 工具）依然存在，但窗口期从 15s 缩短到 8s。

**错误传播保障**：`mcp-manager.ts:registerOne` 内已有 try/catch（行 73、86、108）隔离单个 server 失败：
- `checkPackages` 子进程异常 → 返回 packages 全部缺失 → registerOne 跳过该 server + 日志
- `client.mcp.add` 失败 → catch + 日志，不抛出

**预期耗时**：步骤 4 实测后填入（含 checkPackages + events 握手 + knowledge 握手）。预估 3-6s（待验证）。

**基线数据（步骤 1 实测，2026-07-19）**：

| server | total（中位数） | initialize | tools |
|--------|---------------|-----------|-------|
| events | 0.67s | 0.58s | 8 |
| knowledge | 15.28s | 14.59s | 7 |

knowledge MCP 的 initialize 阶段就占用 14.59s——证明握手期间 BGE-M3 加载是阻塞源。

**改造后数据（步骤 4 实测，2026-07-19）**：

| server | total（中位数） | initialize | 改进 |
|--------|---------------|-----------|------|
| knowledge | 4.80s | 2.79s | total -68%（vs 基线 15.28s），initialize -81%（vs 基线 14.59s） |
| events（R6 回归） | 0.69s | — | 与基线 0.67s 差值 0.02s（< 0.5s 阈值，不受影响） |

剩余 2.79s 是 server.py 顶层 import + FastMCP 启动 + lifespan 启动后台任务 + initialize 请求处理 + HuggingFace HTTP HEAD 检查模型更新（log 可见多个 HTTP 请求）。可通过 `local_files_only=True` 进一步优化（超出本次范围）。

**工具调用 await 行为（步骤 5 实测，2026-07-19）**：

| 场景 | 耗时 | 验证 |
|------|------|------|
| 首次工具调用（含模型加载） | 11.47s | ✅ 等待模型加载完成 |
| 第二次工具调用（已就绪） | 0.037s | ✅ 立即返回（加速比 310x） |
| store + search 端到端 | 通过 | ✅ Frida 测试搜到 |
| 并发 3 个工具调用共享 _ready | 11.71s | ✅ 不重复加载模型 |
| 模型加载失败场景 | 0.00s | ✅ 立即返回错误 `BGE-M3 加载失败: ...` 不 hang |

**F8 plugin.setup 总耗时估算**：

components（实测）：
- checkPackages knowledge：~1-2s（同步 execFileSync）
- knowledge 握手 + tools/list：4.80s
- checkPackages events：~1-2s
- events 握手 + tools/list：0.69s
- 串行总耗时估算：**7-10s**（待用户启动 OpenCode 时实测确认）

vs 改造前 fire-and-forget：plugin.setup 立即返回，但 MCP 不可用窗口期 ~16s。改造后 plugin.setup 同步等待 ~7-10s，MCP 立即可用。

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 行数估计 |
|------|---------|---------|
| `.opencode/mcp-servers/knowledge/server.py` | 重构顶层初始化 + 7 个工具改 async | ~80 行 |
| `.opencode/mcp-servers/knowledge/db.py` | SQLite 跨线程访问（check_same_thread=False + Lock） | ~20 行 |
| `.opencode/plugins/security-analysis.ts` | 注释更新说明 fire-and-forget 必要性 | ~5 行 |
| `test/knowledge/measure_startup.py` | 新增握手耗时测量脚本（步骤 1 创建，步骤 4 复用） | ~30 行 |
| `test/knowledge/test_lazy_loading.py` | 新增工具调用 await 行为测试 | ~60 行 |

### 编码规则

1. **`_state` 字典存共享对象**：`embedder`、`db`。避免全局变量散落。
2. **`_init_error` 列表存加载异常**：工具调用时检查并抛出，避免工具 hang。
3. **`_loop` 显式保存**：子线程需要通过 `call_soon_threadsafe` 唤醒 Event，必须捕获主 loop 引用。
4. **`asyncio.Event()` 在模块顶层创建可行**：Python 3.10+ 的 `asyncio.Event` 不绑定 loop（仅在 `set()`/`wait()` 时需要 loop）。模块顶层创建 `_ready = asyncio.Event()` 安全，因为 `wait()` 总在工具函数（asyncio loop 线程）内调用，`set()` 通过 `call_soon_threadsafe` 进入主 loop。
5. **保存 `run_in_executor` 的 Future 引用**：`_load_future = _loop.run_in_executor(None, _load_blocking)`。否则加载失败时 asyncio 打印 "Future exception was never retrieved" 警告。`_load_blocking` 内已 try/except 把异常存入 `_init_error`，所以 Future 本身不会抛——但保留引用是好习惯，便于进程退出时取消。
6. **工具函数顺序保持**：answer/guide/code/memory 七个工具的相对顺序和签名不变。
7. **print 日志保留**：`[knowledge-mcp] loading embedder...` 和 `[knowledge-mcp] ready` 移到 `_load_blocking` 内（子线程输出）。
8. **plugin await 安全**：`mcp-manager.ts:registerOne` 已 try/catch 隔离单 server 失败（行 73 catch add 失败、行 108 catch checkPackages 子进程异常），await registerAll() 不会因单 server 失败而让 plugin.setup 失败。

### §3.1 实施步骤拆分

#### 步骤 1：基线测量 — 当前启动耗时

- 文件：新建 `test/knowledge/measure_startup.py`（本步骤创建，步骤 4 复用）
- 改动：
  - 写脚本：spawn server 进程 + stdio 握手 + tools/list，测总耗时
  - 支持 `--server events/knowledge` 参数切换
  - 分别测量 events MCP 和 knowledge MCP 当前的握手耗时
- 验证方式：
  ```bash
  ~/bw-security-analysis/.venv/bin/python test/knowledge/measure_startup.py --server events
  ~/bw-security-analysis/.venv/bin/python test/knowledge/measure_startup.py --server knowledge
  ```
- 预期：events <2s（已是延迟加载）；knowledge ~16s（模块顶层加载 BGE-M3）
- 验证点：基线数据记录到需求文档 §2.5
- 依赖：无（脚本本步骤创建）

#### 步骤 2：server.py 顶层重构 + lifespan 引入

- 文件：`.opencode/mcp-servers/knowledge/server.py`
- 改动：
  - 删除顶层 `_embedder = SentenceTransformer(...)` 和 `_db = MemoryDB(...)`
  - 删除顶层 `from sentence_transformers import SentenceTransformer`
  - 新增 `_state`、`_ready`、`_init_error`、`_loop`、`_load_future` 全局
  - 新增 `_load_blocking()` 函数（子线程入口）
  - 新增 `lifespan()` async context manager（保存 Future 引用）
  - `mcp = FastMCP("knowledge", lifespan=lifespan)`
  - 新增 `_ensure_ready()` async 函数
- 预估行数：~50 行（新增 +55 行 / 删除 -5 行）
- 验证点：
  - `python -c "compile(open('...').read(), '...', 'exec')"` 语法通过
  - server.py 顶层不再 import SentenceTransformer
  - `mcp` 实例的 lifespan 不为 None
- 依赖：步骤 1（基线）

#### 步骤 3：7 个工具函数改 async + 加 `_ensure_ready()`

- 文件：`.opencode/mcp-servers/knowledge/server.py`
- 改动：
  - `search_answer`、`store_answer`、`search_guide`、`store_guide`、`search_code`、`store_code`、`search_in_memory` 全部改为 `async def`
  - 函数体开头加 `await _ensure_ready()`
  - 函数体内把全局 `_db` 替换为 `_state["db"]`
- 预估行数：~30 行（7 个函数 × ~4 行改动）
- 验证点：
  - 语法通过
  - 所有 7 个工具签名都是 `async def`
  - grep `^def ` 在文件中无 MCP 工具函数残留（只剩下非工具辅助函数）
- 依赖：步骤 2

#### 步骤 4：端到端验证 — knowledge 握手耗时

- 文件：无（执行验证）
- 改动：用步骤 1 同样的脚本测改造后的 knowledge MCP 启动耗时
- 预期：从 ~16s 降到 <2s（只剩 FastMCP 启动 + lifespan startup 开销，不 await 模型加载）。实测后填入 §2.5。
- 验证方式：
  ```bash
  ~/bw-security-analysis/.venv/bin/python test/knowledge/measure_startup.py --server knowledge
  ```
- 依赖：步骤 2+3

#### 步骤 5：端到端验证 — 工具调用 await 行为

- 文件：新建 `test/knowledge/test_lazy_loading.py`
- 改动：
  - 启动 server 后立即调用 `search_answer`，测量耗时（应等于模型加载时间 + encode 时间）
  - 第二次调用 `search_answer`，测量耗时（应 <0.5s，模型已就绪）
  - 模拟加载失败：mock SentenceTransformer 抛异常，工具调用应返回 error 而非 hang
- 预估行数：~60 行
- 验证点：
  - 首次工具调用返回正确结果（dim=1024 向量生效）
  - 第二次工具调用耗时 <0.5s
  - 加载失败场景工具调用不 hang（在合理 timeout 内返回错误）
- 依赖：步骤 2+3

#### 步骤 6：plugin security-analysis.ts 注释更新

- 文件：`.opencode/plugins/security-analysis.ts`
- 改动：
  - 更新注释说明 fire-and-forget 是 OpenCode Plugin API 强制要求（不能改 await，否则死锁）
  - 代码本身保持原样（fire-and-forget + .catch）
- 预估行数：~5 行（仅注释改动）
- 验证点：
  - `node --check security-analysis.ts` 通过
  - 启动 OpenCode 后 plugin_debug.log 在 ~10s 内出现 `[McpManager] knowledge 注册成功`
- 依赖：步骤 4（确保握手确实快了）

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | server.py 顶层不再加载模型 | `python -c "import server"` 完成时间 <1s（测模块顶层 import 时间，非握手时间——import 触发顶层代码执行，若顶层加载模型会卡 ~16s） |
| F2 | 单 server stdio 握手快 | knowledge MCP 通过 `measure_startup.py` 测耗时 <2s（plugin setup 总耗时见 §2.5，含 checkPackages + events + knowledge 串行） |
| F3 | 首次工具调用成功 | 模型加载完后返回正确结果（dim=1024 向量） |
| F4 | 后续工具调用快 | 第二次调用耗时 <0.5s |
| F5 | 模型加载失败时工具调用不 hang | 模拟加载异常，工具调用在 5s 内返回 error |
| F6 | plugin.setup 同步 await | **❌ 不可行**：OpenCode Plugin API 限制——plugin.setup 在 Effect runtime 内 await，setup 内 await client.mcp.add 会死锁。保持 fire-and-forget 模式（实测 plugin loaded 后 ~10s 内 MCP 注册完成） |
| F7 | 7 个工具全部改 async | `grep -E "^async def (search_answer\|store_answer\|search_guide\|store_guide\|search_code\|store_code\|search_in_memory)"` 全部匹配（7 行） |
| F8 | plugin.setup 后 MCP 可用耗时合理 | 实测：fire-and-forget 后 ~8s knowledge 注册、~10s events 注册（vs 改造前 ~15s+） |

### 回归验收

| # | 验收项 |
|---|--------|
| R1 | search_answer/store_answer 端到端正常工作（store 后能搜到） |
| R2 | search_guide/store_guide 端到端正常工作 |
| R3 | search_code/store_code 端到端正常工作 |
| R4 | search_in_memory 端到端正常工作 |
| R5 | 匿名化仍生效（store 含 IP 的文本，搜索结果 IP 被替换） |
| R6 | events MCP 启动耗时不变（用步骤 1 的 `measure_startup.py --server events` 在改造前后对比，差值 <0.5s） |
| R7 | plugin 其他 hook 不受 await registerAll 影响（启动 OpenCode + 发送一条测试消息，确认 chat.message/system.transform 正常触发：session 数据写入 + system prompt 注入）—— 实测 fire-and-forget 模式下 plugin loaded 后 chat.message/system.transform 立即工作（`plugin_debug.log` 18:28:50 显示 session.idle/system.transform 触发） |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | lifespan 模式符合 FastMCP 标准用法（参考 `fastmcp/server.py:173`） |
| A2 | `_state` 共享状态访问安全：写只在子线程加载完后发生一次（通过 Event 同步），读在工具函数（asyncio loop 线程）—— 无并发写 |
| A3 | 跨线程唤醒用 `call_soon_threadsafe`，不用 `Event.set()` 直接调用（子线程不允许直接操作主 loop 的 asyncio 对象） |
| A4 | 工具调用错误传播：模型加载失败时 `_init_error` 非空，工具调用抛 RuntimeError 而非 hang |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-19-knowledge-mcp-align-pentagi.md` | **直接前置**——align pentagi 完成了功能改造（embed content、4 类别、匿名化、memory 自动写入），本需求解决"启动慢"的性能问题。两者改造的 server.py 是同一个文件，但改动位置不冲突 |
| `2026-07-18-events-mcp-model-replacement.md` | 独立——events MCP 已是延迟加载设计（`_ensure_ready()` + property lazy），本需求让 knowledge MCP 对齐 events MCP 的启动模式 |
