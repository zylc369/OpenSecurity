# embed_server 启动管理改造

## §1 背景与目标

### 1.1 来源

PentAGI 对齐第 2 期——Graphiti 自动 ingest 需要稳定的 embed_server。当前 embed_server 的启动管理存在降级逻辑、端口硬编码、无等待机制等问题，需要统一改造。

### 1.2 现状问题

| 问题 | 现状 | 影响 |
|------|------|------|
| **降级逻辑** | embed_client.py 有 `_fallback_encode`/`_fallback_predict`，HTTP 失败时本地加载模型 | 掩盖启动失败，MCP 进程各自加载 ~1GB 模型，内存暴涨 |
| **脚本不存在静默跳过** | security-analysis.ts 检测到脚本不存在只打日志 | MCP 降级加载但用户不知情 |
| **fire-and-forget 不等待** | Plugin 启动 embed_server 后不等就绪，chat.message 也不等待 | MCP 首次请求可能命中正在加载模型的 embed_server |
| **端口硬编码 9776** | 无冲突检测，端口被占则 uvicorn 启动失败 | embed_server 挂掉，降级逻辑兜底但浪费内存 |
| **/health 不反映模型状态** | 模型未加载完也返回 200 | 健康检查通过但实际请求会 block |
| **超时一刀切 30s** | 首次请求（触发模型加载）和后续请求用同一超时 | 首次可能不够，后续太浪费 |
| **events/server.py 降级打印** | 健康检查失败时打印"回退到本地加载" | 与降级逻辑同理，掩盖错误 |

### 1.3 目标

- embed_server 不可用时**直接报错**，不降级
- 端口**动态分配**，冲突时自动换端口
- embed_server 启动**同步等待就绪**（模型加载完成后才放行）
- 统一启动状态管理，chat.message 做统一等待 + 统一错误处理
- /health 正确反映模型加载状态

---

## §2 技术方案

### 2.1 端口动态分配（预绑定 socket + fd 传递）

**问题**：先选端口再交给 uvicorn，两次 bind 之间有竞争窗口。

**方案**：socket 绑定后不关闭，detach 出 fd 直接交给 uvicorn。

```python
# embed_server.py
import socket
from pathlib import Path
import os

# DATA_DIR 由 TS Plugin spawn 时传入环境变量
DATA_DIR = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))

def bind_available_port(start=9776, max_tries=30):
    """绑定并返回 socket（不关闭）。"""
    for port in range(start, start + max_tries):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", port))
            return sock, port
        except OSError:
            sock.close()
    raise RuntimeError(f"无可用端口（尝试了 {start}-{start + max_tries - 1}）")

sock, PORT = bind_available_port()

# 写端口文件（socket 还开着，端口被占着，不会冲突）
port_file = Path(DATA_DIR) / ".embed_server_port"
port_file.write_text(f"{PORT}\n{os.getpid()}")

# detach：释放 Python 对 fd 的所有权，交给 uvicorn
fd = sock.detach()
uvicorn.run(app, fd=fd, log_level="warning")
```

> **前置条件**：TS Plugin spawn embed_server 时必须传入 `DATA_DIR` 环境变量：
> ```typescript
> env: { ...process.env, HF_HUB_OFFLINE: "1", DATA_DIR: DATA_DIR }
> ```

**端口文件路径**：`$DATA_DIR/.embed_server_port`（`~/bw-security-analysis/.embed_server_port`）

**内容格式**：
```
9776
12345
```
第一行端口，第二行 embed_server PID。

### 2.2 /health 反映模型加载状态

```python
# embed_server.py
_models_ready = False

def get_embedder():
    global _embedder, _models_ready
    if _embedder is None:
        with _embed_lock:
            if _embedder is None:
                _embedder = SentenceTransformer(EMBED_MODEL)
                _models_ready = True  # embedder 加载完成后置 True
    return _embedder

# 注意：实际使用中 embedder 一定先于 reranker 被请求
# （向量搜索是基础操作，rerank 是可选的二次过滤）
# 所以 _models_ready 只追踪 embedder 状态即可
# /health 在 embedder 就绪后返回 200，此时 /embed 可用
# /rerank 首次调用时才加载 reranker（lazy loading）

async def health(request: Request):
    if not _models_ready:
        return JSONResponse(
            {"status": "loading"},
            status_code=503,
            headers={"Retry-After": "5"},
        )
    return JSONResponse({"status": "ok"}, status_code=200)
```

