# 进度：推理串行化收口——LockedEmbedder/LockedReranker 包装（方案A）

> 需求文档：2026-09-25-locked-embedder-serialization.md
> 状态：**已完成**（全部 6 步 + 审计通过）
> 日期：2026-09-25

## 步骤完成记录

| 步骤 | 内容 | 状态 | 验证结果 |
|---|---|---|---|
| 1 | model_loader.py：LockedEmbedder/LockedReranker、get_* 返回包装、内部函数收口（删 `_do_embed`/`_do_rerank`/`infer_lock()`，async 委托 sync） | ✅ | py_compile OK；D 痕迹零残留；锁获取点=2；get_* 返回类型为包装 |
| 2 | knowledge_db.py：`_embed` 去 D 锁、新增 `_embed_batch`、`search` 批量化、Protocol 文档 | ✅ | py_compile OK；`test_knowledge_store_paths` + `test_knowledge_events_routes`（fake 注入）通过 |
| 3 | graphiti_config.py + reranker.py：删两个 `.model` 死出口 property、`_encode_locked`→`_encode`、过时 docstring 修正 | ✅ | py_compile ×2；property 定义清零；全后端无 `.model` 消费（llm_client 的 `self.model` 为 LLM 模型名字符串，无关） |
| 4 | knowledge_store.py 头部并发模型文档更新（model_loader 头部已在步骤1重写） | ✅ | 人工审读一致 |
| 5 | 新增回归测试 `test_locked_wrapper_mutex`（4 线程并发 probe 断言 peak==1） | ✅ | 测试通过（encode 与 predict 双路径互斥实证） |
| 5a | 补充 `test_model_loader_architecture_guard`（静态架构守护：sentence_transformers 仅限 model_loader import、_infer_lock 获取点==2、已删符号零引用、.model 死出口禁止复活） | ✅ | 测试通过；四断言全绿 |
| 5b | 补充 `test_real_model_concurrency_smoke`（ENV 开关 `OPENSECURITY_E2E_SMOKE=1`，默认跳过）：真模型三路并发 embed×memory×graphiti-embedder，**零污染设计**（embed 直调纯计算 / MemoryDB 临时库 finally 删 / BgeM3Embedder.create 不落图） | ✅ | 实跑通过：17.7s（热缓存），三路×6 并发零异常；零残留复核（生产 memory 库/Neo4j 均无 smoke 与 load-test 数据） |
| 5c | 清理历史压测污染：生产 memory 库 6 条 `[load-test]`（ids 5749-5754，含 answer_vectors 联动删除）+ graphiti 6 个 load-test-exec episodes（DETACH DELETE，实体节点保留防误删合并实体） | ✅ | 复核零残留 |
| 6 | 端到端：优雅停旧控制台（SIGTERM）→ 同参重启（pid 8757）→ 压测 | ✅ | 详见下 |

## 端到端验证记录

- 重启：旧 72626 优雅关停（"收到信号 15，退出"），新 pid 8757，health 200
- 心跳：plugin 重注册（14:28:46「新 opencode 注册 pid=34047」），持续 200
- 模型：BAAI/bge-m3 加载于 mps 设备（`No device provided, using mps`）
- **并发压测**：12 路并发直连 IPC（6×`/api/events/entry` + 6×`/api/memory/entry`），全部 `{"queued":true}`
- **双管道并发处理零崩溃**：episode `load-test-exec` 入库多条（graphiti 持锁 embed）× memory 写入走 LockedEmbedder encode——正是 13:43/14:02 两次 SIGSEGV 的复现场景
- memory 检索回读：`/api/memory/search` count=5 命中压测写入（写入+检索双向验证）
- 无 store 失败、无新增 `.ips` 崩溃报告（止于 14:02 事故报告）

## 架构验收（grep 清单）

1. `_infer_lock` 模块外引用：零 ✅
2. `infer_lock`/`_do_embed`/`_do_rerank` 残留：零 ✅（model_loader 内部定义与获取属预期）
3. `.model` property 死出口：零 ✅
4. 锁获取点：恰 2 处（LockedEmbedder.encode + LockedReranker.predict）✅
5. agents/agents-rules 无残留引用：零 ✅

## 备注

- 发现（非缺陷）：plugin 的 events/memory 投递仅对 Security Agent 生效——进化 agent 的工具执行不投递事件。端到端压测因此改用 HTTP 直连 IPC 完成。
- 本次改动未提交 git，待用户审阅（`git diff .opencode/control/backend/`）。
