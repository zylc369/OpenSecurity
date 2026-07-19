# 进度：2026-07-19-events-mcp-lazy-loading

## Phase 5+6 执行进度

| 步骤 | 状态 | 完成时间 | 改动要点 |
|------|------|---------|---------|
| 1. 基线测量 | ✅ 完成 | 2026-07-19 | 实测握手 0.59s / 首次 14.57s / 第二次 0.02s |
| 2. server.py 顶层重构 + lifespan | ✅ 完成 | 2026-07-19 | _state/_ready/_init_error/_loop/_load_future/_indices_lock 全局；_preload_models_blocking（只加载 BGE-M3，不加载 reranker）；lifespan fire-and-forget；_ensure_ready 用 Lock 保护 build_indices |
| 3. 8 个工具引用方式调整 | ✅ 完成 | 2026-07-19 | _graphiti → _state["graphiti"]，grep 无残留 |
| 4. 端到端验证握手耗时 | ✅ 完成 | 2026-07-19 | 实测首次 14.31s（接近基线 14.57s） |
| 5. 单元测试 | ✅ 完成 | 2026-07-19 | 4 层全通过：L1 契约、L2 用户场景、L3 race、L4 加载失败 |
| 6. OpenCode 集成测试 | ✅ 完成 | 2026-07-19 | events + knowledge 都 connected；LLM 实际调用工具成功 |

## 测试覆盖度（12 个单元测试 + OpenCode 集成，全通过）

| Layer | 测试项 | 状态 | 关键数据 |
|-------|--------|------|---------|
| 1 | 握手快 | ✅ | 0.59s |
| 1 | 首次调用等待模型 | ✅ | 15.14s + 成功返回 |
| 1 | 第二次调用立即返回 | ✅ | 0.024s（加速比 649x） |
| 2 | **用户思考 15s 后调用** | ✅ | **0.191s**（方案 B 核心价值） |
| 3 | 并发首次调用共享 _ready | ✅ | 14.85s（<25s 阈值） |
| 4 | 加载失败不 hang | ✅ | 0.01s 返回错误 |
| 5 | 7 个工具烟雾测试 | ✅ | 全部返回合法 JSON |
| 6 | reranker @property 延迟加载 | ✅ | 首次 12.07s / 第二次 0.000s |
| 6 | diverse_results_search 可调用 | ✅ | 不抛错 |
| 7 | delete_session_events 完整流程 | ✅ | 写入 → delete → 返回正确 |
| 8 | build_indices 失败 → _empty_result | ✅ | 0.01s 返回错误 |
| 9 | graphiti.search_ 失败 → _empty_result | ✅ | 0.35s 返回错误 |

总耗时 206s（3 分 26 秒）。

## 最终覆盖率

- 工具函数覆盖：8/8 = **100%**
- 代码行覆盖：**~85%**（核心逻辑 + 全工具 + 失败路径）
- 场景覆盖：12 个独立场景 + OpenCode 集成

## 方案 B 的核心价值（Layer 2 验证）

```
启动 server → 握手 0.59s（fire-and-forget 后台加载 BGE-M3）→ 用户思考 15s →
调用工具 → 后台加载已完成 → 立即返回（0.191s）
```

vs 改造前：
```
启动 server → 握手 0.59s（什么都不做）→ 用户思考 15s →
调用工具 → 首次触发 BGE-M3 加载（14s）→ 漫长等待
```

**核心收益**：利用用户启动后的时间差吸收 BGE-M3 加载，用户实际感知的首次响应从 ~14s 降到 ~0.2s。

## 关键约束

- _preload_models_blocking **不预加载 reranker**（仅 diverse_results_search 用，避免无谓加载）
- build_indices_and_constraints 仍在 asyncio loop 内（async 函数）
- _indices_lock 保护 build_indices 并发执行
- 跨线程唤醒用 loop.call_soon_threadsafe(_ready.set)