### 2.3 删除所有降级逻辑

#### embed_client.py

删除：
- `_fallback` 字段
- `_confirmed_available` 字段
- `_fallback_encode()` 方法
- `_fallback_predict()` 方法
- `_try_http()` 中的重试逻辑（改为直接请求，失败抛异常）

改动后 encode/predict：
```python
def encode(self, inputs, convert_to_numpy=True, **kwargs):
    data = self._try_http("/embed", {"inputs": inputs})
    if data is None:
        raise RuntimeError("embed_server 请求失败")
    arr = np.array(data)
    return arr[0] if is_single else arr

def predict(self, pairs, **kwargs):
    if not pairs:
        return np.array([])
    query = pairs[0][0]
    texts = [p[1] for p in pairs]
    data = self._try_http("/rerank", {"query": query, "texts": texts})
    if data is None:
        raise RuntimeError("embed_server 请求失败")
    return np.array(data)
```

#### events/server.py

删除 line 190-203 的健康检查 + "回退到本地加载"打印。改为：
1. embed_server 不可用 → `_init_error.append(RuntimeError("embed_server 不可用"))`
2. **初始化时做 /health 轮询等待**（最多 60s）——因为 MCP 进程在 Plugin 加载时启动，可能早于 embed_server 就绪

```python
# events/server.py 初始化中
def _wait_embed_server_ready(timeout=60):
    """轮询 embed_server /health，等 embedder 加载完成。"""
    import httpx
    port = os.environ.get("EMBED_SERVER_PORT", "9776")
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = httpx.get(url, timeout=3)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(2)
    return False

# 初始化时
if not _wait_embed_server_ready():
    _init_error.append(RuntimeError("embed_server 启动超时（60s）"))
    return
```

### 2.4 动态端口读取

embed_client.py 和 TS Plugin 从端口文件读端口，不硬编码。

#### embed_client.py

```python
def _read_port():
    """优先级：环境变量 > 端口文件 > 默认 9776。"""
    # 1. 环境变量（由 TS Plugin 设置，MCP 子进程继承）
    port = os.environ.get("EMBED_SERVER_PORT")
    if port:
        return int(port)
    # 2. 端口文件（首次请求时读，最多等 5 秒）
    data_dir = os.environ.get("DATA_DIR", str(Path.home() / "bw-security-analysis"))
    port_file = Path(data_dir) / ".embed_server_port"
    for _ in range(5):
        if port_file.exists():
            return int(port_file.read_text().strip().split("\n")[0])
        time.sleep(1)
    # 3. 默认值（最后手段）
    return 9776
```

延迟到首次请求时才读端口（不在 import 时读）：

```python
class HttpEmbedClient:
    def __init__(self):
        self._base_url = None

    @property
    def base_url(self):
        if self._base_url is None:
            port = _read_port()
            self._base_url = f"http://127.0.0.1:{port}"
        return self._base_url
```

### 2.5 分层超时

| 场景 | 超时 | 理由 |
|------|------|------|
| 首次请求（可能触发模型加载） | 60s | BGE-M3 加载 ~10-30s |
| 后续请求 | 10s | 推理 <1s |
| TS Plugin 健康检查轮询 | 3s/次，总超时 60s | 模型加载 ~10-30s |

embed_client.py：
```python
class HttpEmbedClient:
    def __init__(self):
        self._first_request = True
        self._client_first = httpx.Client(timeout=60.0)
        self._client_normal = httpx.Client(timeout=10.0)

    def _try_http(self, endpoint, payload):
        client = self._client_first if self._first_request else self._client_normal
        try:
            resp = client.post(f"{self.base_url}{endpoint}", json=payload)
            resp.raise_for_status()
            self._first_request = False
            return resp.json()
        except Exception as e:
            return None  # encode/predict 层抛 RuntimeError
```

### 2.6 统一启动状态管理

#### 数据结构

```typescript
// lib/service-registry.ts
interface ServiceStatus {
    name: string;
    status: "pending" | "success" | "failed";
    error?: string;
    metadata?: Record<string, any>;  // port, pid 等
    startedAt: number;
    completedAt?: number;
}

class ServiceRegistry {
    private services = new Map<string, ServiceStatus>();
    private resolvers = new Map<string, (svc: ServiceStatus) => void>();

    register(name: string): void;

    resolve(name: string, status: "success" | "failed", error?: string, metadata?: any): void;

    async waitFor(name: string): Promise<ServiceStatus> {
        // 先检查：已 resolve（非 pending）则立即返回，避免 resolve-before-wait 死锁
        const svc = this.services.get(name);
        if (svc && svc.status !== "pending") return svc;
        // pending → 等 resolve 触发
        return new Promise(resolve => {
            this.resolvers.set(name, resolve);
        });
    }

    get(name: string): ServiceStatus | undefined;
}
```

