# Embed Server：本地模型统一 HTTP 服务

## §1 背景与目标

### 1.1 来源

实测发现 4 个 MCP 进程各自独立加载 BGE-M3 模型，总内存 ~13 GB：

| 进程 | 加载的模型 | 内存 |
|------|-----------|------|
| `knowledge/server.py` | BGE-M3（1.0 GB） | ~3 GB |
| `knowledge/memory_writer_daemon.py` | BGE-M3（1.0 GB）← **重复** | ~3 GB |
| `events/server.py` | BGE-M3（1.0 GB） | ~3.5 GB |
| `events/write_event_daemon.py` | BGE-M3（1.0 GB）← **重复** | ~3.5 GB |

根因：4 个进程是独立 Python 进程，无共享内存。同一个 2.4 GB 的 BGE-M3 模型被加载了 4 次。

### 1.2 目标

新建 `embed_server.py`——单进程加载 BGE-M3（+ 可选 Reranker），通过 HTTP 对外提供嵌入/重排序服务。4 个 MCP 进程改为 HTTP 客户端，不再各自加载模型。

**改造后内存**：~13 GB → **~1.5 GB**（embed_server 1.0 GB + 4 个瘦客户端各 ~50 MB + Python 基础开销 0.3 GB）。

### 1.3 架构设计

```
                     embed_server.py（单进程, ~1.3 GB）
                     ┌────────────────────────────────┐
                     │  BGE-M3 model（CPU, 懒加载）    │
                     │  BGE-Reranker model（CPU, 懒）  │
                     │  starlette + uvicorn            │
                     │                                 │
                     │  POST /embed   → 向量化         │
                     │  POST /rerank  → 重排序         │
                     │  GET  /health  → 健康检查       │
                     │  127.0.0.1:9776                 │
                     └───┬───────┬───────┬───────┬─────┘
                         │       │       │       │
            ┌────────────┘       │       │       └────────────┐
            │                    │       │                    │
  ┌─────────▼─────────┐ ┌───────▼─────┐ ┌▼─────────────┐ ┌───▼──────────────┐
  │ knowledge/        │ │ knowledge/  │ │ events/      │ │ events/          │
  │ server.py         │ │ memory_     │ │ server.py    │ │ write_event_     │
  │                   │ │ writer_     │ │              │ │ daemon.py        │
  │ HttpEmbedClient   │ │ daemon.py   │ │ HttpEmbed-   │ │ HttpEmbedClient  │
  │ (~50 MB)          │ │ HttpEmbed-  │ │ Client       │ │ (~50 MB)         │
  │                   │ │ Client      │ │ (~50 MB)     │ │                  │
  │ encode()→HTTP     │ │ (~50 MB)    │ │ encode()→HTTP│ │ encode()→HTTP    │
  └───────────────────┘ └─────────────┘ └──────────────┘ └──────────────────┘
```

### 1.4 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| HTTP 框架 | starlette（已有）+ uvicorn（已有） | FastAPI 多出的 Pydantic/依赖注入/Swagger 都不需要；输入就是字符串，手动 if 校验够用 |
| 设备 | CPU（不加 MPS） | 当前 4 个进程都是 CPU，保持一致；MPS 虽然实测可用但不在这轮改动范围 |
| 客户端接口 | duck-type 兼容 SentenceTransformer.encode() 和 CrossEncoder.predict() | 消费方代码（db.py、graphiti_config.py、reranker.py）零改动 |
| 端口 | 9776 | 可通过 `EMBED_SERVER_PORT` 环境变量配置 |
| 生命周期 | detect_env.py 管理（与 Docker/Neo4j 并列） | 已有基础设施管理框架，复用 |
| 降级策略 | embed_server 不可用时，MCP server 回退到本地加载模型 | 向后兼容，安装后首次运行无需立即重启 |

---

## §2 技术方案

### 2.1 新文件：`mcp-servers/embed_server.py`

独立的 HTTP 服务进程。懒加载模型，通过 starlette 提供 REST API。

**核心结构**：

