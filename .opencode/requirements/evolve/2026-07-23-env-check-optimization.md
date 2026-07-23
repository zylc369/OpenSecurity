# 需求文档: 环境检测性能优化 + prompt 注入精简 + 去掉 env_cache.json

## §1 背景与目标

### 来源痛点

与用户讨论（2026-07-23），基于对 `chat.message` 环境检测链路的复盘，发现 4 个问题：

1. **每条 chat.message 都 spawn detect_env.py**：`checkEnvironment` → `runDetectEnv` → spawn Python 子进程跑全量检测（find_spec ~25 个包 + shutil.which 多个工具 + docker info/ps），timeout 8 秒。同一台机器同一进程内环境状态稳定，重复检测纯属浪费。用户体感：每条消息延迟 1-3 秒。

2. **evolve 也走完整环境检测但无实际价值**：detect_env.py 的 `PYTHON_PACKAGES` 和 `EXTERNAL_TOOLS` 里没有任何 dep 把 `security-analysis-evolve` 加进 `agents=` 字段。evolve 实际只触发 4 个 MCP 基础包 + 编译器检测，而 evolve 的工作（改代码、读代码、写文档）不依赖这些。

3. **buildEnvSection 注入大量 token 浪费**：
   - Python 包列表（`mcp@1.28.1, sentence_transformers@5.6.0, ...`）：~200 token/次，但 agent 已知用什么包（agent.md 描述）+ fail-fast 保证包装了 + 版本号对决策无价值
   - 外部工具列表（`apktool: /opt/homebrew/bin/apktool (3.0.2)`）：~100 token/次，但工具都在 PATH 里，agent 直接调名字即可
   - 编译器完整路径：agent 用 `clang`/`gcc` 调用即可，不需要 `/usr/bin/clang`
   - IDA Pro 完整路径：shell.env 已注入 `$IDAT`，prompt 里再写一遍路径冗余

4. **env_cache.json 价值变窄**：原设计是把 detect_env.py 的全量检测结果传给 system.transform 注入 prompt。但优化 3 决定去掉大部分注入内容后，env_cache.json 唯一不可替代的字段是 `ida_pro.idat_path`（shell.env 注入 `$IDAT` 的来源）。为一个字段维护一个 JSON 文件不划算——shell.env 可以直接读 `.ai_env` 拼接（成本：读 9 行文本 + 1 次 isfile，微秒级）。

### 目标

1. **并行预热**：Plugin 启动时并行检测 5 领域 agent + Coordinator，chat.message 命中 Promise cache 时跳过 spawn
2. **evolve 排除环境检测**：chat.message 对 evolve 只查 venv 存在性，不跑 runDetectEnv
3. **buildEnvSection 精简**：去掉 packages/tools 列表，简化 IDA Pro 和编译器提示
4. **去掉 env_cache.json**：新增 `getIdatPath()` + `getCompilerName()`（惰性缓存，对齐 `getPythonCmd()` 模式），detect_env.py 不再写 cache

### 预期收益（四维度量）

| 维度 | 改进前 | 改进后 |
|------|--------|--------|
| 速度 | 每条 chat.message spawn 1 次 Python（1-3 秒） | 首条 await 预热，后续命中 Promise cache（~0 秒） |
| 上下文 | 每次注入 ~500 token（packages 200 + tools 100 + 编译器 30 + IDA 20 + 其他 150） | 每次注入 ~150 token（去掉 packages/tools，简化 IDA/编译器） |
| 准确度 | env_cache.json 可能因并发写入/时序导致内容偏差 | 实时读 .ai_env，无 cache 失效问题 |
| 轮次 | 无变化 | 无变化 |

### 不兼容声明

- env_cache.json 不再生成（已有文件不会被主动删除，但不再更新）
- 用户修改 `.ai_env` 后无需重启 Plugin 即可生效（getIdatPath 惰性缓存只在首次计算）——但若 idat_path 已缓存，需重启 Plugin 才能刷新

## §2 技术方案

### 2.1 并行预热 + Promise cache

模块级 Map 存每个 agent 的检测 Promise：

```ts
const envCheckPromises = new Map<string, Promise<EnvironmentCheckResult>>();
```

Plugin setup 函数里（fire-and-forget，不 await）启动并行预热：