注册到 ctx：
```typescript
// lib/context.ts
ctx.services = new ServiceRegistry();
```

#### Plugin 启动 embed_server

```typescript
// Plugin 加载时
ctx.services.register("embed_server");

if (!existsSync(embedScript)) {
    ctx.services.resolve("embed_server", "failed", "embed_server.py 脚本不存在");
    // chat.message 检测到 failed → 当环境检测失败处理
} else if (!embedPython) {
    ctx.services.resolve("embed_server", "failed", "Python 未就绪");
} else {
    // spawn embed_server
    const embedProc = spawnProc(embedPython, [embedScript], {...});

    embedProc.on("exit", (code) => {
        if (code !== 0 && ctx.services.get("embed_server")?.status === "pending") {
            ctx.services.resolve("embed_server", "failed", `embed_server exited code=${code}`);
        }
    });

    // 轮询健康检查（3s/次，总超时 60s）
    pollEmbedServerHealth(portFile, 60000)
        .then((port) => {
            process.env.EMBED_SERVER_PORT = port;  // MCP 子进程继承
            ctx.services.resolve("embed_server", "success", undefined, { port, pid: embedProc.pid });
        })
        .catch((e) => {
            ctx.services.resolve("embed_server", "failed", e.message);
        });
}
```

#### pollEmbedServerHealth

```typescript
async function pollEmbedServerHealth(portFile: string, timeoutMs: number): Promise<string> {
    const deadline = Date.now() + timeoutMs;

    // 1. 等端口文件出现（最多 5 秒）
    const portDeadline = Date.now() + 5000;
    let port: string | null = null;
    while (Date.now() < portDeadline) {
        try {
            const content = readFileSync(portFile, "utf-8").trim();
            const portStr = content.split("\n")[0];
            if (/^\d+$/.test(portStr)) {
                port = portStr;
                break;
            }
        } catch {}
        await new Promise(r => setTimeout(r, 1000));
    }
    if (!port) throw new Error("embed_server 端口文件 5 秒内未出现");

    // 2. 轮询 /health（503=加载中，200=就绪）
    while (Date.now() < deadline) {
        try {
            const resp = await fetch(`http://127.0.0.1:${port}/health`, {
                signal: AbortSignal.timeout(3000),
            });
            if (resp.status === 200) return port;
            // 503 → 继续等
        } catch {
            // 连不上 → 继续等
        }
        await new Promise(r => setTimeout(r, 2000));
    }
    throw new Error(`embed_server 健康检查超时 (${timeoutMs / 1000}s)`);
}
```

#### chat.message 统一等待

```typescript
"chat.message": async (input, output) => {
    // ... existing setup ...

    // ★ 统一初始化等待函数 ★
    await waitForStartupCompletion(agent, sessionID, sessionData);

    // ... 后续逻辑 ...
}

async function waitForStartupCompletion(
    agent: string,
    sessionID: string,
    sessionData: SessionData | null,
) {
    // 1. 等待 embed_server
    const embedStatus = await ctx.services.waitFor("embed_server");
    if (embedStatus.status === "failed") {
        await reportErrorAndAbort(
            ctx.client, sessionID, sessionData,
            `embed_server 启动失败: ${embedStatus.error}`,
        );
        return;
    }

    // 2. 等待环境检测（复用现有 envCheckPromises 逻辑）
    if (envCheckPromises.has(agent)) {
        const envCheck = await envCheckPromises.get(agent)!;
        if (!envCheck.ready) {
            envCheckPromises.set(agent, preheatEnvCheck(agent));
            await reportErrorAndAbort(
                ctx.client, sessionID, sessionData,
                envCheck.message,
            );
            return;
        }
    } else if (
        agent === AGENT_SECURITY_ANALYSIS_EVOLVE ||
        agent === AGENT_SEARCHER ||
        agent === AGENT_MEMORIST
    ) {
        const pythonCmd = getPythonCmd();
        if (!pythonCmd) {
            await reportErrorAndAbort(
                ctx.client, sessionID, sessionData,
                getInstallHint(),
            );
            return;
        }
    }
}
```

### 2.7 embed_server 生命周期

embed_server 跟随启动它的 opencode 进程，退出时 kill。

```typescript
// security-analysis.ts — 模块级变量（不在 try 块内）
let embedProc: any = null;

