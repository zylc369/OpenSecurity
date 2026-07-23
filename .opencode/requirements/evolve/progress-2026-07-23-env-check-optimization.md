# 进度: 环境检测性能优化 + prompt 注入精简 + 去掉 env_cache.json

需求文档: `2026-07-23-env-check-optimization.md`

## 步骤完成状态

| 步骤 | 内容 | 状态 | 改动要点 |
|------|------|------|---------|
| 1 | venv.ts 新增 readAiEnv + getIdatPath + getCompilerName | ✓ 完成 | 3 个函数，惰性缓存模式，bun run 测试通过 |
| 2 | detect_env.py 删除 _save_cache + CACHE_FILE | ✓ 完成 | 删除 _save_cache 函数 + CACHE_FILE 常量 + 调用点，check-preinstall 仍正常输出 JSON |
| 3 | task-session-persistence.ts 删除 readEnvCache | ✓ 完成 | 删除 readEnvCache 方法 + ENV_CACHE_FILE import |
| 4 | constants.ts 删除 ENV_CACHE_FILE | ✓ 完成 | 删除 ENV_CACHE_FILE 定义，plugins/ 无残留 |
| 5 | security-analysis.ts buildEnvSection 精简 + shell.env 改造 | ✓ 完成 | 删 EnvData 接口 + packages/tools 注入，简化 IDA/编译器，shell.env 改用 getIdatPath，删 startup 日志 ENV_CACHE_FILE |
| 6 | security-analysis.ts 并行预热 + Promise cache + evolve 排除 | ✓ 完成 | envCheckPromises Map + preheatEnvCheck + chat.message 三分支 + setup 并行预热，删 checkEnvironment |
| 7 | 端到端验证 | ✓ 完成 | bun run 测试新函数 + bun build 完整构建 17 模块零错误 + env_cache.json 不再写入验证 |

## 关键验证结果

- `readAiEnv()` 正确读取 .ai_env → `{IDA_PRO_HOME: "...", DEEPSEEK_API_KEY: "..."}`
- `getIdatPath()` 返回 `/Applications/IDA Professional 9.1.app/Contents/MacOS/idat`
- `getCompilerName()` 返回 `clang`
- 缓存机制正常（第二次调用返回相同值）
- detect_env.py check-preinstall 仍输出完整 JSON，env_cache.json mtime 未变（不再写入）
- bun build 完整构建成功（17 模块，85.24 KB，零错误）
- 全局无 ENV_CACHE_FILE/readEnvCache/_save_cache/CACHE_FILE 残留

## Phase 6 审计后修复的 bug

**缓存变量初始值 bug**（用户质疑"测过吗"后发现）:
- `cachedIdatPath` 和 `cachedCompilerName` 初始值误写为 `null`（应为 `undefined`）
- 根因：`!== undefined` 检查下，null !== undefined → true，第一次调用就跳过计算返回 null
- 修复：改为 `string | null | undefined = undefined`
- 对比：getPythonCmd 用 truthy 检查（`if (cachedPythonCmd)`），null 不会误判；但 getIdatPath/getCompilerName 用 `!== undefined`，必须用 undefined 初始值
- 教训：缓存状态机必须区分"未计算"(undefined) 和"计算了但结果 null"(null)

**spawnSync 阻塞事件循环 bug**（用户重启 opencode 报"长时间黑屏"后发现）:
- 根因：runProcess（spawn.ts）Unix 路径用 `spawnSync`（同步阻塞）。虽然函数签名是 async，但 spawnSync 在返回 Promise 之前就同步阻塞了整个事件循环。并行预热 6 个检测时，6 次 spawnSync 串行阻塞 ~27 秒，导致 OpenCode 启动黑屏。
- JavaScript async/await 关键规则：async 函数在第一个 `await` 之前的代码是同步执行的。`.catch()` fire-and-forget 防不住 spawnSync 的同步阻塞——spawnSync 在 Promise 创建过程中就阻塞了。
- 修复：spawn.ts Unix 路径从 `spawnSync` 改为 `spawn`（异步）+ Promise 包装，手动处理 stdout/stderr stream + timeout
- 对比测试验证：26767ms（阻塞 27 秒）→ 5261ms（0 次阻塞），5.1x 加速
- 端到端验证：5787ms，事件循环探针 0 次阻塞，6×✓ 结果正确
- 影响范围：runProcess 是核心函数，所有调用方受益（并行预热 + ensureWriterDaemon + ensureMemoryDaemon + 其他 spawn 场景）
- 教训：async 函数内部的同步操作（spawnSync/execFileSync/readFileSync）会阻塞事件循环。"异步"只改变 await 时机，不改变同步代码的阻塞行为。

## 待 Phase 6 审计

- 运行时正确性（资源管理、错误处理、边界条件）
- 跨文件一致性（接口对齐、引用正确）
- 从源文档提炼的知识对照
