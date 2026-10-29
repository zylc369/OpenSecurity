# 远程模型卸载（一期：模型远程化 + 资源调度）

> 状态: 已实施完成（2026-09-26; 回归 119/119 + 端到端全链路验证通过; 详见 progress-2026-09-26-remote-model-offload.md）
> 日期: 2026-09-26
> 范围: 一期 = 模型远程化（embed / rerank / ocr 三模型）。neo4j 远程化延后（数据非中心化问题，二期决策）。

---

## §1 背景与目标

**来源**: 用户提出资源充分利用方案——局域网内 Mac Mini（16GB）作为远程资源节点，本机控制台配置远程链接后，模型推理优先走远程，远程失效降级本地，远程恢复后卸载本地资源，释放本机 ~5-6GB 内存。

**已确认决策清单**（讨论轮次逐项确认，实施不得偏离）:

| # | 决策 |
|---|------|
| D1 | 一期仅模型远程化；neo4j/SQLite 存储与数据 100% 留本地，Mac Mini 上无任何数据库 |
| D2 | 常驻配置 `CONTROL_RESIDENT`（true → 心跳自杀机制失效） |
| D3 | API KEY 拆分暴露面: 管理类 API 仅本机；推理类 API（/embed /rerank /api/ocr/extract /api/remote/*节点端点）+ Bearer token 对局域网开放；`CONTROL_API_KEY` 未配置则不绑局域网（默认安全） |
| D4 | 自动启动 `CONTROL_AUTOSTART`：配置后通过 API 在设备上安装 launchd 开机启动；须提示 Mac Mini 开启自动登录（LaunchAgent 登录后才运行） |
| D5 | 恢复防抖: 连续 N=3 次心跳成功才切回远程；切回后稳定 X=300s 才卸载本地模型；降级判定: 连续 2 次心跳失败 |
| D6 | 卸载安全统一抽象: 新建受管模型生命周期（状态机 + FIFO 串行队列 + 双触发卸载），三模型（embedder/reranker/OCR）全部收口到该抽象；OCR 现有机制（lifecycle 锁 + _MlxWorker FIFO + 空闲 reaper）泛化迁移 |
| D7 | 降级语义: 远程失效 → 新请求 HOLD（本地懒加载阻塞，最长 ~60s 对齐 plugin 超时）→ 本地执行 → 不报错；在途远程请求失败 → 请求级 fallback 自动改走本地 |
| D8 | 切换点在 model_loader / ocr_service 内部路由（MemoryDB 与 graphiti 长期持有 LockedEmbedder 对象，不能靠替换对象切换） |
| D9 | 远程节点（`CONTROL_API_KEY` 存在 = 节点角色）启动即预加载三模型；绑定 0.0.0.0 |
| D10 | `REMOTE_CONSOLE_ENABLED` 只能经"切换远程"按钮（先校验后置位）写 1，配置接口不允许直接置 1 |
| D11 | 远程/本地模型版本指纹（repo_id + HF snapshot hash）不一致时警告不阻断 |
| D12 | 切换本地后本地模型保持加载（不卸载）；心跳日志独立文件（不与 control.log 混） |

**预期收益**: 远程模式期间本机释放 BGE-M3 (~2-3GB) + Reranker (~2GB) + OCR (~1GB)；Mac Mini 闲置算力利用。

**明确不做**（边界）:
- neo4j / SQLite / 事件库 / memory 库的远程化与数据同步
- Docker 容器远程化（一期降级只预热模型，不涉 Docker 冷启动）
- TLS（局域网明文 HTTP + token，用户接受）
- 双写 / 数据回灌 / Mac Mini 上 opencode 双角色支持（仅文档提示）

---

## §2 技术方案

### 2.1 新模块与改动总览

```
control/backend/
├── services/
│   ├── model_lifecycle.py   [新增] 受管模型生命周期抽象（ModelWorker + ManagedModel）
│   ├── remote_client.py     [新增] 远程推理 HTTP 客户端（embed/rerank/ocr/probe）
│   ├── remote_link.py       [新增] 远程链接状态机（心跳/降级/恢复/延迟卸载编排）+ 独立日志
│   ├── api_guard.py         [新增] 鉴权中间件（本机全放行 / 局域网白名单+token）
│   ├── launchd_setup.py     [新增] macOS LaunchAgent 安装/卸载/状态查询
│   ├── model_loader.py      [改造] 三模型纳入 ManagedModel；LockedEmbedder/LockedReranker 内部路由 + 请求级 fallback
│   ├── ocr_engines.py       [改造] _MlxWorker 泛化迁移到 ModelWorker（MlxEngine 不再自持 worker）
│   ├── ocr_service.py       [改造] 生命周期编排迁移到 ManagedModel；extract 增加远程路由 + fallback
│   ├── heartbeat.py         [改造] CONTROL_RESIDENT 支持（禁自杀，sweep 照跑）
│   ├── logging_setup.py     [改造] 新增 setup_auxiliary_logger（独立日志文件通用函数）
│   └── frontend_port.py     [改造] 绑定地址可配置（CONTROL_API_KEY 存在 → 0.0.0.0）
├── routes/
│   ├── remote.py            [新增] 主控端点（status/switch/config）+ 节点端点（health/node-config/autostart，含模型指纹）
│   └── health.py            [不动] /api/health 语义不变（版本指纹由 /api/remote/health 承载）
├── config.py                [改造] 新配置 KEY + 心跳/超时常量
└── server.py                [改造] 中间件挂载 / remote_link 启动 / 节点模式预加载

control/frontend/src/
├── sections/RemoteSection.tsx  [新增] 远程资源 TAB（三卡片）
├── api/client.ts                [改造] 远程 API 封装
├── types/index.ts               [改造] 类型
├── constants/categories.ts      [不动]
└── App.tsx                      [改造] Segmented 第三项 + #/remote 路由
```

### 2.2 model_lifecycle.py — 受管模型生命周期（D6 核心）

从 OCR 已验证机制泛化（语义保真迁移）:

```python
class ModelWorker:
    """专职常驻线程，FIFO 串行执行 load/infer/unload。
    泛化自 ocr_engines._MlxWorker（queue.Queue + Future + daemon 线程）。"""

class ManagedModel:
    """受管模型: 状态机 idle/starting/ready/stopping + 单飞加载 + 排队卸载 + 空闲 reaper(可选)。

    __init__(self, name, load_fn, unload_fn, idle_timeout_sec=None, reaper_interval_sec=5.0)
    ensure_loaded()   -> None        # 单飞: 并发调用等同一事件; 失败回 idle
    run_inference(fn) -> T           # ensure_loaded → worker.call(fn): 卸载天然排在在途推理后
    release()         -> None        # 事件触发卸载: worker.call(unload_fn)（排队，安全）
    is_loaded() -> bool
    status() -> ModelLifecycleStatus # state/idle_sec/idle_timeout_sec/error
    """
```

关键约束:
- **每个 ManagedModel 实例独占一个 ModelWorker**（跨模型不互相阻塞）；OCR 的 ManagedModel 为模块级单例 → 其 worker 保持进程唯一（MLX thread-local stream 约束不变）
- 全部同步原语（threading），async 消费方经 `asyncio.to_thread` 包装（与现状一致）
- 卸载三互斥语义: load / infer / unload 全经同一 worker FIFO——物理排队，在途推理完成才动模型（替代引用计数）
- 空闲 reaper 是 ManagedModel 内置可选能力（idle_timeout_sec=None 禁用）
- **idle_timeout 三模型取值**: embedder / reranker = None（一期仅事件触发卸载，不做空闲卸载）; OCR = 600s（保持现有行为）。DEGRADED 预热会把 OCR 加载，之后 OCR 空闲 600s 被 reaper 卸载属正常行为（下次请求懒加载 ~2s，可接受）
- `ModelLifecycleStatus` 为 dataclass（强类型，规则 9）

**循环依赖防护（铁律）**: model_loader（底层）的路由层引用 remote_link（上层状态机），而 remote_link 的降级/恢复编排又要调用 model_loader 预热/卸载——两个方向都必须**函数内延迟 import**（项目现有惯例，graphiti_config 同模式），模块顶部禁止互相 import。

### 2.3 model_loader.py 改造 — 内部路由 + fallback（D7/D8 核心）

```python
# LockedEmbedder.encode 内部（对外签名与返回类型不变——MemoryDB/graphiti 零感知）:
def encode(self, sentences, **kwargs):
    if _route().use_remote():
        try:
            return _remote_embed(sentences)        # np.ndarray（与本地返回 duck-type 一致）
        except RemoteUnavailable as e:
            remote_link.note_request_failure(str(e))   # 反馈状态机（加速降级判定）
            # 请求级 fallback: 落到本地（懒加载阻塞 = HOLD 语义）
    return _local_embed(sentences)                 # ManagedModel.run_inference 包装
```

- `_route()` 读 remote_link 状态机快照（线程安全，无锁读）
- 本地路径: `run_inference(lambda: _embedder.encode(...))`；`_infer_lock` 退役（worker FIFO 串行是唯一机制——单一机制原则，MPS 堆损坏防线不变）
- reranker（LockedReranker.predict）同构改造
- `preload_embedder_background()` 保留（本地模式语义不变）；新增 `release_all_local()`（事件触发卸载 embedder+reranker，供 remote_link 延迟卸载调用）; 新增 `preload_all_models_background()`（节点模式入口: 后台线程预热 embedder+reranker，OCR 经函数内延迟 import 调 ocr_service 的等价预热方法——§2.2 循环依赖防护同样适用）
- `is_models_ready()` 语义扩展: 远程模式返回 True（模型服务可用——远程就绪即就绪），本地模式维持原语义

### 2.4 remote_client.py — 远程推理客户端

```python
class RemoteUnavailable(RuntimeError): ...   # 连接失败/超时/5xx/401/响应畸形 统一异常

class RemoteConsoleClient:
    __init__(self, base_url, token, infer_timeout=30.0, probe_timeout=3.0)
    embed(texts: list[str]) -> list[list[float]]      # POST /embed {"inputs": texts}
    rerank(query, texts) -> list[float]               # POST /rerank
    ocr_extract(image_b64, prompt) -> str             # POST /api/ocr/extract
    probe_health() -> RemoteHealthInfo                # GET /api/remote/health（心跳探测）
# 同步 httpx（调用点均在 worker/线程域）+ async 包装（asyncio.to_thread）
# 全部带 Authorization: Bearer <token>；secrets.compare_digest 由服务端做
```

`RemoteHealthInfo`（dataclass）: service / version / models: list[ModelFingerprint(repo_id, snapshot, loaded)] / latency_ms。

### 2.5 remote_link.py — 远程链接状态机（D5/D12 核心）

```python
class RemoteLinkService:   # 模块级单例 remote_link
    状态: OFF（未启用/未配置） | REMOTE（启用且健康） | DEGRADED（启用但失效）
    后台 asyncio task（uvicorn loop）周期 REMOTE_HEARTBEAT_INTERVAL_SEC=5s:
      probe → 成功: fail_streak=0, recover_streak+=1
              REMOTE 态: 维持; DEGRADED 态且 recover_streak>=3 → 切 REMOTE + 安排 300s 后卸载本地模型
                         （300s 内再降级 → 取消卸载）
      probe → 失败: recover_streak=0, fail_streak+=1
              REMOTE 态且 fail_streak>=2 → 切 DEGRADED + 立即后台预热本地三模型 + 记录原因
    note_request_failure(reason): 请求级失败反馈（fail_streak+=1，达阈值同样触发降级路径）
    should_use_remote() -> bool: REMOTE 态且 ENABLED=1（线程安全快照读，路由层每请求调用）
    switch_to_remote() -> SwitchResult:  校验（probe + token + 版本指纹对比）→ 成功写
                                         REMOTE_CONSOLE_ENABLED=1 → 状态机立即评估; 失败返回原因（不置位）
    switch_to_local():  写 REMOTE_CONSOLE_ENABLED=0 → 状态机 OFF; 本地模型保持加载（D12）
    status() -> RemoteLinkStatus       # 前端 TAB 单一事实源
```

- 预热/卸载动作经 `threading.Thread(daemon)` 调 model_loader/ocr_service（不阻塞心跳 task; 对 model_loader/ocr_service 的引用必须函数内延迟 import——见 §2.2 循环依赖防护）
- 独立日志: `setup_auxiliary_logger("remote_link", "remote-link.log")` → `DATA_DIR/logs/remote-link.log`（RotatingFileHandler，不进 control.log）
- **配置热重载**: `reload_config()` 在 PUT /api/remote/config 写入 URL/TOKEN 后被调用——重建内部 RemoteConsoleClient（读最新配置）、清零心跳计数、立即触发一次探测（配置变了旧健康状态作废）
- **启动跳过本地预加载**: 启动时若 ENABLED=1 且 URL 非空 → server.py 跳过 preload_embedder_background（本地不加载，由首次心跳判定: REMOTE 则保持不加载、DEGRADED 走预热路径）——避免"每次重启白白加载、300s 后又卸载"
- 常量（env 可覆盖，config.py 收口）: `REMOTE_HEARTBEAT_INTERVAL_SEC=5` / `REMOTE_FAIL_THRESHOLD=2` / `REMOTE_RECOVER_THRESHOLD=3` / `REMOTE_UNLOAD_DELAY_SEC=300` / `REMOTE_INFER_TIMEOUT_SEC=30` / `REMOTE_PROBE_TIMEOUT_SEC=3`

### 2.6 api_guard.py — 鉴权中间件（D3 核心）

FastAPI middleware（覆盖所有路由）:

```
请求 client_host ∈ {127.0.0.1, ::1} → 放行（本机全功能）
否则（局域网）:
  path ∈ LAN_ALLOWED_PREFIXES → 校验 Authorization: Bearer == CONTROL_API_KEY
                                 （secrets.compare_digest）→ 匹配放行，否则 401
  path ∉ 白名单 → 403（fs/docker/process/config/scan 等管理面绝不暴露局域网）
CONTROL_API_KEY 未配置 → 非本机一律 403（同时绑定仍为 127.0.0.1，双保险）
```

白名单（精确前缀）: `/embed`、`/rerank`、`/api/ocr/extract`、`/api/remote/health`、`/api/remote/node-config`、`/api/remote/autostart`。
排除误开放: `/api/docs`、`/api/openapi.json`、`/`（前端页面）均不在白名单（局域网访问页面无 API 权限时无意义，Mac Mini 节点页面经本机/SSH 隧道管理）。

### 2.7 routes/remote.py — API 端点

主控端点（仅本机使用，受 guard 保护默认仅本机）:
- `GET /api/remote/status` → RemoteLinkStatus（enabled/url/state/心跳计数/远程健康明细/本地三模型状态/卸载倒计时; **token 不回传明文**——仅 token_configured: bool + 前 6 位）
- `POST /api/remote/switch` `{"target": "remote"|"local"}` → SwitchResult（成功/失败+原因+warnings）
- `PUT /api/remote/config` `{"url": ..., "token": ...}` → 写 REMOTE_CONSOLE_URL/TOKEN 后触发 remote_link.reload_config()（ENABLED 不可经此写，D10）

配置页隐藏（用户 3a）: ConfigField 增加 `hidden: bool = False` 字段; 6 个新 KEY 全部 hidden=True（type=password/text 元数据齐全，供远程 TAB 差异化渲染）; /api/config/meta 返回 hidden 标志; ConfigSection 跳过 hidden=True 的键——新 KEY 不在配置页出现、由远程资源 TAB 专属管理。GET /api/config 明文回传维持现状（本机信任模型，与 DEEPSEEK_API_KEY 同等待遇; api_guard 已确保局域网 403）。

节点端点（局域网 + token; `?node=remote` 参数化目标——默认操作本机，`node=remote` 时主控转发到远程节点的同端点，远程 TAB 卡片 3 全部带此参数）:
- `GET /api/remote/health` → 轻量健康: service/版本/三模型指纹(repo_id+snapshot hash+loaded)——心跳探测目标
- `GET/PUT /api/remote/node-config` → 仅允许 CONTROL_RESIDENT / CONTROL_AUTOSTART / CONTROL_API_KEY 三 KEY 读写（受限配置面，非通用 config API; 转发模式下调 remote_client 携 TOKEN）
- `GET/POST /api/remote/autostart` → LaunchAgent 安装/卸载/状态（`{"enable": bool}`; 同样支持 node=remote 转发）
- 转发前置条件: REMOTE_CONSOLE_URL + TOKEN 已配置，否则返回明确错误（前端卡片 3 显示空态提示"先配置远程连接"）

版本指纹（D11）: HF 缓存 snapshot 目录名哈希（`models--BAAI--bge-m3/snapshots/<hash>` 的 `<hash>`），不加载模型即可取。switch 校验时对比本地指纹，不一致 → SwitchResult.warnings 携带（前端黄条提示，不阻断）。

### 2.8 launchd_setup.py

- `install()`: 写 `~/Library/LaunchAgents/com.opensecurity.control.plist`（ProgramArguments = 当前 venv python + server.py 路径; RunAtLoad; StandardOut/ErrPath → DATA_DIR/logs/launchd.log）+ `launchctl load`
- `uninstall()` / `status()`（plist 存在性 + launchctl list 探测）
- 非 macOS 返回明确错误（节点部署目标为 Mac Mini，darwin 限定）
- 首次部署流程（写入需求文档与前端提示）: Mac Mini 本机页面配置 CONTROL_API_KEY（bootstrap 必须本机完成，避免远程配 key 的鸡蛋问题）→ 重启生效（绑 0.0.0.0）→ 本地 TAB 填 URL+TOKEN → 切换远程。**部署提示两条**: ① macOS 首次绑 0.0.0.0 可能弹防火墙允许对话框，需点允许; ② Mac Mini 需开启自动登录（LaunchAgent 登录后才运行）

### 2.9 heartbeat.py + server.py 集成

- heartbeat: `HeartbeatTask.__init__` 读 `CONTROL_RESIDENT`（config_store）；resident=True 时 sweep 照跑但跳过自杀分支（日志一条"常驻模式，自杀机制禁用"）
- server.py main(): 绑定地址经 frontend_port（CONTROL_API_KEY 存在 → 0.0.0.0，否则维持 127.0.0.1）
- server.py lifespan startup: `remote_link.start()`（心跳 task）
- server.py main(): 节点角色（CONTROL_API_KEY 存在）→ `preload_all_models_background()`（三模型后台预加载，D9）
- api_guard 中间件在 create_app 中挂载（CORS 之后、路由之前）

### 2.10 前端 — 远程资源 TAB（#/remote）

`App.tsx` Segmented: `[环境总览, 运行状态, 远程资源]`，hash 路由 `#/remote`（复用 pageFromHash 模式，PageKey 扩展 "remote"）。

`RemoteSection.tsx` 三卡片（苹果式布局延续现有 antd 风格 + 毛玻璃顶栏语言）:

1. **远程连接**: URL 输入 / TOKEN 输入（password 态）/ 开关状态 Tag（忠实显示 ENABLED 配置值）/ 「切换远程」「切换本地」按钮（互斥显示; 切换远程先校验——失败红色展示原因，成功绿色 + 按钮翻转; 校验警告黄条展示版本指纹不一致）/ 远程健康度（延迟 ms、连续成功次数、远程模型指纹列表 5s 轮询）
2. **当前模式**: 实际生效模式大字标示（本地 / 远程 / 已降级）; **DEGRADED 时红色闪烁 Badge + 失败原因 + 降级时间**（CSS keyframes 闪烁，global.css 定义）; 本地三模型加载状态（远程托管时显示"远程托管"Tag; 降级预热中显示 loading）
3. **远程节点管理**: CONTROL_API_KEY 设置（password + 「生成随机 KEY」按钮）/ CONTROL_RESIDENT 开关（含说明: 禁用自杀机制）/ CONTROL_AUTOSTART 开关（安装/卸载 LaunchAgent; 含提示: Mac Mini 需开启自动登录，LaunchAgent 登录后才运行）/ 自动启动安装状态显示

数据源: `api.getRemoteStatus()` 5s 轮询（与后端状态机单一事实源对齐）; 节点配置读写 `api.getNodeConfig/updateNodeConfig/setAutostart`（经本控制台转发到远程节点——即本地控制台作为代理调远程节点的 /api/remote/node-config，带本地保存的 TOKEN）。

模型页（ModelsSection）不改动: 显示本地真实加载态（远程托管时本地未加载是事实）; 远程 TAB 负责路由模式口径，避免两处打架。

### 2.11 消费方零改动验证（D8 成立性）

| 消费方 | 调用路径 | 路由生效点 |
|--------|---------|-----------|
| mcp-servers/ocr | HTTP → /api/ocr/extract → ocr_service.extract | ocr_service.extract 内部 |
| graphiti（事件库） | BgeM3Embedder → model_loader.embed_sync | LockedEmbedder.encode 内部 |
| memory/knowledge | MemoryDB( LockedEmbedder ).encode | 同上（持有对象不变，策略内部切换） |
| /embed /rerank 路由 | model_loader.embed_async/rerank_async | 同上 / LockedReranker.predict |
| 同步搜索 | knowledge_store → MemoryDB.search | 同上 |

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 动作 | 预估行数 |
|------|------|---------|
| services/model_lifecycle.py | 新增 | ~200 |
| services/remote_client.py | 新增 | ~130 |
| services/remote_link.py | 新增 | ~260 |
| services/api_guard.py | 新增 | ~110 |
| services/launchd_setup.py | 新增 | ~110 |
| routes/remote.py | 新增 | ~170 |
| services/model_loader.py | 改造 | ~160 变更 |
| services/ocr_service.py | 改造 | ~130 变更 |
| services/ocr_engines.py | 改造 | ~70 变更 |
| services/heartbeat.py | 改造 | ~15 变更 |
| services/logging_setup.py | 改造 | ~30 变更 |
| services/frontend_port.py | 改造 | ~20 变更 |
| config.py / server.py | 改造 | ~60 变更 |
| frontend: RemoteSection.tsx / client.ts / types / App.tsx / global.css | 新增+改造 | ~530 |
| tests/test_model_lifecycle.py 等测试 | 新增 | ~500 |

### 3.1 实施步骤拆分（每步 ≤200 行，含验证点）

**步骤 1. model_lifecycle.py 实现（ModelWorker + ManagedModel）**
- 文件: services/model_lifecycle.py（新）
- 预估行数: 200
- 验证点: `python -c compile` 通过; API 面（ensure_loaded/run_inference/release/status）与 §2.2 签名一致
- 依赖: 无

**步骤 2. model_lifecycle 单测**
- 文件: tests/test_model_lifecycle.py（新）
- 预估行数: 150
- 验证点: 单测覆盖——单飞加载（并发 10 线程只 load 一次）、排队卸载（推理在途时 release 等推理完成后才 unload）、空闲 reaper 触发/禁用、加载失败回 idle、状态快照字段; pytest 全绿
- 依赖: 步骤 1

**步骤 3. OCR 迁移到 ManagedModel**
- 文件: services/ocr_engines.py（_MlxWorker 删除，改用 model_lifecycle.ModelWorker; MlxEngine load/infer/unload 变纯实现由调用方调度）、services/ocr_service.py（生命周期段替换为 ManagedModel; extract 保留并发预处理段; ollama 分支不动）
- 预估行数: 200 变更
- 验证点: `python -c compile`; grep 确认 _MlxWorker/_WORKER_SINGLETON 零残留（收口完成标志）; 现有 OCR 测试回归通过
- 依赖: 步骤 1

**步骤 4. embedder/reranker 纳入 ManagedModel（纯本地路径）**
- 文件: services/model_loader.py（改造为 ManagedModel 管理; _infer_lock 退役; preload/release API）
- 预估行数: 160 变更
- 验证点: 单测——embed_sync 并发 8 线程压测无异常、release 后再次调用自动重载、is_models_ready/is_reranker_loaded 语义不变; 现有 test_control.py 相关用例回归
- 依赖: 步骤 1

**步骤 5. config.py 扩展 + logging_setup 辅助日志**
- 文件: config.py（ConfigField 加 hidden 字段 + 6 个新 KEY 元数据（hidden=True）+ 6 个 env 可覆盖常量）、services/logging_setup.py（setup_auxiliary_logger）
- 预估行数: 110 变更
- 验证点: `python -c compile`; setup_auxiliary_logger 生成独立文件且 root logger 不受影响; meta 序列化含 hidden 字段
- 依赖: 无

**步骤 6. remote_client.py 实现**
- 文件: services/remote_client.py（新）
- 预估行数: 130
- 验证点: `python -c compile`; API 与 §2.4 签名一致; RemoteUnavailable 统一异常面
- 依赖: 步骤 5

**步骤 7. remote_client 单测**
- 文件: tests/test_remote_client.py（新）
- 预估行数: 120
- 验证点: httpx.MockTransport 单测——正常 embed/rerank/ocr/probe、连接失败/超时/401/5xx/畸形响应 → RemoteUnavailable、Bearer 头携带
- 依赖: 步骤 6

**步骤 8. model_loader/ocr_service 路由层 + 请求级 fallback**
- 文件: services/model_loader.py（_route/_remote_embed/fallback，对 remote_link 函数内延迟 import）、services/ocr_service.py（extract 路由段，同规范）
- 预估行数: 120 变更
- 验证点: 单测（monkeypatch remote_link fake）——REMOTE 态走远程（本地不加载）、远程抛 RemoteUnavailable → fallback 本地成功且 note_request_failure 被调、OFF 态直通本地
- 依赖: 步骤 3、4、6

**步骤 9. remote_link.py 实现（状态机 + 心跳 + 编排）**
- 文件: services/remote_link.py（新; 含 reload_config、独立日志、预热/卸载编排、switch、启动跳过本地预加载的判定函数）
- 预估行数: 200
- 验证点: `python -c compile`; 与 §2.5 状态迁移一一对应; 延迟 import 规范（模块顶部无 model_loader import）
- 依赖: 步骤 6

**步骤 10. remote_link 单测**
- 文件: tests/test_remote_link.py（新）
- 预估行数: 180
- 验证点: 单测（fake client + 小阈值 env）——2 连败降级+预热触发、3 连胜恢复+300s 延迟卸载安排、恢复窗口内再降级取消卸载、switch_to_remote 校验失败不置位/成功置位、switch_to_local 不卸载、reload_config 重建 client、独立日志文件生成且 control.log 无 remote_link 行
- 依赖: 步骤 9

**步骤 11. api_guard.py + 绑定扩展 + server 集成**
- 文件: services/api_guard.py（新）、services/frontend_port.py（绑定地址读配置）、server.py（中间件挂载 + remote_link.start + 节点模式预加载 + ENABLED 启动跳过预加载）
- 预估行数: 200
- 验证点: `python -c compile`; 手动冒烟——默认启动行为与现状一致（127.0.0.1、无 token 要求）
- 依赖: 步骤 5、9

**步骤 12. api_guard 单测**
- 文件: tests/test_api_guard.py（新）
- 预估行数: 100
- 验证点: TestClient 单测——本机放行、局域网白名单+正确 token 放行、错误 token 401、非白名单 403、未配 KEY 时局域网全 403
- 依赖: 步骤 11

**步骤 13. heartbeat resident + launchd_setup**
- 文件: services/heartbeat.py（resident 豁免）、services/launchd_setup.py（新）
- 预估行数: 125
- 验证点: `python -c compile`; 单测——resident 模式表空不自杀; launchd status 非 darwin 明确报错（install/uninstall 在测试中不真跑，仅 darwin 单测环境跳过）
- 依赖: 步骤 5

**步骤 14. routes/remote.py + server include + 配置页隐藏**
- 文件: routes/remote.py（新）、server.py（include_router）、routes/config_route.py（meta 输出 hidden）、frontend/src/sections/ConfigSection.tsx（跳过 hidden 键渲染）
- 预估行数: 190
- 验证点: `python -c compile`; 冒烟——status/switch/config/node-config/autostart/health 端点基本路径; 配置页不再出现 6 个新 KEY
- 依赖: 步骤 5、9、13

**步骤 15. routes/remote 单测**
- 文件: tests/test_remote_routes.py（新）
- 预估行数: 150
- 验证点: node-config 仅三 KEY 白名单（其他 key 拒绝）、switch 成功/失败路径、status 字段完整、/api/remote/health 返回模型指纹
- 依赖: 步骤 14

**步骤 16. 前端 types + client.ts**
- 文件: frontend/src/types/index.ts、api/client.ts
- 预估行数: 100
- 验证点: `bunx tsc --noEmit` 通过; 类型与后端 RemoteLinkStatus 字段一一对应（人工对照）
- 依赖: 步骤 14（接口契约）

**步骤 17. RemoteSection 骨架 + 远程连接卡片**
- 文件: frontend/src/sections/RemoteSection.tsx（新; 卡片 1: URL/TOKEN/开关态/切换按钮/健康度）
- 预估行数: 200
- 验证点: `bunx tsc --noEmit` 通过; dev 页面渲染卡片 1、切换按钮互斥逻辑
- 依赖: 步骤 16

**步骤 18. 卡片 2/3 + App 集成 + 闪烁样式**
- 文件: RemoteSection.tsx（卡片 2 当前模式红闪、卡片 3 节点管理）、App.tsx（Segmented 第三项 + #/remote）、global.css（keyframes）
- 预估行数: 200
- 验证点: `bun run build` 成功; 手动验收——三卡片渲染、降级红闪、5s 轮询、开关忠实显示配置
- 依赖: 步骤 17

**步骤 19. 端到端联调 + 全量回归 + progress 文档**
- 文件: requirements/evolve/progress-2026-09-26-remote-model-offload.md
- 预估行数: 60
- 验证点: 双进程联调（本机起两个 uvicorn: 端口 A 主控 + 端口 B 节点配 API_KEY）——节点 /api/remote/health 可探测、主控 switch 成功、embed 请求走 B、kill B 后 2 周期内降级 + embed fallback 本地成功、重启 B 后 3 周期恢复 + 300s 后 A 本地模型卸载（is_loaded 验证）; tests/ 全量 pytest 通过; 心跳日志独立文件确认
- 依赖: 全部

### 3.2 编码规则

- 强类型: 所有跨函数数据结构用 dataclass（规则 9）; `dict[str, str]` 仅限 .ai_env 解析边界
- 日志: 关键路径（状态机迁移、降级/恢复、卸载、鉴权拒绝、心跳失败）必须打点; remote_link 用独立 logger
- 禁止直接 open(.ai_env)——config_store 唯一读写方（现有红线）
- model_loader 单例模式保持（模块级单例 + 委托函数，消费方零改动）
- token 比较用 secrets.compare_digest; 不记录 token 明文到日志（仅前 6 位）
- 前端沿用 antd + 现有毛玻璃风格; 不引入新依赖

---

## §4 验收标准

### 4.1 功能验收

1. 节点部署: Mac Mini 配 CONTROL_API_KEY 后绑定 0.0.0.0、三模型启动预加载、/api/remote/health 返回指纹; 局域网访问管理类 API 返回 403
2. 主控切换: 配 URL+TOKEN → 切换远程（校验失败给原因; 成功 ENABLED=1 按钮翻转）→ /embed /rerank /api/ocr/extract、graphiti 写入、memory 写入全部实际走远程（节点日志可见请求，本地模型未加载）
3. 降级: kill 节点 → ≤2 心跳周期（~10s）内状态 DEGRADED → 在途+新请求 fallback 本地（结果正确、无错误抛出）→ 本地模型自动加载 → 前端红闪 + 原因显示
4. 恢复: 重启节点 → 3 连续成功 → 切回远程 → 300s 稳定期后本地三模型卸载（is_loaded=False / OCR state=idle; 内存释放可用 footprint 验证）
5. 开关忠实性: DEGRADED 期间前端开关仍显示 ENABLED=true（配置值），实际模式标红显示本地
6. 常驻: Mac Mini 配 CONTROL_RESIDENT=1 → 无 opencode 心跳 90s 后不自杀
7. 自动启动: AUTOSTART=1 + API 调用 → LaunchAgent 安装成功（launchctl list 可见）; 前端有自动登录提示
8. 心跳日志: DATA_DIR/logs/remote-link.log 存在且 control.log 无 remote_link 记录

### 4.2 回归验收

- 本地默认模式（不配任何远程 KEY）行为与改造前完全一致: 懒加载、预加载、OCR 空闲卸载、/health 语义、心跳自杀、事件库读写
- tests/ 全量 pytest 通过（含既有 test_control.py / test_e2e_real.py 可跑部分）
- 前端 bun run build 成功; 环境总览/运行状态两页功能不回退

### 4.3 架构验收

- grep: _MlxWorker 零残留（三模型生命周期收口到 ManagedModel 完成）
- grep: .ai_env 直接 open 仅 config_store（+server.py is_dev_mode 既有豁免）
- LockedEmbedder/LockedReranker 对外签名与返回类型不变（MemoryDB/graphiti 零改动确认）
- 消费方（mcp-servers/、graphiti_config、knowledge_store）零文件改动

---

## §5 与现有需求文档的关系

- 与 2026-09-25-locked-embedder-serialization.md: 本需求保持推理串行不变量，机制从"_infer_lock"升级为"worker FIFO 串行"（串行语义更强: 同线程执行），MPS 堆损坏防线不弱化
- 与 2026-08-22-ocr-in-process.md / 2026-08-22-ocr-drop-refcount.md: OCR 生命周期机制（队列卸载/空闲 reaper）语义不变，实现泛化迁移到 model_lifecycle.py（统一抽象，用户明确要求收口）
- 与 2026-08-22-heartbeat-no-users-file.md: 心跳自杀机制不变，仅增加 resident 豁免分支
- 与 2026-08-15-control-frontend-redesign.md: 前端新增第三页签，延续既有设计语言
