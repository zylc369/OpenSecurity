# 需求：推理串行化收口——LockedEmbedder/LockedReranker 包装（方案A）

> 日期：2026-09-25
> 状态：**已完成**（progress-2026-09-25-locked-embedder.md；运行中控制台 pid 8757 已加载新代码）
> 前置：工作区存在未提交的临时修复（D 方案：`knowledge_db._embed` 手动持 `infer_lock()`），本需求落地时**吸收并清零 D 的痕迹**。

## §1 背景与目标

**来源**：2026-09-25 控制台两次运行期 SIGSEGV 崩溃（13:43 pid=55575 / 14:02 pid=56114）复盘。

**根因链**（证据等级 observed，详见分析台账）：

- L1 物理：torch 2.14 MPS 后端线程不安全——`MetalShaderLibrary` 的 shader kernel 缓存（`std::unordered_map`）无锁，两线程并行进入 MPS 计算即数据竞争→堆损坏。两份 `.ips` 崩溃报告均显示崩溃瞬间双线程同处 MPS 原生代码（第二次两线程栈逐帧相同）。
- L2 架构：单 BGE-M3 单例被五条异步管道共享（graphiti 事件 / memory 写 worker / 同步搜索 / /embed / /rerank），plugin 对每次工具执行并发投递 events+memory 两条，碰撞是常态。
- L3 代码：`MemoryDB._embed` 持注入的裸 `SentenceTransformer` 直接 encode，绕过 `_infer_lock`。
- L4 API：`model_loader` 声明"其他模块禁止直接用模型"契约，但 `get_embedder()/get_reranker()` 返回裸模型单例——契约靠注释，API 主动递刀，纪律防线已实证失效。
- L5 防御：无运行时监护、崩溃不隔离、运行期无自动重拉。

**临时修复（D，已在工作区）**：`_embed` 手动持公开锁 `model_loader.infer_lock()`。定性为止血——维持"靠每个调用点记得持锁"的纪律模式，并引入"裸模型引用 + 内部持锁函数 + 公开锁句柄"三种能力并存的新隐患（`threading.Lock` 不可重入，组合即死锁）。

**目标**：把"所有推理必须串行"不变量从纪律约束升级为**构造保证**——锁下沉到模型访问层，消费方拿到的对象天然线程安全，绕过在结构上无路可走。同时清零 D 痕迹、删除裸引用死出口、修复 search 逐条 embed 的性能问题。

**四维度量预期**：
- 准确度：消除 SIGSEGV 复发路径（当前 D 修复已止血，本需求消灭复发**机制**而非单个实例）
- 速度：`search()` 多问题从 N 次前向+N 次锁获取 → 1 次批量前向+1 次锁
- 上下文/轮次：不适用（基础设施修复）

## §2 技术方案

### 2.1 核心机制：锁下沉到包装类

`model_loader.py` 新增两个包装类，`_infer_lock` 成为包装的私有实现细节：

```python
class LockedEmbedder:
    """SentenceTransformer 的线程安全包装。

    MPS 后端多线程并发推理数据竞争（MetalShaderLibrary 无锁缓存）——串行
    不变量由本包装在构造上保证：encode 即持锁，消费方无法绕过。
    duck-type 面与 SentenceTransformer.encode / 测试 fake 一致。
    """
    __slots__ = ("_inner",)

    def __init__(self, inner: "SentenceTransformer") -> None:
        self._inner = inner

    def encode(self, sentences, **kwargs):
        with _infer_lock:
            return self._inner.encode(sentences, **kwargs)


class LockedReranker:
    """CrossEncoder 的线程安全包装（同 LockedEmbedder 语义）。"""
    __slots__ = ("_inner",)

    def __init__(self, inner: "CrossEncoder") -> None:
        self._inner = inner

    def predict(self, pairs, **kwargs):
        with _infer_lock:
            return self._inner.predict(pairs, **kwargs)
```

### 2.2 对外接口变更（get_* 返回包装）

```python
# 模块状态：裸引用仅模块内部可见（加载管理/ready 判断用）
_embedder: "SentenceTransformer | None" = None
_locked_embedder: "LockedEmbedder | None" = None      # 对外唯一出口
_reranker: "CrossEncoder | None" = None
_locked_reranker: "LockedReranker | None" = None

def get_embedder() -> "LockedEmbedder":
    """双重检查锁定加载，返回线程安全包装（永不返回裸模型）。"""
    ...
def get_reranker() -> "LockedReranker": ...
```

`is_models_ready()` / `is_reranker_loaded()` 判断逻辑不变（继续看 `_embedder`/`_reranker` 裸引用是否已加载）。

### 2.3 内部推理函数收口（锁逻辑唯一化 + 消除重复）

