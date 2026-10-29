# 需求：knowledge/events MCP 按 ocr 标杆终态收口（已实施完成，见 progress 整改 34）

## §1 背景与目标

**来源**: 整改 33 只收口了写路径（plugin→控制台），读路径（agent 搜索）仍在胖 MCP server 里；
用户裁定按 ocr/server.py 标杆完成终态收口。

**痛点**（四处不对劲）:
1. 依赖方向倒挂：控制台 sys.path.append 伸手进 mcp-servers 借库
2. Docker 双头管理：docker_manager 自称唯一入口，events/server.py 另有一套 daemon/容器拉起
3. Graphiti 双实例：events MCP（读）+ 控制台 event_writer（写）各持一套 Neo4j driver/LLM/embedder
4. MemoryDB 双连接：knowledge MCP 与 memory_writer 各开一条 SQLite 连接

**目标**: 业务库全部进 `control/backend/services/`；读写共用单实例；MCP server 变纯 HTTP 薄壳
（工具签名/返回结构零变化，agent 无感）；删 6 个文件 + embed_client.py 回环。

## §2 技术方案

### 移动清单（git mv 语义）

| 源 | 目标 | 适配 |
|---|---|---|
| knowledge/db.py | services/knowledge_db.py | embedder 类型 Protocol 化 |
| knowledge/anonymizer.py | services/anonymizer.py | 原样 |
| events/graphiti_config.py | services/graphiti_config.py | .ai_env 路径 parents 修正；embed/rerank 直连 model_loader |
| events/llm_client.py | services/llm_client.py | 原样（无路径依赖） |
| events/reranker.py | services/reranker.py | rank() 直连 model_loader.get_reranker() |

### 关键设计

1. **单实例跨循环共享（events）**：event_store.py（event_writer 改名扩展）持专用线程+事件循环+唯一
   Graphiti；FastAPI 协程经 `asyncio.run_coroutine_threadsafe` + `wrap_future` 桥接进专用循环执行
   search_/add_episode（neo4j driver 绑定创建时的循环）。
2. **惰性基础设施**：首次使用（写或读）时在专用线程内 ensure Docker daemon → ensure 容器 →
   create_graphiti → build_indices（阻塞调用在专用线程，不卡主循环）。daemon/容器拉起逻辑从
   events/server.py 收编进 docker_manager（Docker CLI 唯一入口恢复）；KnownContainer.volumes 补
   `$DATA_DIR/db/events:/data`（修复控制台手动启动容器无卷的隐性 bug），create_container 展开 $DATA_DIR。
3. **单 MemoryDB（knowledge）**：knowledge_store.py（memory_writer 改名扩展）惰性建
   MemoryDB(embedder=model_loader.get_embedder()——真 SentenceTransformer，同步 encode 直连，
   HTTP 回环全删)；plugin 写路径=队列线程（现有），agent 读写路径=同步方法（FastAPI 线程池执行，
   MemoryDB._lock 串行）。
4. **端点与返回结构**：
   - routes/knowledge.py: POST /api/knowledge/search、/api/knowledge/store（anonymize 后落库）、
     /api/memory/search、/api/memory/entry（原 ingest 迁入）
   - routes/events.py: POST /api/events/entry、/api/events/delete（原 ingest 迁入）、
     /api/events/time-search、/entity-relationships-search、/diverse-results-search、
     /episode-context-search、/entity-search（搜参构建+_format_results/_empty_result 进 event_store，
     返回 dict 与原工具 json.loads 后逐字段一致）
   - 删 routes/ingest.py
5. **薄壳**（对齐 ocr/server.py）：工具签名/description 逐字保留，函数体=httpx POST 控制台 +
   失败自愈（清 base 缓存重解析端口）；控制台不可达返回与原降级一致的错误结构。
6. **删除**: 移动后的 5 个源文件 + mcp-servers/embed_client.py（消费方全部迁移后零引用）。
   control_url.py 保留（ocr/knowledge/events 三壳共用）。

## §3.1 实施步骤

1. 移库 knowledge_db.py + anonymizer.py（Protocol embedder）
   - 验证: compile + MemoryDB 用 model_loader.get_embedder() 建库落一行
2. 移库 graphiti_config.py / llm_client.py / reranker.py（路径/直连适配）
   - 验证: compile + create_graphiti() 返回实例（Docker 已运行态）
3. docker_manager 收编 daemon/容器 ensure + volumes 修复
   - 验证: compile + ensure_neo4j_events_blocking() 幂等通过（容器已运行）
4. knowledge_store.py（吸收 memory_writer，+3 同步方法）；删 memory_writer.py
   - 验证: compile + fake embedder 下 search_knowledge/store_knowledge/search_memory 三方法返回结构正确 + 队列写路径回归
5. event_store.py（吸收 event_writer，+5 search + 跨循环桥 + docker ensure + 格式化）；删 event_writer.py
   - 验证: compile + fake graphiti 下 5 个 search 返回结构正确（含 min_mentions 后过滤）+ 写路径回归
6. routes/knowledge.py + routes/events.py；删 routes/ingest.py；server.py 注册
   - 验证: compile + TestClient 三类端点返回结构正确
7. knowledge/server.py 薄壳重写（3 工具签名逐字保留）
   - 验证: compile + 真机 stdio 调用三工具
8. events/server.py 薄壳重写（6 工具签名逐字保留）
   - 验证: compile + 真机 stdio 调用（time_search/delete）
9. 删除旧文件 + embed_client.py + 全仓引用清零（含注释）
   - 验证: grep embed_client/graphiti_config 等 mcp-servers 路径零引用
10. 测试更新（test_control 改名+新增）+ 全量回归
    - 验证: pytest 59±（全绿）+ test_integration 5/5
11. E2E: 生产重启 + MCP stdio 真调用（knowledge 3 + events 2）+ 文档收尾

## §4 验收标准

- 功能: 9 个 MCP 工具经薄壳可用且签名/返回结构不变；控制台端点直调等价；单实例（Graphiti×1、
  MemoryDB×1、Docker 管理入口×1）
- 回归: pytest 全绿；test_integration 全绿；plugin 三端点（memory/entry 等）不受迁移影响
- 架构: 依赖倒挂消除（services 内无 sys.path 伸进 mcp-servers）；embed_client 零引用删除；
  docker CLI 调用只在 docker_manager（grep 唯一性）

## §5 与现有文档关系

- 整改 33 的延续（写路径收口 → 读写全收口）；progress 文档追加整改 34
