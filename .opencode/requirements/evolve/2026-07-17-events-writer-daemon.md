# events writer daemon：常驻并发写入进程

## §1 背景与目标

### 来源痛点

当前 `fireAndForgetEvent`（security-analysis.ts）为每个事件（工具执行 / agent 回复）spawn 一个独立的 Python 进程写 Graphiti。每进程：

| 步骤 | 耗时 | 问题 |
|---|---|---|
| Python 解释器启动 | ~200ms | 6 事件/轮 = 1.2s 纯浪费 |
| import + create_graphiti + 连 Neo4j | ~1s | 无连接复用 |
| build_indices_and_constraints() | ~1s | 幂等操作每次都跑 |
| add_episode() | 5-30s | ZhipuAI LLM 实体提取（必要开销） |
| graphiti.close() | ~200ms | 连接断开 |

一轮对话 6 事件 = **~14.4s 纯开销**（不含 add_episode 本身）。

额外问题：事件乱序（fire-and-forget 完成顺序不确定）、ZhipuAI 无并发控制（可能限流）。

### 预期收益

| 维度 | 改进前 | 改进后 | 提升 |
|---|---|---|---|
| 进程启动 | 6 次/轮 | 1 次（daemon 常驻） | -83% |
| Graphiti 连接 | 6 次建/断 | 1 次建，常驻 | -83% |
| build_indices | 6 次 | 1 次（daemon 启动时） | -83% |
| 事件时序 | 不保证 | timestamp 保证（reference_time） | 100% 正确 |
| API 并发 | 无限制 | Semaphore(5) 限制 | 防限流 |

## §2 技术方案

### 2.1 架构

```
plugin (TypeScript)                        daemon (Python asyncio)
  │                                          │
  │  ensureWriterDaemon()                    │  create_graphiti()（一次）
  │  ↓ 首次调用时 spawn                      │  build_indices()（一次）
  │                                          │
  │  fireAndForgetEvent()                    │  stdin_reader（executor 线程）
  │  ↓ JSON + "\n" → daemon stdin            │  ↓ readline → asyncio.Queue（无界）
  │                                          │
  │  process.on("exit") → SIGTERM            │  5 个 worker（Semaphore(5)）
  │                                          │  ↓ 每个从 queue 取事件
  │                                          │  ↓ graphiti.add_episode(reference_time=ts)
  │                                          │  ↓ ZhipuAI API + BGE-M3 + Neo4j
  │                                          │
  │  stdin EOF → daemon 排空队列 → 退出       │
```

### 2.2 daemon 脚本：`write_event_daemon.py`

职责：
- 启动时创建 Graphiti 实例 + `build_indices_and_constraints()`（各一次）。连接失败 → 立即退出（exit 1），plugin 下次调用时重试
- `sys.path.insert(0, str(Path(__file__).parent))` 确保 graphiti_config 可 import
- 从 stdin 按行读取 JSON（含 name, body, source, group_id, timestamp），用 `loop.run_in_executor(None, sys.stdin.readline)` 保证跨平台
- `asyncio.Queue` 无界缓冲
- 5 个 `asyncio.Task` worker，`asyncio.Semaphore(5)` 限制 ZhipuAI 并发
- 每个 worker 调 `graphiti.add_episode(reference_time=datetime.fromtimestamp(ts/1000))`
- **单事件失败不影响其他事件**：worker catch 异常 → stderr 日志 → 继续 queue.get()
- 所有日志走 stderr（不污染 stdout）
- stdin EOF → `queue.join()` 等待排空 → `graphiti.close()` → 退出
- 收到 SIGTERM → 取消所有 worker → `graphiti.close()` → 退出

### 2.3 plugin 改动：`fireAndForgetEvent`

- 新增 `writerDaemon: ChildProcess | null` 模块级变量
- 新增 `ensureWriterDaemon()`：懒启动 daemon，失败只记日志。`stdio: ["pipe", "pipe", "pipe"]`（捕获 stderr 供排查）
- `fireAndForgetEvent()` 改为：写 line-delimited JSON 到 daemon stdin（含 `Date.now()` 时间戳）。stdin.write 返回 false（背压）→ 记日志丢弃事件（fire-and-forget 语义）
- daemon stderr → debugLog 转发（实时管道）
- daemon exit/close 事件 → `writerDaemon = null`（下次调用自动重启）
- `process.on("exit")` → daemon.kill("SIGTERM")