```python
"""本地模型 HTTP 服务。

加载 BGE-M3（嵌入）和 BGE-Reranker（重排序），通过 HTTP 对外提供推理服务。
所有 MCP 进程通过 embed_client.py 调用本服务，避免重复加载模型。

启动：python embed_server.py（由 plugin.setup 和 detect_env.py install 管理）
端口：默认 9776，可通过 EMBED_SERVER_PORT 环境变量配置

并发模型：starlette ASGI + asyncio.to_thread
  - encode/predict 是 CPU-bound 同步调用，用 to_thread 交给线程池
  - 不阻塞 event loop，多个 MCP 进程可并发请求
"""
import asyncio
import os

# 避免 SentenceTransformer 加载时向 HuggingFace 发 HEAD 请求（网络不通会卡 120s+）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import numpy as np
import threading
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.responses import JSONResponse
from starlette.requests import Request
import uvicorn

EMBED_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
PORT = int(os.environ.get("EMBED_SERVER_PORT", "9776"))

# 懒加载模型（线程安全 double-check）
_embedder = None
_reranker = None
_embed_lock = threading.Lock()
_rerank_lock = threading.Lock()


def get_embedder():
    global _embedder
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                from sentence_transformers import SentenceTransformer
                print(f"[embed-server] loading {EMBED_MODEL}...", flush=True)
                _embedder = SentenceTransformer(EMBED_MODEL)
                print(f"[embed-server] {EMBED_MODEL} ready", flush=True)
    return _embedder


def get_reranker():
    global _reranker
    if _reranker is None:
        with _rerank_lock:
            if _reranker is None:
                from sentence_transformers import CrossEncoder
                print(f"[embed-server] loading {RERANKER_MODEL}...", flush=True)
                _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
                print(f"[embed-server] {RERANKER_MODEL} ready", flush=True)
    return _reranker


# ── 同步推理函数（在线程池中执行）──────────────────────────

def _do_embed(inputs):
    model = get_embedder()
    vecs = model.encode(inputs, convert_to_numpy=True)
    return [v.tolist() for v in vecs]


def _do_rerank(query, texts):
    model = get_reranker()
    pairs = [(query, t) for t in texts]
    scores = model.predict(pairs)
    return [float(s) for s in np.asarray(scores)]


# ── ASGI 路由处理（async，推理交线程池）────────────────────

async def embed(request: Request):
    data = await request.json()
    inputs = data.get("inputs") or data.get("input")
    if not inputs:
        return JSONResponse({"error": "missing 'inputs'"}, status_code=400)
    if isinstance(inputs, str):
        inputs = [inputs]
    result = await asyncio.to_thread(_do_embed, inputs)
    return JSONResponse(result)


async def rerank(request: Request):
    data = await request.json()
    query = data.get("query")
    texts = data.get("texts")
    if not query or not texts:
        return JSONResponse({"error": "missing 'query' or 'texts'"}, status_code=400)
    result = await asyncio.to_thread(_do_rerank, query, texts)
    return JSONResponse(result)


async def health(request: Request):
    return JSONResponse({"status": "ok"})


app = Starlette(routes=[
    Route("/embed", embed, methods=["POST"]),
    Route("/rerank", rerank, methods=["POST"]),
    Route("/health", health, methods=["GET"]),
])

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
```

### 2.2 新文件：`mcp-servers/embed_client.py`

HTTP 客户端，duck-type 兼容 SentenceTransformer.encode() 和 CrossEncoder.predict()。

**适配关系**：

```
当前消费方代码                          改造后
─────────────────                      ─────────────────
db.py:113                              db.py:113（不改）
  self.embedder.encode(text,             self.embedder.encode(text,
    convert_to_numpy=True)                 convert_to_numpy=True)
  ↓                                     ↓
  SentenceTransformer.encode()          HttpEmbedClient.encode()
  （本地加载模型，2.4GB）                （发 HTTP 请求，~50MB）

graphiti_config.py:181                  graphiti_config.py:181（不改）
  self.model.encode(text, ...)           self.model.encode(text, ...)
  ↓                                     ↓
  SentenceTransformer.encode()          HttpEmbedClient.encode()
  （通过 @property model 延迟加载）      （@property model 返回 HttpEmbedClient）

reranker.py:63                          reranker.py:63（不改）
  self.model.predict(pairs)             self.model.predict(pairs)
  ↓                                     ↓
  CrossEncoder.predict()                HttpEmbedClient.predict()
```