```ts
const preheatAgents = [...SECURITY_ANALYSIS_AGENTS, AGENT_SECURITY_COORDINATOR];
for (const agent of preheatAgents) {
  envCheckPromises.set(agent, preheatEnvCheck(agent));
}
```

`preheatEnvCheck(agent)` 封装（替代原 `checkEnvironment`）：

```ts
async function preheatEnvCheck(agent: string): Promise<EnvironmentCheckResult> {
  const pythonCmd = getPythonCmd();
  if (!pythonCmd) {
    return { ready: false, message: getInstallHint() };  // venv 未就绪
  }
  try {
    return await runDetectEnv(agent, pythonCmd, "preheat");  // sessionID="preheat"
  } catch (e) {
    return { ready: false, message: `[预热异常] ${(e as Error)?.message}` };
  }
}
```

**sessionID 处理**：预热时无真实 session 上下文，传 `"preheat"` 占位。runDetectEnv 用 sessionID 调 `getTaskDir("preheat")` 返回 null → buildDetectEnvArgs 不加 `--output` → detect_env.py 不写 taskDir/env.json（与去掉 cache 的目标一致）。

**原 checkEnvironment 的 .ai_env 创建逻辑删除**：原 checkEnvironment（security-analysis.ts 行 268-275）在 .ai_env 不存在时创建空文件。但 detect_env.py 的 `_ensure_ai_env_template`（行 248-258）已会创建带注释的模板——Plugin 这边是冗余，删除。

chat.message 改造（三分支）：

```ts
// 分支 1: 命中预热的 agent → await Promise（已完成则立即返回）
if (envCheckPromises.has(agent)) {
  const envCheck = await envCheckPromises.get(agent)!;
  if (!envCheck.ready) {
    // 失败时重新 set 异步 preheat（不阻塞当前 abort），让用户修复后下次有机会重试
    envCheckPromises.set(agent, preheatEnvCheck(agent));
  }
  // ... 后续 fail-fast 逻辑（reportErrorAndAbort）不变
}
// 分支 2: evolve / searcher / memorist → 只查 venv，不跑 runDetectEnv
// （它们的工作不依赖领域专用 Python 包/工具）
else if (
  agent === AGENT_SECURITY_ANALYSIS_EVOLVE ||
  agent === AGENT_SEARCHER ||
  agent === AGENT_MEMORIST
) {
  const pythonCmd = getPythonCmd();
  if (!pythonCmd) {
    await reportErrorAndAbort(ctx.client, sessionID, sessionData, getInstallHint());
    return;
  }
}
// 分支 3: 其他未识别 agent → 跳过环境检测
else {
  /* skip */
}
```

**失败重试策略**：失败时 `envCheckPromises.set(agent, preheatEnvCheck(agent))` 重新发起异步预热（fire-and-forget，不阻塞当前 abort）。当前 chat.message 仍 abort 提示用户。用户修复环境后下次发消息时，新的 Promise 可能已完成（命中）或仍在跑（await）。

**并发写入风险**：5 个进程并行写 env_cache.json。但本需求要去掉 env_cache.json（§2.4），所以这个风险自然消除。

### 2.2 evolve/searcher/memorist 排除环境检测

evolve 的工作（改代码、读代码、写文档）不依赖 Python 包或编译器。searcher/memorist 的工作（信息检索、记忆检索）同样不依赖领域专用包。这三个 agent 的 chat.message 只需检查 venv 存在（因为它们会通过 bash 调 `$PYTHON_CMD`）。

不预热这三个 agent，chat.message 对它们走轻量路径（只查 getPythonCmd）。

### 2.3 buildEnvSection 精简

**删除**：
- Python 包列表注入（packages 字段）
- 外部工具列表注入（tools 字段）

**简化**：
- IDA Pro：从 `IDA Pro: /Applications/.../MacOS` + `idat ($IDAT): /Applications/.../idat` 简化为 `IDA Pro: 已配置（用 $IDAT 调用 idat）`
- 编译器：从 `编译器: clang (/usr/bin/clang)` 简化为 `编译器: clang（在 PATH 中可用）`

**保留**（必需）：
- 目录路径（OPENCODE_ROOT/AGENT_DIR/TASK_DIR/SHARED_DIR）
- Flow ID（agent 调 MCP 必传 group_id）
- `$PYTHON_CMD`
- IDA Pro 可用性提示（让 agent 知道能用 IDA）
- 编译器可用性提示（让 agent 知道能编译）

