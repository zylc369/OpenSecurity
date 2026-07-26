# 进度：embed_server 启动管理改造

## 步骤完成状态

| 步骤 | 内容 | 状态 |
|------|------|------|
| 1 | embed_server.py 改造（动态端口 + /health 503） | ✅ 完成 |
| 2 | embed_client.py 改造（删降级 + 动态端口 + 分层超时） | ✅ 完成 |
| 3 | events/server.py 改造（删降级 + _wait_embed_server_ready） | ✅ 完成 |
| 4 | 新建 ServiceRegistry | ✅ 完成 |
| 5 | ctx 集成 ServiceRegistry | ✅ 完成 |
| 6 | security-analysis.ts 改造（统一等待 + 启动状态管理） | ✅ 完成 |
| 7 | 端到端验证 | ✅ 完成 |

## 改动要点

### embed_server.py
- `bind_available_port()` 预绑定 socket，`sock.detach()` 传 fd 给 uvicorn
- `$DATA_DIR/.embed_server_port` 写端口+PID
- `_models_ready` 追踪 embedder 加载状态，/health 加载中返回 503
- DATA_DIR 从环境变量读取

### embed_client.py
- 删除全部降级逻辑（_fallback_encode/_fallback_predict/_confirmed_available）
- `_read_port()` 动态读端口（环境变量 > 端口文件 > 默认）
- `base_url` @property 延迟构建
- 分层超时：首次 60s，后续 10s
- 失败抛 RuntimeError

### events/server.py
- 删除降级健康检查 + "回退到本地加载"打印
- 新增 `_wait_embed_server_ready()` /health 轮询等待（最多 60s）
- 不可用时 `_init_error.append(RuntimeError(...))`

### service-registry.ts（新增）
- ServiceStatus 接口 + ServiceRegistry 类
- waitFor 先检查 status 非 pending 避免 resolve-before-wait 死锁

### context.ts
- ctx.services 字段 + init 中初始化

### security-analysis.ts
- 模块级 `let embedProc` + `EMBED_PORT_FILE` 常量
- `startEmbedServer()` 函数：register → spawn(传 DATA_DIR) → poll health → resolve
- `pollEmbedServerHealth()` 函数：等端口文件 + /health 轮询
- chat.message 中 `await ctx.services.waitFor("embed_server")` 统一等待
- `process.on("exit")` kill embed_server