**核心结构**：

```python
"""嵌入/重排序 HTTP 客户端。

duck-type 兼容 SentenceTransformer.encode() 和 CrossEncoder.predict()。
消费方（db.py、graphiti_config.py、reranker.py）代码零改动。

embed_server 不可用时自动回退到本地加载模型（向后兼容）。
"""
import os
import httpx
import numpy as np

DEFAULT_URL = f"http://127.0.0.1:{os.environ.get('EMBED_SERVER_PORT', '9776')}"
EMBED_MODEL = "BAAI/bge-m3"
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
TIMEOUT = 30.0


class HttpEmbedClient:
    """适配 SentenceTransformer.encode() + CrossEncoder.predict() 的 HTTP 客户端。

    embed_server 可用时：所有请求走 HTTP（~50MB 内存）。
    embed_server 不可用时：首次请求失败后回退到本地加载（向后兼容，~1GB 内存）。
    """

    def __init__(self, base_url=DEFAULT_URL, model_name=EMBED_MODEL):
        self._base_url = base_url
        self._client = httpx.Client(timeout=TIMEOUT)
        self._model_name = model_name
        self._fallback = None  # 回退用的本地 SentenceTransformer/CrossEncoder
        self._confirmed_available = False  # HTTP 首次成功后置 True，跳过重试

    def _try_http(self, endpoint, payload):
        """尝试 HTTP 请求。首次调用时重试 3 次（间隔 1s），给 embed_server 加载时间。
        后续调用不重试（embed_server 已就绪或已确认不可用）。
        """
        max_retries = 3 if not self._confirmed_available else 1
        for attempt in range(max_retries):
            try:
                resp = self._client.post(f"{self._base_url}{endpoint}", json=payload)
                resp.raise_for_status()
                self._confirmed_available = True  # 标记 HTTP 可用
                return resp.json()
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                if attempt < max_retries - 1:
                    import time; time.sleep(1)
                    continue
                self._confirmed_available = False
                return None
            except httpx.HTTPStatusError:
                self._confirmed_available = False
                return None

    def encode(self, inputs, convert_to_numpy=True, **kwargs):
        """适配 SentenceTransformer.encode()。

        签名兼容：接受 str 或 list[str]，返回 np.ndarray。
        **kwargs 吃掉 convert_to_numpy、batch_size 等参数（HTTP 不需要）。
        """
        if isinstance(inputs, str):
            inputs = [inputs]
        data = self._try_http("/embed", {"inputs": inputs})
        if data is not None:
            return np.array(data)
        # 回退到本地加载
        return self._fallback_encode(inputs)

    def predict(self, pairs, **kwargs):
        """适配 CrossEncoder.predict()。

        签名兼容：接受 list[(query, passage)]，返回 np.ndarray。
        **kwargs 吃掉 batch_size、activation_fn 等参数。

        注意：当前所有调用方（reranker.py:63）的 pairs 共享同一 query，
        HTTP /rerank 端点也假设单一 query。如果未来需要多 query 场景，
        需改为多次 HTTP 请求或扩展 API。
        """
        if not pairs:
            return np.array([])
        query = pairs[0][0]
        texts = [p[1] for p in pairs]
        data = self._try_http("/rerank", {"query": query, "texts": texts})
        if data is not None:
            return np.array(data)
        return self._fallback_predict(pairs)

    def _fallback_encode(self, inputs):
        if self._fallback is None:
            from sentence_transformers import SentenceTransformer
            self._fallback = SentenceTransformer(self._model_name)
        return self._fallback.encode(inputs, convert_to_numpy=True)

    def _fallback_predict(self, pairs):
        if self._fallback is None:
            from sentence_transformers import CrossEncoder
            self._fallback = CrossEncoder(RERANKER_MODEL, max_length=512)
        return self._fallback.predict(pairs)
```

