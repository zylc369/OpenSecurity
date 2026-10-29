# 需求：plugin fire-and-forget 写入收口到控制台服务端（已实施完成，见 progress 整改 33）

## §1 背景与目标

**来源**: 用户指出的遗留尾巴——`security-analysis.ts` 的 `fireAndForgetEvent`/`fireAndForgetMemory`/`deleteGraphitiEvents` 通过 spawn python daemon 子进程（stdin 管道协议）写入事件库/knowledge 库，本应集成到控制台服务端。

**痛点**:
- plugin 侧 ~250 行 daemon 进程管理代码（spawn/READY 信号/暂存 50 条/背压/EOF 排空）
- daemon 的核心依赖（embed/rerank）本来就回环调控制台 `/embed` `/rerank`——模型能力早已收口，daemon 只是个持有 Neo4j/SQLite 连接的外壳
- 三个进程（opencode + 2 daemon）写两条数据通路，进程页看不见 daemon

**目标**:
- plugin 通过 HTTP POST 调控制台（fire-and-forget，失败仅 debugLog）
- 控制台内常驻两个写入器（后台线程 + 内存队列），端点入队即返 202
- 删除两个 daemon 脚本与 plugin 侧 daemon 管理代码

## §2 技术方案

### 数据通路（改造后）

```
plugin ──fetch POST──▶ 控制台 /api/memory/entry | /api/events/entry | /api/events/delete
                          │ 入队即返 202
                          ▼
                    services/memory_writer.py（线程 + queue + MemoryDB → SQLite）
                    services/event_writer.py（线程 + 独立事件循环 + Graphiti → Neo4j）
                          └─ embed/rerank 经 HttpEmbedClient 回环 /embed /rerank（单一源零改动）
```

### 端点设计（消息体 = 原 stdin line JSON 逐字段一致）

| 端点 | 请求体 | 响应 |
|---|---|---|
| POST /api/memory/entry | `{question, answer, type, flow_id}` | 202 `{queued: true}` |
| POST /api/events/entry | `{name, body, source, group_id, timestamp}` | 202 |
| POST /api/events/delete | `{group_id}` | 202 |

### services/memory_writer.py

- `MemoryWriterService`（类，规则 9 OOP）：
  - `start()`（lifespan 调用）：启动 worker 线程（daemon=True）
  - `submit(entry: MemoryEntry)`：queue.put，字段校验（question/answer/type 非空，与原 daemon 逻辑一致，非法跳过+日志）
  - worker 循环：取条目 → `MemoryDB.store(question=f"[{type}] {question}", content=answer, doc_type="memory", flow_id=...)` → 异常仅日志不退出
  - DB 路径：`config.DATA_DIR / "db/knowledge/knowledge.db"`（与 knowledge/server.py 同库；测试经 DATA_DIR env 指 tmp）
  - embedder：`HttpEmbedClient`（回环 /embed）
  - 关闭：`stop()` 置位 + queue.join（SIGTERM 时 lifespan 调用）
  - 可注入：`MemoryWriterService(db_path=..., embedder=...)`（测试注入 fake）

### services/event_writer.py

- `EventWriterService`（类）：
  - `start()`：启动专用线程；线程内跑独立事件循环（graphiti 的 async neo4j driver 绑定创建时的循环；HttpEmbedClient 同步调用阻塞的是该专用循环，不卡 FastAPI 主循环）
  - 循环内惰性初始化：首次取到条目时 `create_graphiti()` + `build_indices_and_constraints()`（失败 → 日志 + 条目丢弃 + 置未初始化态，下一条重试）
  - worker：`add_episode(name, episode_body, source_description, reference_time, source=EpisodeType.message, group_id, entity_types=CUSTOM_ENTITY_TYPES)`；`delete` → `EntityNode/EpisodicNode.delete_by_group_id`
  - 并发：循环内 `Semaphore(10)`（原 daemon MAX_CONCURRENT=10）+ 无界 queue.Queue
  - 可注入 graphiti 工厂（测试 fake）
- 两服务共用 sys.path 注入：`mcp-servers/`、`mcp-servers/knowledge/`、`mcp-servers/events/`（graphiti_config/db/embed_client import）