### 2.4 去掉 env_cache.json

**新增函数**（venv.ts，对齐 `getPythonCmd()` 模式）：

```ts
// 读 .ai_env 解析为 KEY-VALUE 对象
export function readAiEnv(): Record<string, string> { ... }

// 惰性缓存：拼接 $IDA_PRO_HOME/idat + isfile 校验
export function getIdatPath(): string | null { ... }

// 惰性缓存：which clang/gcc/cc
export function getCompilerName(): string | null { ... }
```

**消费方改造**：
- `shell.env`：`readEnvCache` → `getIdatPath()`
- `buildEnvSection`：`readEnvCache` → `getIdatPath()` + `getCompilerName()`
- `system.transform`：删除 `readEnvCache` 调用

**detect_env.py 改造**：
- 删除 `_save_cache` 函数 + `_check_preinstall` 里的调用点
- 删除 `CACHE_FILE` 常量
- fail-fast 校验逻辑全部保留（用户配置错误时仍立即提示）

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响级别 |
|------|---------|---------|
| `plugins/lib/venv.ts` | 新增 readAiEnv + getIdatPath + getCompilerName | 中 |
| `plugins/security-analysis.ts` | 并行预热 + Promise cache + evolve 排除 + buildEnvSection 精简 + shell.env 改造 + 删 EnvData 接口 | 高 |
| `plugins/lib/task-session-persistence.ts` | 删除 readEnvCache 方法 + ENV_CACHE_FILE import | 低 |
| `plugins/lib/constants.ts` | 删除 ENV_CACHE_FILE 常量 | 低 |
| `binary-analysis/scripts/detect_env.py` | 删除 _save_cache + CACHE_FILE + 调用点 | 中 |

### 编码规则

- 新增函数对齐 `getPythonCmd()` 的惰性缓存模式（模块级 `let cached` + 首次计算 + 后续返回）
- `getIdatPath()` 跨平台处理（Windows 加 `.exe`）
- `getCompilerName()` 跨平台处理（Windows 用 `where`，Unix 用 `which`）
- 所有新增函数打 debugLog（首次计算时记录结果）
- 并行预热用 fire-and-forget（不 await，不阻塞 Plugin setup）

### §3.1 实施步骤拆分

**步骤 1. venv.ts 新增 readAiEnv + getIdatPath + getCompilerName**
- 文件: `plugins/lib/venv.ts`
- 改动: 新增 3 个函数
  - `readAiEnv()`: 读 `.ai_env`（纯文本 KEY=VALUE），解析为 `Record<string, string>`，忽略注释和空行
  - `getIdatPath()`: 惰性缓存。首次：`readAiEnv().IDA_PRO_HOME` → 拼接 `idat`（Windows 加 `.exe`）→ `existsSync` 校验 → 缓存结果。后续：直接返回缓存
  - `getCompilerName()`: 惰性缓存。首次：`spawnSync(which/where, ["clang"])` → 找到则缓存名字。候选：`clang` → `gcc` → `cc`（Unix）或 `clang.exe` → `gcc.exe` → `cl.exe`（Windows）
- 预估行数: ~60 行新增
- 验证点: `node --check venv.ts` 通过；手动测试 `readAiEnv()` 返回 `{IDA_PRO_HOME: "...", DEEPSEEK_API_KEY: "..."}`；`getIdatPath()` 返回正确路径或 null；`getCompilerName()` 返回 "clang" 或 null
- 依赖: 无

**步骤 2. detect_env.py 删除 _save_cache + CACHE_FILE**
- 文件: `binary-analysis/scripts/detect_env.py`
- 改动:
  - 删除 `_save_cache` 函数（行 436-439）
  - 删除 `_check_preinstall` 里 `_save_cache(data)` 调用（行 927）
  - 删除 `CACHE_FILE` 常量（行 39）
  - `CACHE_DIR` 保留（VENV_DIR 仍用）
- 预估行数: ~10 行删除
- 验证点: `python -c "compile(open('...').read(), '...', 'exec')"` 通过；`detect_env.py check-preinstall all` 仍输出完整 JSON（success/data/errors）；env_cache.json 不再被写入（文件 mtime 不变）
- 依赖: 无（与步骤 1 并行）