锁获取点全进程收敛为包装内部一处。`*_sync` 函数去掉手动锁，直接调包装：

```python
def embed_batch_sync(texts: list[str]) -> list[list[float]]:
    vecs = get_embedder().encode(texts, convert_to_numpy=True)   # 锁在包装内
    return [np.asarray(v).tolist() for v in vecs]

def embed_sync(text: str) -> list[float]:
    vec = get_embedder().encode(text, convert_to_numpy=True)
    return np.asarray(vec).tolist()

def rerank_sync(query: str, passages: list[str]) -> list[float]:
    pairs = [(query, p) for p in passages]
    scores = get_reranker().predict(pairs)
    return [float(s) for s in np.asarray(scores)]

# async 包装不变（to_thread 委托 sync 函数）
async def embed_async(inputs): return await asyncio.to_thread(embed_batch_sync, inputs)
async def rerank_async(query, texts): return await asyncio.to_thread(rerank_sync, query, texts)
```

**消除既有重复**（规则2）：原 `_do_embed` 与 `embed_batch_sync` 实现相同、`_do_rerank` 与 `rerank_sync` 实现相同——合并为后者，`_do_*` 删除。

**死锁消除**：D 修复后系统存在"包装锁 + `*_sync` 手动锁"叠加即死锁的风险面；收口后锁只在包装内获取一次。

### 2.4 D 痕迹清零

- 删除 `model_loader.infer_lock()` 公开 contextmanager
- `knowledge_db._embed` 删除 `with model_loader.infer_lock():`，恢复直接 `self.embedder.encode(...)`（此时 self.embedder 已是 LockedEmbedder）

### 2.5 死出口删除

`graphiti_config.BgeM3Embedder.model` 与 `reranker.BgeRerankerClient.model` 两个 property 删除——已验证 graphiti_core 从不访问 `.model`（grep 全库零引用），纯风险零收益。

### 2.6 search 批量化（性能顺带修复）

`knowledge_db.py`：

```python
def _embed(self, text: str) -> bytes:            # 单条（store 用）
    vec = self.embedder.encode(text, convert_to_numpy=True)
    return struct.pack(f"{EMBEDDING_DIM}f", *vec.tolist())

def _embed_batch(self, texts: list[str]) -> list[bytes]:   # 新增：批量
    vecs = self.embedder.encode(texts, convert_to_numpy=True)
    return [struct.pack(f"{EMBEDDING_DIM}f", *v.tolist()) for v in vecs]

# search() 内：q_embs = [self._embed(q) for q in questions]
#          改为：q_embs = self._embed_batch(questions)
```

N 个问题：N 次前向+N 次锁获取 → 1 次批量前向+1 次锁。FakeEmbedder 批量路径返回 2-D ndarray，迭代兼容。

### 2.7 测试注入兼容

`embedder_factory` 注入机制不变。测试 fake 实现 `encode(inputs, **kw)` 同协议即可；单线程测试下 fake 无锁无影响。`EmbedderLike` Protocol 文档更新（生产注入 LockedEmbedder）。

### 2.8 架构影响

改动收敛在 `control/backend` 进程内，无 IPC/路由/数据格式变更。涉及 3 个以上文件，影响图：

```
model_loader.py（核心：包装类 + get_* + 收口）
  ├── knowledge_store.py     _ensure_db 注入 get_embedder() → 自动获得包装（代码不变，注释更新）
  │     └── knowledge_db.py  _embed/_embed_batch/search（去锁+批量化）
  ├── graphiti_config.py     BgeM3Embedder：删 .model property、_encode_locked 更名 _encode
  ├── reranker.py            BgeRerankerClient：删 .model property
  └── routes/embed.py        经 embed_async/rerank_async（函数签名不变，零改动）
```

## §3 实现规范

### 3.0 改动范围表

| 文件 | 改动内容 | 性质 |
|---|---|---|
| `services/model_loader.py` | LockedEmbedder/LockedReranker；get_* 返回包装；`*_sync` 收口去锁；删 `_do_embed`/`_do_rerank`/`infer_lock()`；头部文档更新 | 核心重构 |
| `services/knowledge_db.py` | `_embed` 去 D 锁；新增 `_embed_batch`；`search` 批量化；Protocol 文档 | 去 D + 性能 |
| `services/knowledge_store.py` | 头部注释（并发安全表述改为"由 LockedEmbedder 保证"） | 文档 |
| `services/graphiti_config.py` | 删 `.model` property；`_encode_locked`→`_encode` | 死出口清理 |
| `services/reranker.py` | 删 `.model` property | 死出口清理 |
| `tests/test_control.py` | 新增 LockedEmbedder 互斥性回归测试 | 测试 |

编码规则：遵守规则 9（`__slots__`、类型注解、无裸 dict）；每文件改后 `py_compile`；锁获取点唯一化后 grep 验证。

