# 进度：2026-07-19-mcp-infra-separation

## Phase 5+6 执行进度

| 步骤 | 状态 | 完成时间 | 改动要点 |
|------|------|---------|---------|
| 1. pyproject.toml 加 [tool.opensecurity] | ✅ 完成 | 2026-07-20 | events: import_names + requires_docker=neo4j-events；knowledge: import_names only |
| 2. detect_env.py 加新函数 | ✅ 完成 | 2026-07-20 | _load_mcp_metadata + _check_docker_binary_and_daemon + _check_container_status + _check_mcp_deps_fast + _ensure_mcp_infra |
| 3. _check_preinstall 改调 _check_mcp_deps_fast | ✅ 完成 | 2026-07-20 | 实测 3.9s（<5s，原 8s timeout 杀进程） |
| 4. _run_install 改调 _ensure_mcp_infra，删 _detect_mcp_deps | ✅ 完成 | 2026-07-20 | 删除 115 行旧函数 |
| 5. events/server.py 加 Docker 启动 + 改 lifespan | ✅ 完成 | 2026-07-20 | _ensure_docker_daemon_blocking + _ensure_neo4j_container_blocking + _pull_image_with_progress + 改 _preload_models_blocking 三步序列 |
| 6. mcp-manager.ts 删除 requiredPackages + checkPackages | ✅ 完成 | 2026-07-20 | 删除 25 行，节省 2-4s 启动时间 |
| 7. 单元测试 | ✅ 完成 | 2026-07-20 | 5 测试全通过：docker helpers + lifespan 完整序列 + 用户场景 |
| 8. OpenCode 集成测试 | ✅ 完成 | 2026-07-20 | events/knowledge 都 connected；LLM 真实调用 recent_context_search 返回结果 |
| 9. check-preinstall 不再 ETIMEDOUT | ✅ 完成 | 2026-07-20 | 实测 3.9s，日志无"正在启动 Docker" |

## 测试覆盖度（5 单元 + 2 集成，全通过）

| Layer | 测试项 | 状态 | 关键数据 |
|-------|--------|------|---------|
| 1 | _ensure_docker_daemon_blocking 已运行时 | ✅ | 0.09s |
| 1 | _ensure_neo4j_container_blocking 已运行时 | ✅ | 0.02s |
| 2 | lifespan 完整序列 首次调用 | ✅ | 15.54s（成功返回） |
| 2 | 并发 2 个调用 | ✅ | 16.61s（共享 _ready） |
| 3 | 用户思考 20s 后调用 | ✅ | 0.216s（<2s） |
| 集成 | opencode serve events MCP connected | ✅ | all 3 connected |
| 集成 | LLM 调用 mcp__events__recent_context_search | ✅ | 返回正确结果 |
| 集成 | check-preinstall 不再启动 Docker | ✅ | 3.9s，无"正在启动 Docker"日志 |

## 关键改造收益

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| check-preinstall 耗时 | 8s+ timeout 杀进程 | 3.9s（<5s） |
| Docker 容器可靠性 | 经常没启动（进程被杀） | lifespan 完整执行 |
| 依赖声明 | 3 处重复 | pyproject.toml 单一事实源 |
| mcp-manager.ts 启动时间 | 2-4s（checkPackages） | 0s（直接注册） |
| 用户首次响应（思考后） | 14.57s（BGE-M3 加载） | 0.216s（已后台加载） |