### 2.3 改造文件清单

#### 2.3.1 `mcp-servers/knowledge/server.py`（~15 行改动）

`_load_blocking()` 函数内：

```python
# 当前（第48-49行）：
from sentence_transformers import SentenceTransformer
embedder = SentenceTransformer(MODEL_NAME)

# 改为：
from embed_client import HttpEmbedClient
embedder = HttpEmbedClient(model_name=MODEL_NAME)
```

db.py 不改——它接收的 embedder 参数从 SentenceTransformer 变成 HttpEmbedClient，但调用的 `.encode()` 签名完全一致。

#### 2.3.2 `mcp-servers/knowledge/memory_writer_daemon.py`（~5 行改动）

`main()` 函数内（第25-27行）：

```python
# 当前：
from sentence_transformers import SentenceTransformer
embedder = SentenceTransformer("BAAI/bge-m3")

# 改为：
from embed_client import HttpEmbedClient
embedder = HttpEmbedClient()
```

#### 2.3.3 `mcp-servers/events/graphiti_config.py`（~15 行改动）

`BgeM3Embedder` 类内：

```python
# 当前（第149-160行）：
class BgeM3Embedder(EmbedderClient):
    def __init__(self):
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer("BAAI/bge-m3")
        return self._model

# 改为：
class BgeM3Embedder(EmbedderClient):
    def __init__(self):
        from embed_client import HttpEmbedClient
        self._model = HttpEmbedClient()

    @property
    def model(self):
        return self._model
```

create/create_batch 方法不改——它们调用 `self.model.encode()`，HttpEmbedClient 有同名方法。

#### 2.3.4 `mcp-servers/events/reranker.py`（~10 行改动）

`BgeRerankerClient` 类内：

```python
# 当前（第32-44行）：
class BgeRerankerClient(CrossEncoderClient):
    def __init__(self):
        self._model: Any = None

    @property
    def model(self):
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
        return self._model

# 改为：
class BgeRerankerClient(CrossEncoderClient):
    def __init__(self):
        from embed_client import HttpEmbedClient
        self._model = HttpEmbedClient()

    @property
    def model(self):
        return self._model
```

rank 方法不改——它调用 `self.model.predict(pairs)`，HttpEmbedClient 有同名方法。

#### 2.3.5 `mcp-servers/events/server.py`（~3 行改动）

`_preload_models_blocking()` 函数内（第188行）：

```python
# 当前：
_ = graphiti.embedder.model  # 触发 BGE-M3 加载（@property）

# 改为：
_ = graphiti.embedder.model  # 触发 HttpEmbedClient 初始化（不再加载本地模型）
# 检查 embed_server 是否可用
import httpx
try:
    r = httpx.get(f"http://127.0.0.1:{os.environ.get('EMBED_SERVER_PORT', '9776')}/health", timeout=2)
    if r.status_code == 200:
        print("[events-mcp] embed_server 可用", file=sys.stderr)
    else:
        print("[events-mcp] embed_server 不可用，将回退到本地加载", file=sys.stderr)
except Exception:
    print("[events-mcp] embed_server 不可用，将回退到本地加载", file=sys.stderr)
```

#### 2.3.6 `mcp-servers/events/write_event_daemon.py`（~2 行改动）

create_graphiti 内部已经通过 BgeM3Embedder 使用 model，改造后自动走 HTTP。无需额外改动。只需确保 import 路径正确。

#### 2.3.7 `binary-analysis/scripts/detect_env.py`（~50 行改动）

##### a) PYTHON_PACKAGES 新增依赖（第282行区域）

```python
Dependency(name="psutil", kind="python", pip_name="psutil", preinstall=True,
           agents=["all"],
           description="进程/内存监控库，embed_server 和诊断工具依赖"),
```