### plugin 改造（security-analysis.ts）

- 删：`ensureWriterDaemon`/`ensureMemoryDaemon`/`writerDaemon`/`memoryDaemon`/`daemonReady`/`memoryDaemonReady`/`pendingEvents` 及 READY/背压/暂存逻辑
- 新增 `postToControl(path, body)`：`readControlPortFile()`（control-manager.ts 已有）→ `fetch POST`（不 await，`.catch` 全部，失败 debugLog 跳过——语义同 daemon 不可用）
- `fireAndForgetEvent`/`fireAndForgetMemory`/`deleteGraphitiEvents` 改为调 `postToControl`

### 删除清单

- `mcp-servers/events/write_event_daemon.py`
- `mcp-servers/knowledge/memory_writer_daemon.py`
- `db.py` 头注释中 memory_writer_daemon 字样改为控制台端点

## §3 实现规范

- 规则 9：两服务为类（dataclass 条目 + 类型注解），禁止裸 dict 穿透
- 规则 10：plugin 新路径打日志（每跳过分支、每次 fetch 失败）
- 线程 daemon=True（控制台退出不等待）；stop() 仅用于测试优雅收尾
- 事件队列残余在控制台重启时丢弃（fire-and-forget 语义，与 daemon 模式下 opencode 崩溃等价）——文档说明

## §3.1 实施步骤

1. services/memory_writer.py（MemoryEntry dataclass + MemoryWriterService）
   - 文件: 新增 control/backend/services/memory_writer.py
   - 预估行数: ~110
   - 验证点: `python -c compile` + 临时脚本 fake embedder 注入，submit 2 条（1 合法 1 非法），SQLite 查 1 行、日志 1 条跳过
2. services/event_writer.py（EventEntry dataclass + EventWriterService）
   - 文件: 新增 control/backend/services/event_writer.py
   - 预估行数: ~140
   - 验证点: compile + fake graphiti 工厂注入，entry/delete 两类消息路由正确、add_episode 参数完整
3. routes/ingest.py 三端点 + server.py include_router + lifespan start
   - 文件: 新增 routes/ingest.py；改 server.py
   - 预估行数: ~70
   - 验证点: TestClient POST 三端点 202；tmp DATA_DIR 下 SQLite 落库（真 HttpEmbedClient 不可用 → fake 注入）
4. backend 测试 3 例（fake 注入）
   - 文件: tests/test_control.py 追加
   - 预估行数: ~90
   - 验证点: pytest 全绿（56+3）
5. plugin 改造：删 daemon 代码 + postToControl + 三函数改写
   - 文件: plugins/security-analysis.ts
   - 预估行数: 删 ~260 / 增 ~70
   - 验证点: `node --check`；grep 零 daemon 残留；bun 环境加载 plugin 冒烟（若有现成方式）
6. 删除 daemon 脚本 + db.py 注释更新 + 全仓 grep 零残留
   - 文件: 删 2 个 .py；改 db.py 注释
   - 验证点: grep write_event_daemon/memory_writer_daemon 全仓零命中
7. E2E 生产验证 + 需求文档归档 + progress.md
   - 验证点: 重启控制台（按钮）→ plugin 新代码生效 → 触发一轮真实工具调用 → sqlite3 查 knowledge.db 新行；events 依赖 Neo4j/Docker + DeepSeek，环境在则真验，不在则记录 fake 级已验

## §4 验收标准

- 功能: 三端点 202 入队；memory 真实落库 SQLite；events 正确路由 add/delete；plugin 侧三函数语义不变（fire-and-forget、失败不阻塞、白名单保留）
- 回归: pytest 59 例全绿；tsc 无关（本次无前端改动）；embed/rerank 端点不受影响
- 架构: daemon 脚本与 plugin daemon 管理代码零残留；graphiti_config/MemoryDB/embed_client 零改动（单一源）

## §5 与现有需求文档的关系

- progress-2026-08-16-deps-ocr.md 整改系列的延续（控制台能力收口第 N 步：embed→模型→OCR→进程页→重启→本轮写入通路）
