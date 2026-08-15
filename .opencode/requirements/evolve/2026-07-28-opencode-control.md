# OpenSecurity 控制台（opencode-control）

## §1 背景与目标

### 1.1 来源

随着 OpenSecurity 项目复杂度增长（9 个一级目录、24+ Python 包、8+ 外部工具、Docker 基础设施、本地 AI 模型），暴露了三个核心问题：

1. **embed_server 并发启动**（来源：2026-07-26-embed-server-startup.md）：每个 opencode 进程各自 spawn 一份 embed_server，每份加载 6.5GB BGE-M3 模型。多 opencode 进程并行时内存翻倍。
2. **状态不可见**：依赖检测、工具检测、服务状态全靠命令行 detect_env.py 输出文字流，故障排查靠 grep。Web/IDE 用户（通过 opencode ACP）连命令行都看不到。
3. **职责散乱**：detect_env.py 既装 Python 包又检测外部工具；.ai_env 被 detect_env.py、Plugin、events MCP 多处读取；端口文件被 Plugin 和 embed_client 多处消费。

### 1.2 现状问题

| 问题 | 现状 | 影响 |
|------|------|------|
| **embed_server 并发启动** | 每个 opencode spawn 一份，`detached:false` 跟随父进程 | 多 opencode 进程时 6.5GB 模型重复加载 |
| **状态文字流** | detect_env.py 输出 `[✓]/[✗]` 文字 | 故障排查靠 grep，Web/IDE 用户看不到 |
| **职责散乱** | detect_env.py 既装包又测工具；.ai_env 多头读 | 改一处要同步多处，易出 bug |
| **配置散落** | .ai_env 被 detect_env.py、Plugin venv.ts、events MCP 读 | 没有单一管理入口 |
| **端口读取散落** | `.embed_server_port` 被 Plugin 和 embed_client 读 | 改名要改多处 |
| **切换 agent 检测时机乱** | Plugin 在 chat.message 等多个 hook 做检测 | 检测逻辑分散，缺漏 |
| **缺依赖告知粗糙** | detect_env.py 返回文字 install_guide | 用户面对长文字流，没有可操作 UI |
| **前端资源** | 无（opencode TUI 覆盖不全） | Web/IDE 用户无 GUI |

### 1.3 目标

**核心目标**：用单一控制台进程解决"并发启动 + 状态可视化 + 配置/资源收口"三个问题。

**五层分层架构**（核心设计原则）：

| 层 | 内容 | 检测方 | 缺失告知 |
|----|------|-------|---------|
| 第一层 | conda（必须存在） | Plugin | 对话框 abort + 安装指引 |
| 第二层 | Python 依赖（pip 包 + 编译器存在性） | detect_env.py | 对话框 abort + 提示跑 install.sh |
| 第三层 | 手动安装的外部工具（Docker、IDA、apktool 等） | 控制台 | 对话框 abort + 控制台地址 |
| 第四层 | 可视化管理的资源（Docker 镜像、模型、API Key） | 控制台 | 控制台 GUI 红灯 + 操作按钮 |
| 第五层 | 配置类数据（DEEPSEEK_API_KEY、IDA_PRO_HOME 等） | 控制台 | 控制台 GUI 顶部 banner + 配置对话框 |

**关键设计原则——收口**：

| 收口点 | 唯一责任方 | 消费方 |
|--------|-----------|-------|
| 配置读写 | 控制台（config_store.py + .ai_env） | Plugin 通过 HTTP，agent 通过环境变量 |
| 端口读取 | Plugin（读端口文件 → 注入 MCP env） | MCP server 通过环境变量 |
| 文件锁 | 控制台（process_lock.py） | 控制台启动逻辑 |
| 引用计数 | Plugin（exit handler + users 文件） | 控制台生命周期 |
| 扫描逻辑 | 控制台（scanner.py） | 前端、Plugin 等待结果 |
| 模型加载 | 控制台（model_loader.py，来自 embed_server.py） | embed 路由 |

**控制台 = embed_server 的超集**：当前 `mcp-servers/embed_server.py` 的全部功能融合到控制台后端，新增资源管理 + 配置管理 + Web 前端。

### 1.4 范围（不做的事）

- ❌ **不做守护进程**：控制台是普通 Web 进程，由 opencode 启动 + 引用计数管理生命周期（用户不直接启停，但也不是 launchd/systemd/Windows Service）
- ❌ **不做 GPU 实时监控**：只查 GPU 规格（一次性，用于判断模型/功能适用性），不持续采样
- ❌ **不引入 sqlite**：配置全用 .ai_env，无运行时数据要存
- ❌ **不打包可执行文件**：控制台跑在 `~/bw-security-analysis/.venv`，跟 embed_server 共享环境
- ❌ **不做 Plugin 内 TUI 命令**：可视化全部由独立 Web GUI 承担

---

## §2 技术方案

### 2.1 系统组件与通信

```
┌──────────────────────────────────────────────────────────────┐
│  用户交互层                                                  │
│  ┌──────────────────┐    ┌─────────────────────────────┐    │
│  │ opencode TUI     │    │ 浏览器                      │    │
│  │ （对话框）        │    │ http://localhost:9776       │    │
│  └────────┬─────────┘    └──────────┬──────────────────┘    │
└───────────┼──────────────────────────┼──────────────────────┘
            │ session.abort + message  │ HTTP /api/*
            ↓                          ↓
┌──────────────────────────────────────────────────────────────┐
│  Plugin（TS，跑在 opencode 进程内）                          │
│  ──────────────────────────────────────────────────────────  │
│  职责（只管第一二层 + 启动控制台 + 端口/配置收口消费）：     │
│  • 第一层检测：isCondaInstalled()                            │
│  • 第二层检测：调 detect_env.py check-preinstall             │
│  • 启动控制台（spawn + 引用计数）                            │
│  • 读端口文件 → env 注入给 MCP server                        │
│  • HTTP /api/config + 内存缓存 → shell.env 注入              │
│  • chat.message：waitFor 三阶段（detect_env → control_startup │
│    → control_scan）→ 缺失时 abort + 提示控制台地址           │
└──────────────────────────────────────────────────────────────┘
            ↑ HTTP /api/config           ↓ spawn + HTTP /api/embed
┌──────────────────────────────────────────────────────────────┐
│  opencode-control（Python FastAPI，独立进程）                │
│  ──────────────────────────────────────────────────────────  │
│  路由模块：                                                  │
│  • routes/embed.py：/embed, /rerank（替代 mcp-servers/embed_server.py）│
│  • routes/health.py：/health（模型加载状态）                 │
│  • routes/scan.py：/api/scan（全量扫描，第三~五层）          │
│  • routes/deps.py：/api/deps（依赖详情）                     │
│  • routes/install.py：/api/install（pip 一键装包）           │
│  • routes/docker.py：/api/docker/*（容器管理）               │
│  • routes/config.py：/api/config/*（配置 CRUD）              │
│  • routes/hardware.py：/api/hardware（CPU/内存/GPU 规格）    │
│  • /：静态文件（dist/）或 dev 提示                           │
│                                                              │
│  业务模块：                                                  │
│  • services/config_store.py：.ai_env 唯一读写               │
│  • services/model_loader.py：BGE-M3 加载（来自 embed_server.py）│
│  • services/scanner.py：第三~五层扫描                        │
│  • services/docker_manager.py：Docker 操作（迁移自 detect_env.py）│
│  • services/tools_detector.py：外部工具检测（迁移自 detect_env.py）│
│  • services/process_lock.py：跨平台文件锁（portalocker）     │
│  • services/port_manager.py：端口分配 + 端口文件             │
│  • services/ref_counter.py：引用计数（被 Plugin 调用）       │
└──────────────────────────────────────────────────────────────┘
            ↓ subprocess
┌──────────────────────────────────────────────────────────────┐
│  detect_env.py（精简版，只管第二层）                         │
│  ──────────────────────────────────────────────────────────  │
│  保留：                                                      │
│  • _find_conda（第一层，Plugin 也独立检测）                  │
│  • _bootstrap_venv（创建 venv）                              │
│  • PYTHON_PACKAGES + _detect_compiler（第二层）              │
│  • install 子命令（装 Python 包 + 编译器支撑）               │
│  • check-preinstall 子命令（只查第二层，不读 .ai_env）       │
│                                                              │
│  删除：                                                      │
│  • EXTERNAL_TOOLS → 迁移到控制台 tools_detector.py           │
│  • Docker 检测 → 迁移到控制台 docker_manager.py              │
│  • 容器/镜像检测 → 同上                                      │
│  • embed_server 检测 → 删除（控制台替代）                    │
│  • _load_ai_env → 删除（第二层不依赖配置）                   │
└──────────────────────────────────────────────────────────────┘
```