starlette、uvicorn、httpx 已安装，不需要新增。sentence-transformers 已在列表中。

##### b) embed_server 启动/检测函数（新增 ~50 行）

```python
EMBED_SERVER_PORT = int(os.environ.get("EMBED_SERVER_PORT", "9776"))


def _check_embed_server():
    """检测 embed_server 是否运行（只读，不启动）。
    返回 (running: bool, message: str)。
    """
    import urllib.request
    try:
        req = urllib.request.urlopen(
            f"http://127.0.0.1:{EMBED_SERVER_PORT}/health", timeout=2
        )
        if req.status == 200:
            return True, "embed_server 已运行"
    except Exception:
        pass
    return False, "embed_server 未运行"


def _ensure_embed_server():
    """启动 embed_server（install 子命令用，有副作用）。
    已运行则跳过；未运行则后台 spawn。
    """
    running, _ = _check_embed_server()
    if running:
        return True

    opencode_root = _get_opencode_root()
    script = os.path.join(opencode_root, "mcp-servers", "embed_server.py")
    if not os.path.isfile(script):
        return False

    import subprocess
    try:
        subprocess.Popen(
            [_get_venv_python(), script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # 等 health check（模型加载 ~3s，给 30s 余量）
        import time
        for _ in range(30):
            time.sleep(1)
            running, _ = _check_embed_server()
            if running:
                return True
        return False
    except Exception:
        return False
```

##### c) `_check_mcp_deps_fast()` 新增 embed_server 检测（第1102行区域）

在函数末尾、`return result` 前加：

```python
    # 4. embed_server 检测（informational，不影响 ready 判定）
    # embed_server 不可用时 MCP 自动回退到本地加载，不阻塞 agent 运行
    embed_ok, embed_msg = _check_embed_server()
    result["_embed_server"] = {
        "available": embed_ok,
        "auto_recoverable": True,  # plugin.setup 启动时自动 spawn
        "message": embed_msg,
    }
```

##### d) `_ensure_mcp_infra()` 新增 embed_server 启动（第1175行区域）

在 Docker/Neo4j 启动之后加：

```python
    # embed_server
    embed_ok, _ = _check_embed_server()
    if not embed_ok:
        _log("[*] 启动 embed_server...")
        if _ensure_embed_server():
            _log("[+] embed_server 已启动")
        else:
            _log("[!] embed_server 启动失败（MCP 将回退到本地加载）")
```

#### 2.3.8 `plugins/security-analysis.ts`（~25 行改动）

##### a) plugin.setup 中 spawn embed_server（与 McpManager.registerAll 并列）

```typescript
// ── 启动 embed_server（fire-and-forget，与 McpManager 并列）──
// embed_server 是普通 HTTP 服务（非 MCP），加载 BGE-M3 供所有 MCP 进程共享。
// 不可用时 MCP 自动回退到本地加载（embed_client.py 的 _fallback 逻辑），不阻塞。
const embedScript = join(OPENCODE_ROOT, "mcp-servers", "embed_server.py");
const embedPort = process.env.EMBED_SERVER_PORT || "9776";
if (existsSync(embedScript) && getPythonCmd()) {
  const { spawn: spawnProc } = require("child_process");
  const embedProc = spawnProc(getPythonCmd()!, [embedScript], {
    stdio: ["ignore", "ignore", "ignore"],
    detached: false,
    env: { ...process.env, HF_HUB_OFFLINE: "1" },
  });
  embedProc.on("error", (e: Error) => {
    debugLog(`embed_server spawn 失败: ${e.message}`);
  });
  embedProc.on("exit", (code: number | null) => {
    debugLog(`embed_server exited code=${code}`);
  });
  // opencode 退出时关闭
  process.on("exit", () => {
    try { embedProc.kill("SIGTERM"); } catch {}
  });
  debugLog(`embed_server 已启动 pid=${embedProc.pid} port=${embedPort}`);
} else {
  debugLog(`embed_server 未启动（脚本不存在或 Python 未就绪），MCP 将各自加载模型`);
}
```