**步骤 3. task-session-persistence.ts 删除 readEnvCache**
- 文件: `plugins/lib/task-session-persistence.ts`
- 改动:
  - 删除 `readEnvCache` 静态方法（行 90-101）
  - 删除 `ENV_CACHE_FILE` import（行 9 中 ENV_CACHE_FILE 部分，保留 TASK_SESSIONS_DIR/WORKSPACE_DIR）
- 预估行数: ~15 行删除
- 验证点: `node --check task-session-persistence.ts` 通过
- 依赖: 无（与步骤 1/2 并行）

**步骤 4. constants.ts 删除 ENV_CACHE_FILE**
- 文件: `plugins/lib/constants.ts`
- 改动: 删除 `ENV_CACHE_FILE` 定义（行 25）
- 预估行数: 1 行删除
- 验证点: `node --check constants.ts` 通过；grep 确认无 `ENV_CACHE_FILE` 残留引用（排除 requirements/evolve）
- 依赖: 步骤 3（task-session-persistence 不再 import）+ 步骤 5（security-analysis 不再 import）

**步骤 5. security-analysis.ts: buildEnvSection 精简 + shell.env 改用 getIdatPath + 删 EnvData**
- 文件: `plugins/security-analysis.ts`
- 改动:
  - 删除 `EnvData` 接口（行 52-77）
  - 删除 `ENV_CACHE_FILE` import（行 18）
  - `buildEnvSection` 签名改为不接收 `envInfo` 参数（只接收 agentName + session）
  - `buildEnvSection` 删除 packages 注入（行 177-184）+ tools 注入（行 187-195）
  - `buildEnvSection` 简化 IDA Pro（行 155-161）：用 `getIdatPath()` 判断，注入 `IDA Pro: 已配置（用 $IDAT 调用 idat）` 或 `IDA Pro: 未配置`
  - `buildEnvSection` 简化编译器（行 168-176）：用 `getCompilerName()` 判断，注入 `编译器: clang（在 PATH 中可用）` 或 `编译器: 未检测到`
  - `buildEnvSection` 删除 `envInfo?.packages` 相关逻辑
  - `system.transform` 删除 `readEnvCache` 调用（行 1038-1039），不再传 envInfo 给 buildEnvSection
  - `shell.env` 改用 `getIdatPath()`（行 1143-1147）：删除 `readEnvCache` 调用，改 `const idatPath = getIdatPath()`
  - 删除 startup 日志里的 `ENV_CACHE_FILE` 引用（行 803, 809）：`debugLog(ENV_CACHE_FILE: ...)` 和 `debugLog(env_cache exists: ...)` 两行删除
  - import `getIdatPath`, `getCompilerName` from "./lib/venv"
- 预估行数: ~95 行修改（删除 ~75 行 + 修改 ~20 行）
- 验证点: `node --check security-analysis.ts` 通过；启动后日志显示 buildEnvSection 不再注入 packages/tools；shell.env 日志显示 IDAT 注入来自 getIdatPath
- 依赖: 步骤 1（getIdatPath/getCompilerName 就绪）+ 步骤 3（readEnvCache 已删）

**步骤 6. security-analysis.ts: 并行预热 + Promise cache + evolve 排除**
- 文件: `plugins/security-analysis.ts`
- 改动:
  - 新增模块级 `const envCheckPromises = new Map<string, Promise<EnvironmentCheckResult>>()`
  - 新增 `preheatEnvCheck(agent)` 函数：封装 getPythonCmd + runDetectEnv，返回 Promise（catch 错误转 `{ready:false, message:...}`）
  - setup 函数里 fire-and-forget 启动并行预热：遍历 `[...SECURITY_ANALYSIS_AGENTS, AGENT_SECURITY_COORDINATOR]`，每个 agent 调 `preheatEnvCheck` 并存入 Map
  - chat.message 改造：
    - agent 在 `envCheckPromises` 中 → `await envCheckPromises.get(agent)!`，失败时 delete（让下次重试）
    - agent === AGENT_SECURITY_ANALYSIS_EVOLVE → 只查 `getPythonCmd()`，null 则 abort
    - 其他 agent（searcher/memorist 等）→ 跳过环境检测
  - 删除 `checkEnvironment` 函数（被 preheatEnvCheck + chat.message 内联逻辑替代），或保留为 preheatEnvCheck 的别名