### §3.1 实施步骤拆分

**步骤 1**：model_loader.py 全部改动（包装类 + get_* 返回包装 + 内部函数收口 + 删 infer_lock/`_do_*`）
- 文件：`services/model_loader.py`
- 预估行数：~90
- 验证点：`py_compile` 通过；`grep -n "_do_embed\|_do_rerank\|def infer_lock" model_loader.py` 零残留；`get_embedder` 返回类型注解为 LockedEmbedder
- 依赖：无
- ⚠ 原子性要求：get_* 返回包装与内部函数去手动锁**必须同一步完成**（Lock 不可重入，分步会出现包装锁+函数锁叠加死锁）

**步骤 2**：knowledge_db.py 去 D 锁 + `_embed_batch` + search 批量化
- 文件：`services/knowledge_db.py`
- 预估行数：~25
- 验证点：`py_compile`；运行 `test_control.py` 中 `test_knowledge_store_paths` 与 `test_knowledge_events_routes`（fake 注入路径，验证批量兼容）
- 依赖：步骤 1（否则 `_embed` 去锁后无串行保护）

**步骤 3**：graphiti_config.py + reranker.py 死出口删除与更名
- 文件：`services/graphiti_config.py`、`services/reranker.py`
- 预估行数：~15
- 验证点：`py_compile` ×2；`grep -rn "\.model\b" services/graphiti_config.py services/reranker.py` 零 property 定义；全后端 grep 无 `.model` 消费
- 依赖：步骤 1

**步骤 4**：knowledge_store.py 与 model_loader.py 头部并发模型文档更新
- 文件：`services/knowledge_store.py`、`services/model_loader.py`
- 预估行数：~10
- 验证点：人工审读——文档描述"串行由包装保证、模块外无锁概念"，与实现一致
- 依赖：步骤 1

**步骤 5**：新增回归测试（LockedEmbedder/LockedReranker 互斥性）
- 文件：`tests/test_control.py`
- 预估行数：~35
- 验证点：测试通过——两线程并发调 `LockedEmbedder(fake).encode`，用带内部并发计数器的 fake（进入 +1、睡眠、退出 -1，断言计数器峰值 ≤1）验证互斥；同协议验证 LockedReranker.predict
- 依赖：步骤 1

**步骤 6**：端到端验证（重启控制台 + 并发观测）
- 文件：无代码改动
- 验证点：
  1. 重启控制台（同参 spawn，加载新代码），`/health` 200
  2. plugin 心跳重注册（control.log「新 opencode 注册」）
  3. 并发双管道活跃下无崩溃：episode 持续入库 + `store_knowledge` 成功 + 无新增 `.ips`
  4. `knowledge_search` / `events_time_search` MCP 正常返回
- 依赖：步骤 1-5 全部

## §4 验收标准

**功能验收**：
1. 并发推理互斥：回归测试证明包装的 encode/predict 互斥（峰值并发 ≤1）
2. `search()` 批量路径功能等价：fake 测试（结构断言）+ 线上检索正常
3. 控制台全链路正常：health / heartbeat / episode 入库 / store_knowledge / knowledge_search / events 检索

**回归验收**：
1. `tests/test_control.py` 相关用例（knowledge_store 路径、knowledge/events 路由、fake 注入）全部通过
2. `/embed`、`/rerank` 路由行为不变（请求/响应格式零变更）
3. graphiti episode 入库正常（真实运行观测）
4. `is_models_ready`/`is_reranker_loaded` 语义不变（/health 加载期 503 行为不变）

**架构验收**：
1. `grep -rn "_infer_lock" services/ | grep -v model_loader` → 零结果（锁不出模块）
2. `grep -rn "infer_lock\|_do_embed\|_do_rerank" services/` → 零结果（D 痕迹与合并残留清零）
3. `grep -n "def model" services/graphiti_config.py services/reranker.py` → 零结果（死出口清零）
4. 锁获取点唯一：`grep -c "with _infer_lock" services/model_loader.py` == 2（LockedEmbedder.encode + LockedReranker.predict 各一）
5. 运行期观测 ≥10 分钟并发活动无新 `.ips` 崩溃报告

## §5 与现有需求文档的关系

- `2026-08-17-mcp-ocr-standard-consolidation.md` / `2026-08-22-ocr-in-process.md`：OCR 的 MLX 串行化（thread-local Metal stream）是同类问题的独立处理，本需求不触碰 ocr_service（其已有自己的 GPU 串行机制），但模式一致（GPU 推理串行），未来如出现第三处 GPU 模型接入，应复用本需求的包装模式。
- 本需求不与任何在办需求冲突；`progress-*.md` 机制照常使用（本文件同目录落 `progress-2026-09-25-locked-embedder.md`）。