// spawn 时赋值
embedProc = spawnProc(embedPython, [embedScript], {
    env: { ...process.env, HF_HUB_OFFLINE: "1", DATA_DIR: DATA_DIR },
    // ...
});

// 退出时 kill（放在 Plugin 初始化阶段注册，确保只注册一次）
process.on("exit", () => {
    try {
        if (embedProc) embedProc.kill("SIGTERM");
    } catch {}
});
```

> **多 opencode 共享 embed_server** 放到后续进化。本期每个 opencode 启动自己的 embed_server。

---

## §3 实现规范

### 3.1 实施步骤拆分

#### 步骤 1：embed_server.py 改造

- **文件**：`mcp-servers/embed_server.py`
- **预估行数**：新增 ~45 行，修改 ~10 行
- **改动**：
  1. 新增 `bind_available_port()` 函数（预绑定 socket，返回 sock + port）
  2. 从环境变量读 `DATA_DIR`（由 TS Plugin spawn 时传入）
  3. 写端口文件（`$DATA_DIR/.embed_server_port`，内容：端口\nPID）
  4. `sock.detach()` + `uvicorn.run(app, fd=fd)`
  5. 新增 `_models_ready` 全局变量（追踪 embedder 加载状态）
  6. `/health` 端点：`_models_ready` 为 False 时返回 503
  7. 删除 `PORT = int(os.environ.get(...))` 硬编码（改为动态分配）
- **验证点**：
  - 启动 embed_server（传入 `DATA_DIR` 环境变量）→ 端口文件出现 → 内容是 `端口号\nPID`
  - 模型加载期间 `curl /health` 返回 503
  - 模型加载完成后 `curl /health` 返回 200
  - 9776 被占用时 → 自动使用 9777 → 端口文件内容是 9777
  - **前置验证**：`python -c "from uvicorn import Config; Config('app', fd=0)"` 不报错（确认 uvicorn 支持 fd 参数）

#### 步骤 2：embed_client.py 改造

- **文件**：`mcp-servers/embed_client.py`
- **预估行数**：删除 ~60 行，新增 ~25 行
- **改动**：
  1. 删除 `_fallback`、`_confirmed_available` 字段
  2. 删除 `_fallback_encode()`、`_fallback_predict()` 方法
  3. 删除 `_try_http()` 中的重试逻辑
  4. 新增 `_read_port()` 函数（环境变量 > 端口文件 > 默认）
  5. `base_url` 改为 `@property` 延迟构建
  6. 新增分层超时（首次 60s，后续 10s）
  7. encode/predict 失败时抛 `RuntimeError`（不再回退）
- **验证点**：
  - embed_server 运行时 → HTTP 请求成功
  - embed_server 未运行时 → encode() 抛 RuntimeError（不本地加载）
  - 首次请求用 60s 超时，第二次请求用 10s 超时

#### 步骤 3：events/server.py 改造

- **文件**：`mcp-servers/events/server.py`
- **预估行数**：删除 ~15 行，新增 ~25 行
- **改动**：
  1. 删除 line 190-203 的健康检查 + "回退到本地加载"打印
  2. 新增 `_wait_embed_server_ready()` 函数（/health 轮询，最多 60s）
  3. 初始化时调用 `_wait_embed_server_ready()`，超时则 `_init_error.append(RuntimeError(...))`
- **验证点**：
  - embed_server 已就绪时 events MCP 正常初始化（_wait 快速通过）
  - embed_server 未就绪时 events MCP 初始化等待（最多 60s）
  - embed_server 60s 内未就绪 → events MCP 初始化失败（不降级）

#### 步骤 4：新建 ServiceRegistry

- **文件**：**新增** `plugins/lib/service-registry.ts`
- **预估行数**：~80 行
- **改动**：
  1. `ServiceStatus` 接口
  2. `ServiceRegistry` 类（register/resolve/waitFor/get）
  3. 导出单例
- **验证点**：
  - `register("test")` → `waitFor("test")` 阻塞
  - `resolve("test", "success")` → `waitFor` 返回
  - `resolve("test", "failed", "msg")` → `waitFor` 返回带 error

#### 步骤 5：ctx 集成 ServiceRegistry

- **文件**：`plugins/lib/context.ts`
- **预估行数**：~5 行
- **改动**：
  1. `ctx.services` 字段
  2. `ctx.init()` 中初始化
- **验证点**：
  - `ctx.services.register("x")` 不报错

#### 步骤 6：security-analysis.ts 改造

- **文件**：`plugins/security-analysis.ts`
- **预估行数**：新增 ~80 行，修改 ~35 行，删除 ~15 行
- **改动**：
  1. 新增 `pollEmbedServerHealth()` 函数
  2. 新增模块级 `let embedProc: any = null`
  3. embed_server 启动逻辑改为：register → spawn（**传入 DATA_DIR 环境变量**）→ poll health → resolve
  4. 脚本不存在/Python 未就绪 → resolve("failed")
  5. 新增 `waitForStartupCompletion()` 函数（等待 embed_server + envCheck）
  6. chat.message 调用 `waitForStartupCompletion()` 替代现有分散的等待逻辑
  7. 退出时 kill embed_server（`process.on("exit")` 中 `embedProc?.kill("SIGTERM")`）
- **验证点**：
  - embed_server 脚本不存在 → chat.message 报错"embed_server 启动失败: 脚本不存在"
  - embed_server 启动中 → chat.message 等待 → 就绪后放行
  - embed_server 启动失败 → chat.message 报错
  - opencode 正常退出 → embed_server 被 kill
  - spawn 时 DATA_DIR 已传入（embed_server 端口文件路径正确）

#### 步骤 7：端到端验证

- **文件**：无新文件
- **预估行数**：0
- **改动**：无代码改动
- **验证点**：
  1. 启动 opencode → embed_server 自动启动 → 端口文件出现 → /health 从 503 变 200
  2. 发送分析消息 → chat.message 等待 embed_server 就绪 → 正常工作
  3. kill embed_server → 下次 opencode 启动检测到无响应 → 重新启动
  4. 端口 9776 被占用 → embed_server 自动用 9777 → MCP 正常连接
  5. opencode 退出 → embed_server 被 kill → 端口文件残留但不影响

---

## §4 验收标准

### 4.1 功能验收

| 编号 | 验收点 | 验证方法 |
|------|--------|---------|
| F1 | embed_server 动态端口分配 | 占用 9776 → 启动 opencode → 端口文件显示 9777 |
| F2 | 端口文件正确写入 | 启动后 `cat ~/bw-security-analysis/.embed_server_port` 显示端口+PID |
| F3 | /health 模型加载中返回 503 | 启动后立即 `curl http://127.0.0.1:<port>/health` → 503 |
| F4 | /health 模型就绪返回 200 | 等待模型加载完 → `curl` → 200 |
| F5 | 降级逻辑已删除 | kill embed_server → embed_client.encode() 抛 RuntimeError（不本地加载） |
| F6 | 脚本不存在报错 | 删除 embed_server.py → 启动 opencode → chat.message 报"脚本不存在" |
| F7 | chat.message 等待启动 | 启动 opencode → 立即发消息 → 消息被阻塞直到 embed_server 就绪 |
| F8 | 分层超时生效 | 首次请求 60s 超时（日志可见），后续请求 10s 超时 |
| F9 | opencode 退出 kill embed_server | 退出 opencode → `ps aux \| grep embed_server` 无进程 |

### 4.2 回归验收

| 编号 | 验收点 |
|------|--------|
| R1 | MCP server（events/knowledge）正常使用 embed_server |
| R2 | Graphiti 初始化正常（依赖 embed_client） |
| R3 | 现有功能不受影响（分析流程、知识检索、事件图谱） |

### 4.3 架构验收

| 编号 | 验收点 |
|------|--------|
| A1 | `plugins/lib/service-registry.ts` 位于正确的架构层 |
| A2 | ctx 集成 ServiceRegistry 不破坏现有 ctx.init() 逻辑 |
| A3 | embed_client.py 接口不变（encode/predict 签名不变），消费方零改动 |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-26-embed-server.md` | 本文是其后续改造——初始实现已完成，本文修复启动管理、端口、降级、等待机制 |
| `2026-07-08-pentagi-alignment-decisions.md` | 第 2 期 Graphiti 自动 ingest 的前置依赖——Graphiti 依赖 embed_server 稳定运行 |