**通信协议**：

| 通信 | 协议 | 数据 |
|------|------|------|
| opencode ↔ Plugin | TS import | 函数调用 |
| Plugin ↔ 用户对话框 | opencode session API | abort + 错误消息 |
| Plugin ↔ 控制台 | HTTP（/api/config, /api/embed, /api/scan） | JSON |
| Plugin ↔ 控制台（服务发现） | 文件（.opencode-control.port + users 文件 + flock） | 文本 |
| 浏览器 ↔ 控制台 | HTTP + SSE（docker pull 进度推送） | JSON + 流 |
| Plugin ↔ MCP server | env 注入（OPENCODE_CONTROL_PORT） | 环境变量 |
| 控制台 ↔ Docker | 子进程（docker CLI） | stdout |

**Plugin 启动控制台的时序（关键，决定 MCP server 能否拿到端口）**：

```
T0  opencode 启动 → Plugin setup()
T1  Plugin 检测 venv（第二层）
T2  venv 就绪 → Plugin spawn 控制台进程（detached:true + unref）
T3  控制台进程启动 → bind 端口 → 写端口文件
T4  Plugin 读端口文件 → 拿到端口
T5  Plugin 注册 MCP server（events、knowledge）：
    client.mcp.add 时 env 注入 OPENCODE_CONTROL_PORT
    ↓
T6  MCP server 子进程启动 → 通过环境变量拿端口
T7  MCP server 调 /embed（如果控制台还在加载模型，返回 503，MCP 等待重试）
```

**关键约束**：
- T5 必须在 T4 之后（注册 MCP 前端口已知）
- T7 在 T3 之后（控制台已监听，即使模型还在加载）
- events MCP server.py 现有的 `_wait_embed_server_ready` 逻辑保留（轮询 /health 直到 200）

**控制台启动失败的兜底**（Plugin 端处理）：

| 失败场景 | 检测方式 | 处理 |
|---------|---------|------|
| venv 缺包（fastapi、portalocker 等） | Plugin spawn 前 import 校验：`python -c "import fastapi, portalocker"` | abort + 提示跑 install.sh |
| 控制台进程 spawn 失败（权限等） | spawnProc 的 error 事件 | abort + 显示错误 |
| 端口都被占用（候选列表用尽） | 控制台 exit code = 3 | abort + 提示修改 config.json 端口 |
| 模型加载失败（torch、模型文件损坏） | /health 永远 503，Plugin 60s 超时 | abort + 提示重装模型或检查 venv |
| 控制台运行中崩溃 | embed_client 连续失败 3 次 → /health 验证 | 标记死亡，下次 chat.message 重新 spawn |

**install 路由的安全约束**：
- 控制台 bind 地址：**必须 `127.0.0.1`**（禁止 `0.0.0.0`），避免局域网内任意主机可调 /api/install 执行任意 pip install
- /api/install 白名单：只允许安装 PYTHON_PACKAGES 列表中的包名（控制台后端校验，前端传的 pkg_name 必须在白名单内）

### 2.2 控制台 = embed_server 超集

**事实**：当前 `mcp-servers/embed_server.py` 用 starlette + uvicorn，控制台用 FastAPI（基于 starlette）。技术栈一致，迁移顺滑。

**改造要点**：

1. **embed_server.py 拆分迁移**：
   - `bind_available_port` → `services/port_manager.py`
   - `get_embedder`、`get_reranker`、`_do_embed`、`_do_rerank` → `services/model_loader.py`
   - `embed`、`rerank`、`health` 路由 → `routes/embed.py` + `routes/health.py`
   - `__main__` → `server.py`（FastAPI app）

2. **B 方案改造（uvicorn 立即启动 + 后台线程加载模型）**：
   - 当前是 A 方案（先加载模型再启 uvicorn），用户访问 /health 会一直连接失败 30 秒
   - 改造为 B 方案：uvicorn.run 在最前面，模型后台线程加载，/health 返回 503 直到加载完
   - 解锁：控制台启动后立即提供 /api/scan、/api/config 等管理功能，不用等模型加载

3. **embed_client.py 改造（端口读取收口）**：
   - 删除 `_read_port()` 中读端口文件的逻辑
   - 只读环境变量 `OPENCODE_CONTROL_PORT`
   - Plugin spawn MCP server 时通过 env 注入端口

4. **端口文件改名**：`.embed_server_port` → `.opencode-control.port`（命名约定见 §3.4）

### 2.2.1 SSE 进度推送实现（docker pull 用）

```python
# routes/docker.py
from sse_starlette.sse import EventSourceResponse

@router.post("/docker/pull/{image}")
async def pull_image(image: str):
    async def event_generator():
        proc = await asyncio.create_subprocess_exec(
            "docker", "pull", image,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        async for line in proc.stdout:
            yield {"event": "progress", "data": line.decode().strip()}
        await proc.wait()
        yield {"event": "done", "data": f"exit_code={proc.returncode}"}
    return EventSourceResponse(event_generator())
```

依赖：`sse-starlette`（venv 已装，无需新增）

### 2.3 全局唯一进程（核心难点，所有边界已盘清）

**目标**：多个 opencode 进程共享同一个控制台进程。

**锁的归属与种类（明确化，避免双方拿同锁死锁）**：

| 锁文件 | 持有方 | 持锁时间 | 用途 |
|--------|-------|---------|------|
| `.opencode-control.lock` | **控制台进程**（启动期持有） | 毫秒级（检查 + 写端口文件后释放） | 防止两个控制台实例并发启动 |
| 无锁（原子 rename 保证） | Plugin 端 users 文件操作 | - | users 文件并发写入安全 |

**关键决策**：Plugin 端**不拿任何文件锁**。所有 Plugin 端的并发安全靠：
- users 文件用"临时文件 + rename"原子写
- PID 检测靠 `process.kill(pid, 0)`（OS 级原子）
- 端口发现靠 read-only 读端口文件

这样控制台锁不会被 Plugin 阻塞，Plugin 也不会被控制台阻塞。