### 2.4 IPC 协议

stdin 管道，每行一个 JSON：

```json
{"name": "frida hook execution", "body": "...", "source": "binary-analysis tool execution", "group_id": "session-xxx", "timestamp": 1721234567890}
```

`timestamp` 由 plugin 传入（`Date.now()`），daemon 传给 `graphiti.add_episode(reference_time=...)`。保证时序与写入完成顺序无关。

### 2.5 文件变更

| 文件 | 操作 | 说明 |
|---|---|---|
| `mcp-servers/events/write_event_daemon.py` | **新建** | 常驻 daemon 脚本 |
| `mcp-servers/events/write_event.py` | **删除** | 被 daemon 替代 |
| `plugins/security-analysis.ts` | **修改** | fireAndForgetEvent 改为 daemon stdin 写入 |

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 新建 `write_event_daemon.py`**
- 文件: `mcp-servers/events/write_event_daemon.py`
- 预估行数: ~90 行
- 内容: asyncio 事件循环 + stdin_reader + 5 worker + Semaphore + 信号处理
- 验证点: `python write_event_daemon.py` 启动 → stdin 写入 JSON → stderr 看到 "episode added" → stdin EOF → 进程退出
- 依赖: 无

**步骤 2. 修改 `fireAndForgetEvent`**
- 文件: `plugins/security-analysis.ts`
- 预估行数: ~40 行（新增 ensureWriterDaemon + 改写 fireAndForgetEvent + process.on exit）
- 验证点: bun bundle 成功；grep 确认不再 spawn write_event.py
- 依赖: 步骤 1

**步骤 3. 删除 `write_event.py` + 清理引用**
- 文件: 删除 `write_event.py`；检查 `detect_env.py` / `security-analysis.ts` 是否有路径引用
- 预估行数: ~5 行
- 验证点: grep 确认无 `write_event.py` 引用（write_event_daemon.py 除外）
- 依赖: 步骤 2

## §4 验收标准

### 功能验收

| 验收项 | 验证方式 |
|---|---|
| daemon 启动后 Graphiti 连接复用 | 日志显示 create_graphiti 只出现一次 |
| build_indices 只执行一次 | 日志显示 build_indices 只出现一次 |
| 5 个 worker 并发 | 同时提交 10 个事件，ZhipuAI 最多 5 个并发 |
| 超过 5 个排队 | 第 6-10 个事件等待 worker 空闲后执行 |
| timestamp 保证时序 | 事件 A 先于 B 提交但 B 先完成 → 搜索结果仍按 A 在前 |
| stdin EOF → 优雅退出 | 队列排空后 daemon 自动退出 |
| SIGTERM → 立即退出 | daemon 收到 SIGTERM 后取消 worker 并退出 |
| daemon 崩溃后自动重启 | kill daemon → 下一个事件触发 ensureWriterDaemon 重启 |
| ZHIPU_API_KEY 未配置 → daemon 不启动 | ensureWriterDaemon 检测后跳过 |
| Docker 没跑 → daemon 不启动 | graphiti 连接失败 → daemon 退出 → 事件丢弃 |

### 回归验收

| 验收项 | 验证方式 |
|---|---|
| events MCP server 不受影响 | server.py 仍正常工作（独立进程） |
| fireAndForgetEvent 不阻塞主流程 | stdin.write 是非阻塞的 |
| 搜索功能不受影响 | events MCP server 搜索结果正确 |

### 架构验收

| 验收项 | 验证方式 |
|---|---|
| 无孤儿进程 | opencode 退出 → daemon 退出（stdin EOF 或 SIGTERM） |
| 依赖方向正确 | daemon → graphiti_config.py → graphiti_core（单向） |

## §5 与现有需求文档的关系

- `2026-07-15-detect-env-subcommand-refactor.md` — detect_env 重构，无冲突
- `2026-07-14-events-mcp-implementation.md` — events MCP 实施文档，本文档是其写入路径的优化