##### b) chat.message hook 内增加 embed_server 可用性提示（可选，非阻塞）

```typescript
// 环境检测通过后，检查 embed_server（非阻塞，仅日志）
try {
  const resp = await fetch(`http://127.0.0.1:${embedPort}/health`);
  if (resp.ok) {
    debugLog(`embed_server 可用`);
  } else {
    debugLog(`embed_server 健康检查失败，MCP 将回退到本地加载`);
  }
} catch {
  debugLog(`embed_server 不可用，MCP 将回退到本地加载`);
}
```

#### 2.3.9 `plugins/lib/mcp-manager.ts`（~5 行改动）

MCP_SERVERS 列表不变（embed_server 不是 MCP server，是普通 HTTP server）。
但可以在 registerAll 之前加 embed_server 启动检查。

---

## §3 实施规范

### 3.1 改动范围表

| 文件 | 类型 | 改动行数 | 说明 |
|------|------|---------|------|
| `mcp-servers/embed_server.py` | 新建 | ~110 | HTTP 服务（async + to_thread + 离线模式） |
| `mcp-servers/embed_client.py` | 新建 | ~70 | HTTP 客户端（含回退逻辑） |
| `mcp-servers/knowledge/server.py` | 修改 | ~3 | SentenceTransformer→HttpEmbedClient |
| `mcp-servers/knowledge/memory_writer_daemon.py` | 修改 | ~3 | 同上 |
| `mcp-servers/events/graphiti_config.py` | 修改 | ~8 | BgeM3Embedder.model property |
| `mcp-servers/events/reranker.py` | 修改 | ~8 | BgeRerankerClient.model property |
| `mcp-servers/events/server.py` | 修改 | ~5 | _preload_models_blocking 健康检查 |
| `binary-analysis/scripts/detect_env.py` | 修改 | ~55 | _check_embed_server + _ensure_embed_server |
| `plugins/security-analysis.ts` | 修改 | ~25 | plugin.setup spawn + chat.message 健康检查 |
| **合计** | | **~287** | |

### 3.2 实施步骤拆分

#### 步骤 1. 新建 embed_server.py
- 文件: `mcp-servers/embed_server.py`
- 预估行数: ~80
- 验证点: `python embed_server.py` 启动后 `curl http://127.0.0.1:9776/health` 返回 `{"status":"ok"}`
- 依赖: 无

#### 步骤 2. 新建 embed_client.py
- 文件: `mcp-servers/embed_client.py`
- 预估行数: ~70
- 验证点: `python -c "from embed_client import HttpEmbedClient; c=HttpEmbedClient(); print(c.encode('test').shape)"` 返回 `(1024,)`
- 依赖: 步骤 1

#### 步骤 3. 改造 knowledge/server.py
- 文件: `mcp-servers/knowledge/server.py`
- 预估行数: ~3
- 验证点: `python -c "import server; print('import OK')"`（不实际运行 MCP）
- 依赖: 步骤 2

#### 步骤 4. 改造 knowledge/memory_writer_daemon.py
- 文件: `mcp-servers/knowledge/memory_writer_daemon.py`
- 预估行数: ~3
- 验证点: `python -c "import memory_writer_daemon; print('import OK')"`
- 依赖: 步骤 2

#### 步骤 5. 改造 events/graphiti_config.py
- 文件: `mcp-servers/events/graphiti_config.py`
- 预估行数: ~8
- 验证点: `python -c "from graphiti_config import BgeM3Embedder; e=BgeM3Embedder(); print(type(e.model).__name__)"` 返回 `HttpEmbedClient`
- 依赖: 步骤 2

#### 步骤 6. 改造 events/reranker.py
- 文件: `mcp-servers/events/reranker.py`
- 预估行数: ~8
- 验证点: `python -c "from reranker import BgeRerankerClient; r=BgeRerankerClient(); print(type(r.model).__name__)"` 返回 `HttpEmbedClient`
- 依赖: 步骤 2