```python
# services/process_lock.py 跨平台文件锁（portalocker）
import portalocker

LOCK_FILE = "$DATA_DIR/.opencode-control.lock"

def acquire_startup_lock() -> portalocker.Lock:
    """拿启动协调锁。拿不到说明其他进程在启动控制台。"""
    return portalocker.Lock(LOCK_FILE, flags=portalocker.LOCK_EX)
```

**启动流程（控制台进程）**：

```
1. 拿文件锁（portalocker.LOCK_EX）
   ↓
2. 检查端口文件 + PID 存活 + 端口连通
   - 全通过 → 已有实例：本进程退出（exit code 2 = 复用）
   - 任一失败 → 需要启动新实例
   ↓
3. 启动新实例（锁持有中）：
   - 候选端口列表：[配置端口 9776, 9777, 9778, 9779, 9780]
   - 依次尝试 bind
   - bind 成功 → 写端口文件（PID + 端口 + 启动时间）→ 释放锁 → 启动 uvicorn
   - 全部 bind 失败 → 报错"端口都被占用"
   ↓
4. 崩溃恢复（锁持有中）：
   - 旧端口文件 PID 死了 → 删 users 文件（所有引用作废）→ 当作首次启动
```

**引用计数（Plugin 端直接读写 users 文件，不走 HTTP）**：

> **设计说明**：原本设计为 Plugin 通过 HTTP /api/ref 操作引用，但 `process.on("exit")` 是同步 hook，不能 await HTTP。且 opencode 退出时控制台可能已死，HTTP 调用必然失败。所以 users 文件**双方都直接读写**，但格式严格统一（共享协议），双方各自实现解析。这不是"重复"，是"协议一致性"。

```
users 文件格式（$DATA_DIR/.opencode-control.users，共享协议）：
  pid=12345 start_time=1783000000
  pid=12346 start_time=1783000005
```

**Plugin 端（plugins/lib/ref-counter.ts）**：
- 启动时：read-only 检查端口文件 + PID 存活 + 端口连通 → 决定 spawn 还是复用 → 把 opencode 自己的 PID + start_time **原子加**到 users 文件（临时文件 + rename）
- 退出时（`process.on("exit")` 同步）：读 users → 删自己 PID → 原子写回 → users 空 → SIGTERM 控制台 + 删端口文件
- **不拿任何文件锁**（靠原子 rename 保证并发安全）

**控制台端（services/ref_counter.py）**：
- 启动时清洗 users（移除死 PID / start_time 不匹配的 PID 复用）
- 周期性后台任务（每 60 秒）清洗 users——处理 opencode 被 SIGKILL 后的残留
- users 清洗后空 → 控制台自杀（exit code 0）

**为什么控制台也要清洗**：opencode 被 SIGKILL 时 exit handler 不执行，users 文件残留幽灵 PID。控制台周期清洗兜底，避免孤儿进程永远运行。

**边界条件覆盖**（实测验证）：

| 边界 | 处理 |
|------|------|
| opencode 优雅退出 | exit handler 减引用 → users 空 → SIGTERM 控制台 |
| opencode 被 SIGTERM | Node.js 默认触发 exit → 同上 |
| opencode 被 SIGKILL / OOM | exit handler 不执行 → 控制台周期清洗（≤60s）兜底 |
| PID 复用 | start_time 校验（`ps -p PID -o lstart=`） |
| users 文件损坏 | 临时文件 + rename 原子写 |
| 控制台崩溃 | 端口文件 PID 死 → 下次 Plugin 启动重新 spawn |
| 多个 opencode 同时启动 | portalocker 互斥 |
| 控制台被 SIGKILL | portalocker 内核自动释放（实测） |
| 端口被其他程序占 | 候选端口列表 fallback |
| 模型加载失败 | /health 永远 503，Plugin 60s 超时后报错 + 标记控制台失败 |
| 控制台 spawn 失败（venv 缺包等） | Plugin 通过 import 校验提前发现，spawn 前 abort |
| 控制台运行中崩溃 | Plugin 调 /health 连续失败 3 次 → 标记控制台死亡 → 下次操作前尝试重启 |

**控制台崩溃的 Plugin 端检测**：
- `embed_client.py` 调 /embed 失败 → 抛 RuntimeError → agent 报错给 Plugin
- Plugin 检测到连续错误 → 调 `/health` 验证 → 失败则标记控制台死亡
- 下次 chat.message 时检测到 CONTROL_STARTUP_SERVICE 状态为 failed → 重新 spawn（先清理旧端口文件）

### 2.4 端口读取收口

**当前问题**：`.embed_server_port` 被 Plugin（pollEmbedServerHealth）和 embed_client.py（_read_port）两处消费。

**收口方案**：

```
Plugin 启动控制台
  ↓
Plugin 读 .opencode-control.port（唯一消费者）
  ↓
Plugin spawn MCP server 时通过 env 注入端口：
  env: { OPENCODE_CONTROL_PORT: "9776" }
  ↓
MCP server 子进程
  ↓
embed_client.py 只读环境变量 OPENCODE_CONTROL_PORT
  （删除读端口文件的逻辑）
```

**改动**：

| 文件 | 改动 |
|------|------|
| `mcp-servers/embed_client.py` | 删 `_read_port()` 读文件逻辑，只读环境变量 |
| `plugins/lib/mcp-manager.ts` | `client.mcp.add` 时 env 加 `OPENCODE_CONTROL_PORT` |
| `plugins/lib/constants.ts` | 端口文件常量改名 |

### 2.5 配置收口

**当前问题**：.ai_env 被 detect_env.py、Plugin venv.ts、events MCP 多处读，无统一管理。

**收口方案**：

```
┌──────────────────────────────────────────────────────────┐
│  .ai_env（单一真相源，唯一写入方：控制台）                │
└──────────────────────────────────────────────────────────┘
                          ↑ 读/写
┌──────────────────────────────────────────────────────────┐
│  控制台 config_store.py（唯一管理者）                     │
│  ────────────────────────────────────────────────────   │
│  • read_all()：读全部配置                                │
│  • read(key)：读单个                                     │
│  • write(updates)：批量更新（前端表单保存）              │
│  • write_one(key, value)：单条更新                       │
│  • delete(key)：删除                                     │
│  • required_status()：必要配置完整性                     │
└──────────────────────────────────────────────────────────┘
                          ↑ HTTP /api/config/*
┌──────────────────────────────────────────────────────────┐
│  Plugin control-config.ts（只读消费者，带缓存）           │
│  ────────────────────────────────────────────────────   │
│  • 启动时 fetch /api/config → 内存缓存                   │
│  • getConfig(key) / getAllConfig() 读缓存               │
│  • 不直接读 .ai_env                                      │
│  • 不主动刷新（用户改配置后重启 opencode 生效）          │
└──────────────────────────────────────────────────────────┘
                          ↓ shell.env hook 注入环境变量
┌──────────────────────────────────────────────────────────┐
│  events MCP / agent 子进程                               │
│  通过环境变量拿配置（IDA_PRO_HOME、DEEPSEEK_API_KEY）    │
└──────────────────────────────────────────────────────────┘
```

**API 设计**：

```
GET  /api/config                    → 全部配置（key-value 字典）
GET  /api/config/{key}              → 单个配置值
PUT  /api/config                    → 批量更新（前端表单保存用）
PUT  /api/config/{key}              → 更新单个配置
DELETE /api/config/{key}            → 删除配置项
GET  /api/config/required-status    → 必要配置完整性（前端 banner 用）
```