- 预估行数: ~70 行修改（新增 ~50 行 + 修改 ~20 行）
- 验证点: `node --check` 通过；启动日志显示并行预热 6 个 agent；首次 chat.message（领域 agent）日志显示 Promise cache 命中；evolve chat.message 日志显示跳过 runDetectEnv
- 依赖: 步骤 5

**步骤 7. 端到端验证**
- 验证点:
  1. **并行预热**: Plugin 启动后日志显示 6 个 agent 的 preheatEnvCheck 启动
  2. **Promise cache 命中**: 首条 chat.message（领域 agent）日志显示"命中预热 cache"，不 spawn detect_env.py
  3. **evolve/searcher/memorist 轻量路径**: 这些 agent 的 chat.message 日志显示"跳过 runDetectEnv，只查 venv"
  4. **buildEnvSection 精简**: system.transform 注入的环境信息不含 packages/tools 列表
  5. **shell.env IDAT**: shell.env 日志显示 IDAT 注入来自 getIdatPath，值正确
  6. **env_cache.json 不再写入**: 运行后 env_cache.json 的 mtime 不变
  7. **detect_env.py 仍可 fail-fast**: 手动改错 .ai_env 的 IDA_PRO_HOME → 重启 Plugin → 预热失败 → chat.message abort 并提示
  8. **.ai_env 修改生效**: 修改 .ai_env 加正确 IDA_PRO_HOME → 重启 Plugin → getIdatPath 返回正确路径
- 依赖: 步骤 1-6

## §4 验收标准

### 功能验收

- [ ] Plugin 启动时并行预热 6 个 agent（5 领域 + Coordinator），日志可见
- [ ] chat.message 对领域 agent 命中 Promise cache（不 spawn detect_env.py）
- [ ] chat.message 对 evolve/searcher/memorist 只查 venv，不跑 runDetectEnv
- [ ] buildEnvSection 不再注入 packages/tools 列表
- [ ] buildEnvSection IDA Pro 提示简化为"已配置（用 $IDAT 调用）"或"未配置"
- [ ] buildEnvSection 编译器提示简化为"clang（在 PATH 中可用）"或"未检测到"
- [ ] shell.env 通过 getIdatPath() 注入 IDAT
- [ ] detect_env.py check-preinstall 仍正常输出 JSON（fail-fast 逻辑不变）
- [ ] env_cache.json 不再被写入

### 回归验收

- [ ] detect_env.py `compile` 通过
- [ ] security-analysis.ts / venv.ts / task-session-persistence.ts / constants.ts `node --check` 通过
- [ ] detect_env.py check-preinstall all 仍能检测所有依赖并 fail-fast
- [ ] shell.env 注入的 SESSION_ID/AGENT_NAME/PYTHON_CMD/OPENCODE_ROOT/SHARED_DIR/TASK_DIR/OPENSECURITY_FLOW_ID 不受影响
- [ ] searcher/memorist 的 chat.message 走轻量 venv 检查（不再 spawn detect_env.py）

### 架构验收

- [ ] env_cache.json 完全退场（detect_env.py 不写、Plugin 不读）
- [ ] `.ai_env` 成为唯一环境配置源（用户输入）
- [ ] 新增函数（getIdatPath/getCompilerName）与 getPythonCmd 同模式（惰性缓存）
- [ ] 依赖方向: venv.ts ← security-analysis.ts（单向）；detect_env.py 不再被 Plugin 读 cache
- [ ] 无循环依赖

## §5 与现有需求文档的关系

- `2026-07-05-env-check-refactor.md`: 本需求是其后续优化。前者建立了 `_check_preinstall` 全量检测 + 写 env_cache.json 机制；本需求发现"全量写入 prompt"是 token 浪费、"每条消息重复检测"是性能浪费，因此去掉 cache + 并行预热。detect_env.py 的 fail-fast 校验逻辑（按 agent 过滤）全部保留。
- `2026-07-17-install-architecture-simplify.md`: 确立了 venv.ts 的惰性缓存模式（getPythonCmd）。本需求新增的 getIdatPath/getCompilerName 对齐这个模式。
- `2026-07-15-detect-env-subcommand-refactor.md`: 确立了 check-preinstall 子命令。本需求不改变子命令接口，只删除其 `_save_cache` 副作用。