#### 步骤 7. 改造 events/server.py
- 文件: `mcp-servers/events/server.py`
- 预估行数: ~5
- 验证点: 语法检查 `python -c "compile(open('server.py').read(), 'server.py', 'exec')"`
- 依赖: 步骤 5, 6

#### 步骤 8. 改造 detect_env.py
- 文件: `binary-analysis/scripts/detect_env.py`
- 预估行数: ~50
- 验证点: `python detect_env.py check-preinstall all` 输出含 `_embed_server` 字段
- 依赖: 步骤 1

#### 步骤 9. 改造 plugins/security-analysis.ts
- 文件: `plugins/security-analysis.ts`
- 预估行数: ~25
- 验证点: `node --check security-analysis.ts`；检查 plugin.setup 内有 embed_server spawn 逻辑
- 依赖: 步骤 1

#### 步骤 10. 端到端验证
- 验证点:
  1. 启动 embed_server.py，`curl /health` 返回 ok
  2. `curl -X POST /embed -d '{"inputs":"test"}' -H 'Content-Type: application/json'` 返回 1024 维向量
  3. `curl -X POST /rerank -d '{"query":"test","texts":["a","b"]}'` 返回 2 个 score
  4. kill embed_server，验证 HttpEmbedClient 回退到本地加载
  5. 重启 embed_server，验证 HttpEmbedClient 自动切回 HTTP

---

## §4 验收标准

### 4.1 功能验收

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | embed_server 启动后 `/health` 返回 ok | `curl http://127.0.0.1:9776/health` |
| 2 | `/embed` 返回 1024 维向量 | `curl -X POST /embed -d '{"inputs":"测试"}'` |
| 3 | `/embed` 批量返回 N×1024 | `curl -X POST /embed -d '{"inputs":["a","b"]}'` |
| 4 | `/rerank` 返回 N 个 score | `curl -X POST /rerank -d '{"query":"q","texts":["a","b"]}'` |
| 5 | embed_server 不可用时 HttpEmbedClient 回退本地加载 | kill server 后 encode 仍返回正确向量 |
| 6 | 回退后重启 server，自动切回 HTTP | 重启后 encode 走 HTTP |
| 7 | knowledge MCP search_knowledge 正常工作 | 在 opencode 中调用 search_knowledge |
| 8 | events MCP time_search 正常工作 | 在 opencode 中调用 time_search |
| 9 | memory_writer_daemon 正常写入 | 执行一个 bash 命令后 search_in_memory 能找到 |
| 10 | write_event_daemon 正常写入 | 执行一个 bash 命令后 time_search 能找到 |

### 4.2 回归验收

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | 向量结果与改造前一致 | 同一文本 encode 结果的余弦相似度 = 1.0 |
| 2 | 重排序结果与改造前一致 | 同一 query+passages 的 predict 结果一致 |
| 3 | detect_env.py install 正常 | `python detect_env.py install` 无报错 |
| 4 | detect_env.py check-preinstall 正常 | `python detect_env.py check-preinstall all` 输出 _embed_server 字段 |

### 4.3 架构验收

| # | 验收项 | 方法 |
|---|--------|------|
| 1 | 4 个 MCP 进程不再各自加载模型 | `ps aux | grep python` 查看各进程 RSS < 500MB |
| 2 | embed_server 是唯一加载模型的进程 | embed_server RSS ~1.3GB，其他进程 < 500MB |
| 3 | 总内存从 ~13GB 降到 ~3GB | `ps aux | grep python` 汇总 |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-19-events-mcp-lazy-loading.md` | 本方案保持 lazy 加载策略，只是加载位置从各进程移到 embed_server |
| `2026-07-25-events-mcp-simplify.md` | 无冲突，工具简化与模型服务化是正交的 |
| `2026-07-25-knowledge-mcp-simplify.md` | 无冲突，同上 |
| `2026-07-23-env-check-optimization.md` | 本方案新增 embed_server 检测，复用 env-check 的 _check_mcp_deps_fast 框架 |