**必要配置清单**（控制台后端常量，前端 banner 用）：

```python
REQUIRED_CONFIGS = [
    ConfigField(key="DEEPSEEK_API_KEY", label="DeepSeek API 密钥", type="password",
                hint="获取地址：https://platform.deepseek.com/api-keys",
                validator=validate_api_key),
    ConfigField(key="IDA_PRO_HOME", label="IDA Pro 安装目录", type="path",
                hint="该目录下需有 idat 可执行文件",
                validator=validate_ida_pro_home),
]

def validate_ida_pro_home(value: str) -> tuple[bool, str]:
    """校验 IDA_PRO_HOME：目录存在 + idat 可执行文件存在。"""
    path = Path(value)
    if not path.exists():
        return False, f"目录不存在：{value}"
    exe = "idat.exe" if sys.platform == "win32" else "idat"
    if not (path / exe).exists():
        return False, f"目录下未找到 {exe}"
    return True, ""
```

前端 ConfigPage 表单保存时调 PUT /api/config，控制台对每个字段调 validator，校验失败返回 400 + 错误信息，前端在字段下方显示红色提示。

**未来扩展**：换 sqlite 只改 `services/config_store.py`（实现层），API 接口不变。

### 2.6 前端开发态/发布态（CONTROL_FRONTEND_DEV 开关）

**.ai_env 增加开关**：

```
# 控制台前端开发模式开关
# 启用（走 Vite 5173）：1 / true
# 禁用（用 dist/ 静态文件）：0 / false / 不配置
CONTROL_FRONTEND_DEV=0
```

**控制台启动判断**（`server.py`）：

**初始化顺序约束**：
1. server.py 启动时**直接读 .ai_env 文件**判断 dev 模式（不能用 config_store，因为 config_store 是控制台模块，启动前还没初始化）
2. config_store 初始化后，所有后续配置操作走 config_store
3. dev 模式判断是"启动期一次性读"，不算违反"配置收口"原则

```python
def is_dev_mode(opencode_root: str) -> bool:
    """启动期直接读 .ai_env（不走 config_store，避免循环依赖）。"""
    ai_env_path = Path(opencode_root) / ".ai_env"
    if not ai_env_path.exists():
        return False
    for line in ai_env_path.read_text().splitlines():
        if line.strip().startswith("CONTROL_FRONTEND_DEV"):
            _, _, value = line.partition("=")
            return value.strip().lower() in ("1", "true")
    return False

if is_dev_mode(opencode_root):
    # 开发态：不挂载 dist/，/ 路由返回 dev 提示
    @app.get("/")
    async def dev_hint():
        return {"mode": "dev", "hint": "请访问 http://localhost:5173"}
else:
    # 发布态：挂载 dist/
    dist_path = Path(__file__).parent.parent / "frontend" / "dist"
    if dist_path.exists():
        app.mount("/", StaticFiles(directory=str(dist_path), html=True))
```

**前端 API 客户端 baseURL 处理**：

```typescript
// control/frontend/src/api/client.ts
const BASE_URL = import.meta.env.DEV
  ? "http://localhost:9776"  // Vite dev 模式（5173 → 9776 跨域）
  : "";                      // release 模式（同源，空字符串）

export const api = axios.create({ baseURL: `${BASE_URL}/api` });
```

Vite dev 模式下 `import.meta.env.DEV === true`，构建后为 false。CORS 在控制台后端配置（开发态允许 5173 跨域）。

**dist/ 处理**：发布时 `bun run build` 生成 dist/，提交到 git。开发者本地改 `CONTROL_FRONTEND_DEV=1` 走 Vite。

---

## §3 实现规范

### 3.1 目录结构

```
.opencode/
├── control/                              # ★ 新增独立目录
│   ├── backend/                          # Python 后端
│   │   ├── server.py                     # FastAPI 主入口
│   │   ├── config.py                     # 控制台配置（端口候选、必要配置清单等）
│   │   ├── routes/                       # 路由模块
│   │   │   ├── embed.py                  # /embed, /rerank（来自 embed_server.py）
│   │   │   ├── health.py                 # /health
│   │   │   ├── scan.py                   # /api/scan（全量扫描，第三~五层）
│   │   │   ├── deps.py                   # /api/deps（依赖详情）
│   │   │   ├── install.py                # /api/install（pip 一键装包）
│   │   │   ├── docker.py                 # /api/docker/*（容器管理）
│   │   │   ├── config_route.py           # /api/config/*（配置 CRUD）
│   │   │   └── hardware.py               # /api/hardware（CPU/内存/GPU 规格）
│   │   ├── services/                     # 业务逻辑
│   │   │   ├── config_store.py           # .ai_env 唯一读写
│   │   │   ├── model_loader.py           # BGE-M3 加载（来自 embed_server.py）
│   │   │   ├── scanner.py                # 第三~五层扫描
│   │   │   ├── tools_detector.py         # 外部工具检测（迁移自 detect_env.py）
│   │   │   ├── docker_manager.py         # Docker 操作（迁移自 detect_env.py / events/server.py）
│   │   │   ├── process_lock.py           # 跨平台文件锁（portalocker）
│   │   │   ├── port_manager.py           # 端口分配 + 端口文件
│   │   │   └── ref_counter.py            # 引用计数（users 文件操作）
│   │   └── requirements.txt              # 控制台特有依赖（fastapi、portalocker）
│   │
│   ├── frontend/                         # React 前端
│   │   ├── src/
│   │   │   ├── App.tsx                   # 路由 + 布局
│   │   │   ├── pages/
│   │   │   │   ├── StatusPage.tsx        # 状态总览（默认页）
│   │   │   │   ├── DepsPage.tsx          # 依赖管理（按 agent + 全局分类）
│   │   │   │   ├── DockerPage.tsx        # Docker 资源管理
│   │   │   │   ├── ConfigPage.tsx        # 配置管理（表单 + 必要项 banner）
│   │   │   │   └── HardwarePage.tsx      # 硬件信息
│   │   │   ├── components/               # 通用组件（卡片、表格、状态灯、Banner）
│   │   │   ├── api/                      # API 客户端（axios + 类型定义）
│   │   │   ├── hooks/                    # 自定义 hooks（useConfig, useScan）
│   │   │   └── types/                    # TypeScript 类型
│   │   ├── dist/                         # 构建产物（发布态提交到 git）
│   │   ├── package.json
│   │   ├── vite.config.ts                # dev 代理 /api 到 9776
│   │   ├── tsconfig.json
│   │   └── .gitignore                    # 忽略 node_modules
│   │
│   └── README.md
│
├── mcp-servers/                          # embed_server.py 删除，embed_client.py 改造
│   ├── embed_client.py                   # 改造：删端口文件读取，只读环境变量
│   ├── events/                           # 不动
│   └── knowledge/                        # 不动
│
├── binary-analysis/scripts/
│   └── detect_env.py                     # 精简：删 EXTERNAL_TOOLS + Docker 检测 + .ai_env 读取
│
└── plugins/
    ├── security-analysis.ts              # 改造：spawn 控制台 + 三阶段 waitFor
    └── lib/
        ├── control-manager.ts            # ★ 新增：控制台启动 + 端口发现 + 引用计数
        ├── control-config.ts             # ★ 新增：控制台配置 API + 缓存
        ├── mcp-manager.ts                # 改造：注册 MCP 时 env 注入端口
        ├── service-registry.ts           # 不动
        ├── venv.ts                       # 改造：删 readAiEnv/getIdatPath
        └── constants.ts                  # 改造：端口文件改名 + 新增 CONTROL_SCAN_SERVICE 等
```

### 3.2 改动范围表

| 文件 | 类型 | 改动要点 | 行数估算 |
|------|------|---------|---------|
| `control/backend/server.py` | 新增 | FastAPI 主入口、B 方案启动 | ~150 |
| `control/backend/config.py` | 新增 | 端口候选、必要配置清单常量 | ~50 |
| `control/backend/routes/embed.py` | 新增 | /embed, /rerank（迁移自 embed_server.py） | ~80 |
| `control/backend/routes/health.py` | 新增 | /health（含模型加载状态） | ~30 |
| `control/backend/routes/scan.py` | 新增 | /api/scan（全量扫描） | ~80 |
| `control/backend/routes/deps.py` | 新增 | /api/deps（按 agent 过滤） | ~60 |
| `control/backend/routes/install.py` | 新增 | /api/install（pip 调用） | ~60 |
| `control/backend/routes/docker.py` | 新增 | /api/docker/* | ~150 |
| `control/backend/routes/config_route.py` | 新增 | /api/config/* | ~80 |
| `control/backend/routes/hardware.py` | 新增 | /api/hardware | ~80 |
| `control/backend/services/config_store.py` | 新增 | .ai_env 读写 | ~120 |
| `control/backend/services/model_loader.py` | 新增 | BGE-M3 加载（迁移） | ~100 |
| `control/backend/services/scanner.py` | 新增 | 全量扫描协调 | ~120 |
| `control/backend/services/tools_detector.py` | 新增 | 迁移自 detect_env.py EXTERNAL_TOOLS | ~200 |
| `control/backend/services/docker_manager.py` | 新增 | 迁移自 detect_env.py + events/server.py | ~150 |
| `control/backend/services/process_lock.py` | 新增 | portalocker 跨平台锁 | ~80 |
| `control/backend/services/port_manager.py` | 新增 | 端口分配 + 端口文件 | ~80 |
| `control/backend/services/ref_counter.py` | 新增 | users 文件操作 | ~100 |
| `control/backend/requirements.txt` | 新增 | fastapi、portalocker | ~5 |
| `control/frontend/src/*` | 新增 | React 完整前端 | ~3500 |
| `control/frontend/package.json` | 新增 | 依赖声明 | ~30 |
| `control/frontend/vite.config.ts` | 新增 | Vite 配置 | ~30 |
| `mcp-servers/embed_server.py` | **删除** | 功能迁移到 control/backend | -180 |
| `mcp-servers/embed_client.py` | 修改 | 删端口文件读取，只读环境变量 | -20 / +5 |
| `binary-analysis/scripts/detect_env.py` | 修改 | 删 EXTERNAL_TOOLS + Docker + .ai_env | -300 |
| `plugins/security-analysis.ts` | 修改 | spawn 控制台 + 三阶段 waitFor | -150 / +200 |
| `plugins/lib/control-manager.ts` | 新增 | 控制台启动 + 端口发现（不含引用计数） | ~250 |
| `plugins/lib/ref-counter.ts` | 新增 | users 文件读写（与控制台共享格式协议） | ~100 |
| `plugins/lib/control-config.ts` | 新增 | 配置 API + 缓存 | ~80 |
| `plugins/lib/mcp-manager.ts` | 修改 | env 注入端口 | +10 |
| `plugins/lib/venv.ts` | 修改 | 删 readAiEnv/getIdatPath | -150 |
| `plugins/lib/constants.ts` | 修改 | 端口文件改名 + 新 service 名 | +20 |
| **合计** | | | **~6500 行** |

### 3.3 抽象点清单（关键审计维度）

按"是否可抽象"审计维度，本次改造必须收口的抽象点：

| 抽象点 | 收口模块 | 严格规则 |
|--------|---------|---------|
| **配置读写** | `services/config_store.py` | 禁止其他文件直接 open(.ai_env)。控制台 routes/config_route.py 是唯一对外接口 |
| **文件锁** | `services/process_lock.py` | 禁止其他文件直接 portalocker.Lock。**只有控制台进程**启动期持锁（防止并发启动）。Plugin 端**不持锁**，靠原子 rename 保证 users 文件并发安全 |
| **端口分配** | `services/port_manager.py` | 禁止其他文件直接 socket.bind。bind + 写端口文件 + 读端口文件全在本模块。**端口分配需要锁保护时调用 process_lock**（依赖关系：port_manager → process_lock） |
| **引用计数** | 双方直接读写 users 文件（共享格式协议），Plugin 端 `plugins/lib/ref-counter.ts`，控制台端 `services/ref_counter.py` | 控制台周期清洗 + 自杀，Plugin exit handler 减引用 |
| **扫描协调** | `services/scanner.py` | 单一扫描入口，避免多次扫描并发 |
| **模型加载** | `services/model_loader.py` | 唯一持有 BGE-M3 实例（线程安全单例） |
| **Docker 操作** | `services/docker_manager.py` | 唯一调 docker CLI 的地方，封装跨平台 |
| **工具检测** | `services/tools_detector.py` | 唯一检测外部工具的地方，迁移自 detect_env.py |
| **常量提取** | `control/backend/config.py` | 端口候选、必要配置清单、超时时间等常量统一在此 |

**反重复原则**：
- 任何"读 .ai_env"逻辑只能出现在 `config_store.py`（一处）
- 任何"读端口"逻辑只能出现在 `port_manager.py`（一处）+ Plugin `control-manager.ts`（消费方）
- 任何"PID 存活检测"逻辑提取为 `process_lock.py` 的公共函数 `is_process_alive(pid, start_time)`（Plugin TS 端在 ref-counter.ts 内独立实现，但用相同算法）
- 任何"原子写文件"逻辑提取为公共函数 `atomic_write(path, content)`（Python 在 process_lock.py，TS 在 ref-counter.ts，用相同实现：临时文件 + rename）
- users 文件格式是**共享协议**（双方各自实现解析，但格式严格一致），不算重复

**复制粘贴检测**（审计时 grep 验证）：
- `grep -rn "open.*\.ai_env" .opencode/` 只匹配 `config_store.py` **+ server.py 的 is_dev_mode 函数**（启动期一次性读，例外允许）
- `grep -rn "socket.bind\|bind_available_port" .opencode/` 应该只匹配 `port_manager.py`
- `grep -rn "portalocker\|fcntl.flock\|msvcrt.locking" .opencode/` 应该只匹配 `process_lock.py`
- `grep -rn "EXTERNAL_TOOLS\|external_tools" .opencode/` 不应匹配 detect_env.py

### 3.4 编码规则

#### 跨平台

- **文件锁**：用 `portalocker`（跨平台统一），禁止直接 `fcntl` 或 `msvcrt`
- **PID 检测**：用 `os.kill(pid, 0)`（Python 跨平台）
- **进程启动时间**：跨平台函数 `get_process_start_time(pid)`：
  - macOS/Linux：`ps -p PID -o lstart=`
  - Windows：PowerShell `Get-Process -Id PID | Select-Object StartTime`
- **spawn detached**：Node.js `child_process.spawn` 的 `detached:true` + `unref()`
- **路径分隔符**：用 `os.path.join` / `pathlib.Path`，禁止硬编码 `/` 或 `\`

#### 命名约定

- 端口文件：`.opencode-control.port`（统一改名）
- 锁文件：`.opencode-control.lock`
- users 文件：`.opencode-control.users`
- 环境变量：`OPENCODE_CONTROL_PORT`（传给 MCP server）
- service 名：`CONTROL_STARTUP_SERVICE`、`CONTROL_SCAN_SERVICE`（区分控制台启动 vs 扫描完成）

#### 收口原则

- 写入操作必须收口到一处（.ai_env 写只在控制台）
- 读取操作可以多处，但都通过收口模块的函数（不直接 open 文件）
- 跨进程通信走 HTTP（不要走共享文件 + 文件锁，除了端口发现这种必要场景）

### 3.5 实施步骤拆分

按规则 1.5，每步 ≤ 200 行（不含注释和空行），每步独立可验证。

**步骤 1. 控制台后端骨架 + embed 迁移**
- 文件：`control/backend/server.py`、`config.py`、`routes/embed.py`、`routes/health.py`、`services/model_loader.py`、`requirements.txt`
- 预估行数：~180
- 验证点：`python server.py` 启动后 `curl http://localhost:9776/health` 返回 503（模型加载中），加载完成后（视硬件 6-30 秒）返回 200；`curl -X POST /embed -d '{"inputs":"test"}'` 返回向量
- 依赖：无

**步骤 2. 跨平台文件锁 + 端口管理**
- 文件：`services/process_lock.py`、`services/port_manager.py`、`config.py`（候选端口常量）
- 预估行数：~150
- 验证点：写测试脚本验证 flock 在 SIGKILL 后释放；验证端口候选 fallback；验证端口文件写入格式
- 依赖：步骤 1

**步骤 3. 引用计数 + 单实例检测**
- 文件：`services/ref_counter.py`、修改 `server.py` 加单实例检测
- 预估行数：~120
- 验证点：
  - 并行启动测试：用 shell 脚本 `for i in 1 2 3; do python server.py & done; wait`，验证只有第一个 exit code 0，其余 exit code 2
  - users 清洗测试：手动写入 users 文件加一个不存在的 PID，启动控制台后验证该 PID 被清洗
  - 自杀测试：清空 users 文件后启动控制台，验证控制台周期任务（≤60s）后 exit 0
- 依赖：步骤 2

**步骤 4. 配置管理（config_store + API）**
- 文件：`services/config_store.py`、`routes/config_route.py`
- 预估行数：~180
- 验证点：`curl /api/config` 返回当前 .ai_env 内容；`curl -X PUT /api/config -d '{"DEEPSEEK_API_KEY":"sk-test"}'` 写入后 .ai_env 文件实际改变；`curl /api/config/required-status` 返回必要配置完整性
- 依赖：步骤 1

**步骤 5. 工具检测迁移（tools_detector.py + 路由）**
- 文件：`services/tools_detector.py`、`routes/deps.py`（依赖详情路由）
- 预估行数：~200
- 验证点：`curl /api/deps?agent=mobile-analysis` 返回 apktool/jadx/adb 状态；`curl /api/deps` 返回所有 agent 工具状态
- 依赖：步骤 1（控制台骨架）

**步骤 5.1. Docker 管理迁移（docker_manager.py + 路由）**
- 文件：`services/docker_manager.py`、`routes/docker.py`
- 预估行数：~200
- 验证点：`curl /api/docker/status` 返回 daemon + 容器状态；`curl /api/docker/containers` 返回容器列表
- 依赖：步骤 5（共用 routes/deps.py 的扫描框架）

**步骤 6. 全量扫描协调（scanner + scan 路由）**
- 文件：`services/scanner.py`、`routes/scan.py`、`routes/install.py`、`routes/hardware.py`
- 预估行数：~180
- 验证点：`curl /api/scan` 并行扫描所有 agent，返回完整结果；install 路由能 pip install 指定包
- 依赖：步骤 5、5.1

**scanner.py 并发实现**（关键设计）：

```python
# services/scanner.py
import asyncio
from concurrent.futures import ThreadPoolExecutor

class Scanner:
    def __init__(self):
        self._cache = None           # 扫描结果缓存
        self._cache_time = 0         # 缓存时间戳
        self._scanning = False       # 是否正在扫描（避免并发）
        self._CACHE_TTL = 30         # 缓存 30 秒

    async def scan_all(self, force_refresh: bool = False) -> ScanResult:
        # 1. 命中缓存且未过期 → 直接返回
        if not force_refresh and self._cache and (time.time() - self._cache_time < self._CACHE_TTL):
            return self._cache
        
        # 2. 已有扫描在跑 → 等待结果（避免重复扫描）
        if self._scanning:
            while self._scanning:
                await asyncio.sleep(0.5)
            return self._cache
        
        # 3. 启动新扫描
        self._scanning = True
        try:
            # 工具检测是同步 IO（subprocess），用线程池并发
            with ThreadPoolExecutor(max_workers=8) as executor:
                loop = asyncio.get_event_loop()
                
                # 并行扫描每个 agent 的工具
                agent_tasks = [
                    loop.run_in_executor(executor, tools_detector.scan_agent, agent)
                    for agent in ALL_AGENTS
                ]
                # 并行扫描全局资源
                global_task = loop.run_in_executor(executor, self._scan_global)
                
                agent_results = await asyncio.gather(*agent_tasks)
                global_result = await global_task
            
            self._cache = ScanResult(agents=agent_results, global_=global_result)
            self._cache_time = time.time()
            return self._cache
        finally:
            self._scanning = False
```

**扫描缓存策略**：
- 30 秒缓存（避免前端频繁刷新触发全量扫描）
- `force_refresh=true` 强制刷新（前端"刷新"按钮）
- 扫描中重复请求等待结果（不重复扫描）

**GPU 规格跨平台查询命令清单**（routes/hardware.py 实现）：

```python
async def get_gpu_info() -> list[GPUInfo]:
    """跨平台 GPU 规格查询（一次性，启动时调用）。"""
    if sys.platform == "darwin":
        # macOS: system_profiler
        r = subprocess.run(["system_profiler", "SPDisplaysDataType"], 
                          capture_output=True, text=True, timeout=5)
        return parse_macos_gpu(r.stdout)
    elif sys.platform == "win32":
        # Windows: PowerShell Get-CimInstance（wmic 已弃用）
        r = subprocess.run(
            ["powershell", "-Command", 
             "Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM"],
            capture_output=True, text=True, timeout=5)
        return parse_windows_gpu(r.stdout)
    else:
        # Linux: 优先 nvidia-smi，回退 lspci
        if shutil.which("nvidia-smi"):
            r = subprocess.run(
                ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=5)
            return parse_nvidia_gpu(r.stdout)
        elif shutil.which("lspci"):
            r = subprocess.run(["lspci", "-nn"], capture_output=True, text=True, timeout=5)
            return parse_linux_gpu(r.stdout)
        return []
```

**用途判断**（前端展示）：
- Apple Silicon + Metal → 显示"可用 MLX/MPS 加速"
- NVIDIA + ≥8GB 显存 → 显示"可用 GPU 推理"
- 集显 / 显存 <4GB → 显示"限制 CPU 推理"
- 无 GPU → 显示"仅 CPU"

**步骤 7. detect_env.py 精简**
- 文件：`binary-analysis/scripts/detect_env.py`（删 EXTERNAL_TOOLS + Docker + .ai_env 读取）
- 预估行数：-300（删除）/ +30（重构 check-preinstall 不读 .ai_env）
- 验证点：`python detect_env.py check-preinstall binary-analysis` 仍能正常返回 Python 包状态；`grep -n "EXTERNAL_TOOLS\|_load_ai_env" detect_env.py` 无匹配
- 依赖：步骤 5（确认迁移完成）

**步骤 8. embed_client.py 端口读取收口**
- 文件：`mcp-servers/embed_client.py`
- 预估行数：-25 / +5
- 验证点：删 `_read_port` 内读端口文件逻辑，只读环境变量；grep 不应再匹配 `.embed_server_port`
- 依赖：步骤 1

**步骤 9. Plugin 引用计数模块（ref-counter.ts）**
- 文件：`plugins/lib/ref-counter.ts`、`plugins/lib/constants.ts`（加 users 文件路径常量）
- 预估行数：~100
- 验证点：单元测试覆盖 addUserPid、removeUserPid、atomicWrite；模拟 SIGKILL 后 users 文件残留的场景，验证下次启动清洗逻辑
- 依赖：无（纯 TS 逻辑，独立于控制台后端）

**步骤 10. Plugin 控制台启动管理（control-manager.ts）**
- 文件：`plugins/lib/control-manager.ts`、`plugins/lib/constants.ts`（加 CONTROL_STARTUP_SERVICE 等）、修改 `plugins/security-analysis.ts` 替换 startEmbedServer
- 预估行数：~200
- 验证点：opencode 启动时 spawn 控制台；chat.message 三阶段等待（detect_env → control_startup → control_scan）；退出时减引用正确
- 依赖：步骤 1-7、步骤 9

**三阶段 waitFor 的超时与失败处理**（关键设计）：

| 阶段 | Service 名 | 超时 | 失败处理 |
|------|-----------|------|---------|
| 1. detect_env | DETECT_ENV_SERVICE | 30s（已有逻辑） | abort + 提示跑 install.sh |
| 2. control_startup | CONTROL_STARTUP_SERVICE | 60s（端口文件 5s + 模型加载 30s + 余量） | abort + 显示具体错误（spawn 失败 / 端口占用 / 模型超时） |
| 3. control_scan | CONTROL_SCAN_SERVICE | 90s（Docker + 工具检测） | abort + 提示控制台地址（扫描已完成但有问题） |

**阶段失败的具体消息模板**：

```
[阶段 1 失败] Python 依赖未就绪：xxx
请运行：bash install.sh

[阶段 2 失败] 控制台启动失败：<具体原因>
- spawn 失败：<错误信息>
- 端口占用：端口 9776-9780 都被占用，请修改 control/config.json
- 模型超时：BGE-M3 加载超过 60s，请检查 venv 完整性

[阶段 3 缺失] <agent> 缺失：<缺失项列表>
请打开控制台修复：http://localhost:9776/?agent=<agent>
```

**步骤 11. Plugin 配置获取（control-config + shell.env）**
- 文件：`plugins/lib/control-config.ts`、修改 `plugins/lib/venv.ts`（删 readAiEnv/getIdatPath）、修改 `plugins/security-analysis.ts`（getIdatPath 调用方改用 control-config）、修改 `plugins/lib/persistence.ts`（readAiEnv 调用方改用 control-config，取 RESUME_ANALYSIS_ENABLED）
- 预估行数：~150
- 验证点：opencode 启动后 `getAllConfig()` 返回控制台 .ai_env 内容；agent 调 idat 时环境变量有 IDA_PRO_HOME；persistence.ts 仍能正确读 RESUME_ANALYSIS_ENABLED
- 依赖：步骤 4、10

**调用方迁移清单**（避免遗漏）：
- `plugins/lib/persistence.ts:214` `readAiEnv()[ENV_KEY_RESUME_ANALYSIS]` → `await getConfig("RESUME_ANALYSIS_ENABLED")`
- `plugins/security-analysis.ts:134` `getIdatPath()` 环境检测 → 删除（IDA Pro 检测迁控制台）
- `plugins/security-analysis.ts:1437` `getIdatPath()` shell.env 注入 → `await getConfig("IDA_PRO_HOME")` 拼路径

**步骤 12. Plugin mcp-manager 端口注入**
- 文件：`plugins/lib/mcp-manager.ts`
- 预估行数：+15
- 验证点：注册 MCP server 时 env 含 `OPENCODE_CONTROL_PORT`；events MCP 启动后能调通控制台 /embed
- 依赖：步骤 8、10

**步骤 13. 前端骨架（React + Vite + 路由）**
- 文件：`control/frontend/package.json`、`vite.config.ts`、`src/App.tsx`、`src/main.tsx`、`src/api/client.ts`
- 预估行数：~200
- 验证点：`bun install && bun run dev` 启动 Vite 5173；浏览器打开看到空白页（路由占位）；`bun run build` 生成 dist/
- 依赖：无（可与后端并行）

**步骤 14. 前端 - 状态总览页 + 必要配置 banner**
- 文件：`src/pages/StatusPage.tsx`、`src/components/RequiredConfigBanner.tsx`、`src/pages/ConfigPage.tsx`、`src/components/ConfigEditDialog.tsx`
- 预估行数：~200
- 验证点：访问控制台首页看到硬件信息卡片；缺必要配置时顶部红色 banner；点击 banner 弹出配置对话框；保存后 .ai_env 实际改变
- 依赖：步骤 13

**步骤 15. 前端 - 依赖管理页（含全量扫描 loading）**
- 文件：`src/pages/DepsPage.tsx`、`src/components/AgentDepsSection.tsx`、`src/components/GlobalResourcesSection.tsx`、`src/components/MissingSummary.tsx`、`src/hooks/useScan.ts`
- 预估行数：~200
- 验证点：进入页面看到 loading 动画 → 扫描完成显示缺失项汇总 → 按 agent 折叠查看细节 → 全局资源区块显示 Docker/模型/API Key
- 依赖：步骤 14

**步骤 16. 前端 - Docker 管理 + 安装操作**
- 文件：`src/pages/DockerPage.tsx`、`src/components/ContainerCard.tsx`、`src/components/ImageCard.tsx`、`src/components/PullProgress.tsx`（SSE 接收）
- 预估行数：~200
- 验证点：Docker 页面显示 daemon 状态、容器列表（启停按钮）、镜像列表（拉取按钮带进度）；点击"一键安装"pip 包后状态刷新
- 依赖：步骤 15

**步骤 17. .ai_env 开关 + dist 构建脚本**
- 文件：修改 `.opencode/.ai_env` 增加 `CONTROL_FRONTEND_DEV=0`、修改 `control/backend/server.py` 加 dev 模式判断、新增 `control/build.sh`（前端构建脚本）
- 预估行数：~50
- 验证点：CONTROL_FRONTEND_DEV=1 时访问 9776 返回 dev 提示；CONTROL_FRONTEND_DEV=0 时返回 dist/index.html
- 依赖：步骤 14

**dist/ 入 git 的 .gitignore 处理**：

```gitignore
# control/frontend/.gitignore
node_modules/
# 注意：dist/ 不在此处忽略，需要提交到 git（发布态用户用）
```

```gitignore
# .opencode/.gitignore（如果有）
# control/frontend/dist/ 不忽略
```

**构建脚本** `control/build.sh`：

```bash
#!/usr/bin/env bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/frontend"

# 检测包管理器（bun 优先，npm 兜底）
if command -v bun &>/dev/null; then
  PKG_MGR=bun
elif command -v npm &>/dev/null; then
  PKG_MGR=npm
else
  echo "[ERROR] 未找到 bun 或 npm" >&2
  exit 1
fi

echo "[*] 安装依赖（$PKG_MGR install）..."
$PKG_MGR install

echo "[*] 构建前端（$PKG_MGR run build）..."
$PKG_MGR run build

echo "[+] dist/ 已生成"
```

---

## §4 验收标准

### 4.1 功能验收

| # | 验收项 | 验证方法 | 通过标准 |
|---|-------|---------|---------|
| F1 | 控制台启动 | `bash install.sh` 后启动 opencode，看 Plugin 日志 | spawn 控制台 → /health 200 → 注册成功 |
| F2 | 控制台全局唯一 | 启动两个 opencode 进程，看 Plugin 日志 | 第二个 opencode 检测到端口文件 + PID 存活 + 端口连通 → 不 spawn，复用现有控制台（Plugin 日志记录 "control already running, reuse"） |
| F3 | 控制台引用计数 | 启动两个 opencode，关闭一个 | users 减 1，控制台继续运行；关闭第二个后**控制台周期清洗（≤60s）发现 users 空，自杀退出** |
| F4 | embed 接口兼容 | 用现有 embed_client.py 调 /embed | 返回正确向量，无报错 |
| F5 | 配置读取收口 | `grep -rn "open.*\.ai_env" .opencode/` | 只匹配 `control/backend/services/config_store.py` + `control/backend/server.py` 的 `is_dev_mode` 函数（启动期一次性读，例外允许） |
| F6 | 配置 CRUD | `curl /api/config`、`PUT /api/config` | 读写正确，.ai_env 实际更新 |
| F7 | 必要配置 banner | 删除 .ai_env 里 DEEPSEEK_API_KEY | 控制台首页顶部红色 banner 显示 |
| F8 | 全量扫描 | `curl /api/scan` | 返回所有 agent + 全局资源状态 |
| F9 | agent 缺工具告知 | 切到 mobile-analysis（缺 apktool）发消息 | 对话框 abort + 控制台地址 + `?agent=mobile-analysis` |
| F10 | 一键 pip 安装 | 控制台点"安装 frida" | 实际装上，状态变绿 |
| F11 | Docker 容器启停 | 控制台启停 neo4j-events | 容器状态正确切换 |
| F12 | Docker 镜像拉取 | 控制台点"拉取 neo4j:5" | SSE 进度推送，完成后镜像就绪 |
| F13 | 前端 dev 模式 | 设 CONTROL_FRONTEND_DEV=1 | 9776 返回 dev 提示，5173 可用 |
| F14 | 前端 release 模式 | bun run build + 设 CONTROL_FRONTEND_DEV=0 | 9776 返回 dist/index.html |
| F15 | 硬件信息显示 | 访问控制台首页 | 显示 CPU/内存/GPU 规格 |
| F16 | B 方案启动 | 控制台刚启动时 | uvicorn 立即监听，/health 返回 503 直到模型加载完 |

### 4.2 回归验收

| # | 验收项 | 验证方法 | 通过标准 |
|---|-------|---------|---------|
| R1 | events MCP 启动 | opencode 启动后 events MCP 注册成功 | 不报错，能调 graphiti |
| R2 | events MCP 调 embed | 触发 graphiti ingest | /embed 调通，事件入库 |
| R3 | knowledge MCP 启动 | opencode 启动后 knowledge MCP 注册成功 | 不报错，能调向量搜索 |
| R4 | binary-analysis agent 工作 | 跑一个 binary-analysis 会话 | 能调 idat（环境变量有 IDA_PRO_HOME） |
| R5 | install.sh 仍可用 | 全新机器跑 install.sh | 创建 venv + 装 pip 包正常 |
| R6 | detect_env.py check-preinstall | `python detect_env.py check-preinstall binary-analysis` | 只检测第二层，不查工具，不读 .ai_env |
| R7 | 现有 agent 仍能工作 | 跑各 agent 的典型场景 | 无回归（除工具检测迁移到控制台） |

### 4.3 架构验收

| # | 验收项 | grep 命令 | 通过标准 |
|---|-------|----------|---------|
| A1 | 配置读取收口 | `grep -rn "open.*\.ai_env" .opencode/` | 只匹配 `config_store.py` + `server.py` 的 `is_dev_mode` 函数（例外允许） |
| A2 | 端口读取收口 | `grep -rn "socket.bind\|bind_available_port" .opencode/` | 只匹配 `port_manager.py` |
| A3 | 文件锁收口 | `grep -rn "portalocker\|fcntl.flock\|msvcrt.locking" .opencode/` | 只匹配 `process_lock.py` |
| A4 | 工具检测迁移 | `grep -rn "EXTERNAL_TOOLS" .opencode/binary-analysis/scripts/detect_env.py` | 无匹配 |
| A5 | embed_server 删除 | `ls .opencode/mcp-servers/embed_server.py` | 不存在 |
| A6 | 端口文件改名 | `grep -rn "embed_server_port" .opencode/` | 无匹配 |
| A7 | 环境变量传递 | `grep -rn "EMBED_SERVER_PORT" .opencode/` | 无匹配（统一为 OPENCODE_CONTROL_PORT） |

### 4.4 跨平台验收

| # | 平台 | 验证项 |
|---|------|-------|
| C1 | macOS（开发机） | 完整跑通所有功能 |
| C2 | Linux | portalocker 跨平台锁（底层 fcntl）、PID 检测、spawn detached、Docker 操作 |
| C3 | Windows | portalocker 跨平台锁（底层 msvcrt）、PID 检测、PowerShell 启动时间、Docker Desktop |

**Windows 验证备注**：开发者无 Windows 环境时，C3 仅做代码审查（确认 portalocker 跨平台抽象正确）+ 单元测试覆盖。审计阶段必须明确标注 Windows 未实测。

---

## §5 与现有需求文档的关系

### 取代的文档

| 文档 | 关系 |
|------|------|
| `2026-07-26-embed-server-startup.md` | **取代**：控制台替代 embed_server，本需求的步骤 1-3 覆盖该文档全部目标（端口动态分配、/health 反映模型状态、同步等待就绪、统一启动管理） |
| `2026-07-26-embed-server.md` | **取代**：embed_server 融合到控制台，全部功能迁移 |

### 关联的文档（不取代，但有交集）

| 文档 | 关系 |
|------|------|
| `2026-07-23-env-check-optimization.md` | **关联**：环境检测并行预热逻辑保留，但工具检测迁移到控制台 |
| `2026-07-15-detect-env-subcommand-refactor.md` | **关联**：detect_env.py 子命令保留 install/check-preinstall，但 check-preinstall 范围收窄到第二层 |
| `2026-07-19-mcp-infra-separation.md` | **关联**：MCP 基础设施分离原则延续，控制台接管 embed_server 后 MCP 不再各自管理 |
| `2026-06-28-conda-venv-migration.md` | **关联**：venv 路径 `~/bw-security-analysis/.venv` 沿用，控制台也跑在此 venv |

### 不影响的文档

所有 agent 相关文档（binary-analysis、mobile-analysis、web-analysis、ai-security-analysis、crypto-analysis）的 agent prompt 不变，本需求只改环境检测和服务管理层。




