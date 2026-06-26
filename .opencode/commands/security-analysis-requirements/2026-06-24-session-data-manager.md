# 插件代码拆分 + SessionDataManager + PluginContext 全局上下文

## §1 背景与目标

### 来源

代码审计和讨论中发现两类问题：
1. SessionData 创建逻辑散落在 3 个地方，代码重复、职责模糊
2. 插件单文件 1500+ 行，可维护性差

两者可以合并解决——重做 session 管理时顺便拆分文件。

### 痛点

| 问题 | 当前状态 |
|------|---------|
| 插件单文件过大 | security-analysis.ts 1568 行，所有逻辑挤在一个文件 |
| SessionData 创建散落 | 3 个创建点（doEnsureSession、requireSessionWithPrimary、间接通过 chat.message），代码几乎相同 |
| 职责模糊 | ensureSession 和 requireSessionWithPrimary 功能高度重叠 |
| nonPrimarySessions 冗余 | 用单独的 Set 缓存非 PRIMARY session |
| 并发去重散落 | pendingEnsures Map 是裸露的全局变量 |
| debugLog 循环依赖 | debugLog 依赖 getTaskDir 和 getAgentName，而它们又依赖 debugLog（手动 workaround 防栈溢出） |
| 全局状态散落 | opencodeClient 是裸露的模块级 `let`，directory 是 Plugin input 参数 |
| 缺少 parentSessionID | 无法判断子任务 |

### 预期收益

- 插件从 1 个文件拆分为 11 个文件，每个文件 30~500 行
- SessionData 创建点统一为 1 个（SessionDataManager.getOrCreate）
- 消除 debugLog 循环依赖（getTaskDirRaw 拆分方案，根治递归风险）
- debugLog 提取到 logging.ts，所有模块统一使用（日志逻辑一致）
- 全局状态统一收口到 PluginContext（client、directory、sessionManager）
- 删除 4 个散落函数 + 3 个全局变量
- SessionData 新增 parentSessionID 字段，为编排 agent 子任务方案打基础

## §2 技术方案

### 2.1 文件拆分方案

```
.opencode/plugins/
├── context.ts             ← 全局上下文（~30行）：PluginContext 类 + ctx 单例
├── constants.ts           ← 常量定义（~80行）
├── utils.ts               ← 纯工具函数（~50行）：getTaskDirRaw、getAgentName、clearTaskDirCache
├── logging.ts             ← 日志（~50行）：writeLog、trimLogFile、getLogFilePath、debugLog
├── task-session.ts        ← 任务目录映射（~60行）：getTaskDir、removeTaskSession、readJsonSafe
├── session-manager.ts     ← SessionData + SessionDataManager（~130行）
├── venv.ts                ← Python 虚拟环境管理（~100行）
├── snippet.ts             ← 占位符展开（~100行）：loadSnippet、hasBuwaiExtensionId、parseFrontmatter
├── persistence.ts         ← 分析持续性恢复（~200行）：maybeResumeAnalysis、checkLastMessageAborted 等
├── timeline.ts            ← 时间线记录（~80行）：recordTimeline、flushTimeline
└── security-analysis.ts   ← 主入口（~500行）：Plugin 函数 + hooks + abortSession + buildEnvSection
```

注意：
- `buildEnvSection` 和 `getCompactionContext`/`getCompactionReminder` 留在 security-analysis.ts，不移出（它们直接使用 debugLog + abortSession，且只在主文件的 hook 中调用）
- `debugLog` 提取到 logging.ts，所有模块统一使用它（见 §2.3）
- 新增 `context.ts`（全局上下文）和 `utils.ts`（纯工具函数），解决循环依赖（见 §2.3、§2.7）
- 类型定义跟随使用方：`TaskSessionMapping` → task-session.ts，`PersistenceData` → persistence.ts，`ConfigData`/`EnvData`/`ToolConfig` → 留在 security-analysis.ts（仅 hooks 使用）

### 2.2 依赖链（无循环）

```
context.ts             ← PluginContext 类 + ctx 单例（import type SessionDataManager，运行时零依赖）
constants.ts           ← 纯常量（无依赖）
    ↑
utils.ts               ← getTaskDirRaw（纯文件读取）、getAgentName（用 ctx）、clearTaskDirCache
    ↑                      import: context, constants
logging.ts             ← writeLog、trimLogFile、getLogFilePath、debugLog
    ↑                      import: constants, utils（getTaskDirRaw + getAgentName）
task-session.ts        ← getTaskDir（调 getTaskDirRaw + debugLog）、removeTaskSession、readJsonSafe
    ↑                      import: utils, logging
session-manager.ts     ← SessionData、SessionDataManager
    ↑                      import: constants, logging, context (import type only)
venv.ts                ← ensureVenvPython, PYTHON_CMD
    ↑                      import: logging
snippet.ts             ← loadSnippet, hasBuwaiExtensionId, parseFrontmatter
    ↑                      import: logging, constants
persistence.ts         ← maybeResumeAnalysis、checkLastMessageAborted 等
    ↑                      import: context, logging, task-session, session-manager (import type), constants
timeline.ts            ← recordTimeline, flushTimeline
    ↑                      import: logging, task-session, constants
security-analysis.ts   ← 主入口：Plugin + hooks + abortSession + buildEnvSection
                           import: 全部
```

关键设计点：
- `context.ts` 使用 `import type { SessionDataManager }`，TypeScript 类型擦除后运行时零依赖，不产生循环
- `logging.ts` 的 `debugLog` 调用 `utils.ts` 的 `getTaskDirRaw`（纯函数，不回调 debugLog）和 `getAgentName`（从 ctx 读，不回调 debugLog），彻底切断循环
- 所有模块统一使用 `debugLog`（从 logging.ts import），日志逻辑全局一致

### 2.3 循环依赖分析与解决方案

当前代码中存在 2 个循环依赖：

**循环 1：debugLog ↔ getTaskDir**
```
debugLog → 调 getTaskDir（决定日志路径）
getTaskDir catch → 调 debugLog（记录异常）
```

当前代码通过手动 workaround 规避递归（getTaskDir 第 319 行注释：`// 注意：此处不传 sessionID 给 debugLog，否则 debugLog→getTaskDir 会与此处形成无限递归`），但这是脆弱的——任何新代码调 `debugLog(msg, sessionID)` 都可能触发栈溢出。

**循环 2：debugLog ↔ session 管理**
```
debugLog → 调 getAgentName（决定日志路由）
doEnsureSession/requireSessionWithPrimary → 调 debugLog（记录日志）
```

**根因**：debugLog 的日志路由依赖业务函数（getTaskDir、getAgentName），而这些业务函数又依赖 debugLog 记录日志。

**解决方案：拆分 getTaskDir + 全局上下文 + debugLog 提取到 logging.ts**

1. **getTaskDir 拆分为两层**（根治循环 + 消灭递归风险）：

| 函数 | 文件 | 职责 | 调日志？ |
|------|------|------|---------|
| `getTaskDirRaw(sessionID)` | utils.ts | 纯文件读取 + JSON 解析 + 缓存，返回 `{ path, error? }` | ❌ 绝不调 |
| `getTaskDir(sessionID)` | task-session.ts | 调 getTaskDirRaw，有 error 时调 debugLog | ✅ |

`debugLog` 只调 `getTaskDirRaw`（不调 `getTaskDir`），彻底切断循环。同时消灭递归风险——不再需要手动 workaround。

2. **getAgentName 移到 utils.ts**：通过全局上下文 `ctx.sessionManager?.get(sessionID)?.agentName` 读取，不回调 debugLog。

3. **debugLog 提取到 logging.ts**：

```typescript
// logging.ts
function debugLog(msg: string, sessionID?: string): void {
  if (sessionID) {
    const result = getTaskDirRaw(sessionID);   // ← 调 Raw 版本，不回调 debugLog
    if (result.path) {
      writeLog(join(result.path, "logs", "plugin.log"), msg);
      return;
    }
    const agentName = getAgentName(sessionID);  // ← 从 ctx 读，不回调 debugLog
    writeLog(getLogFilePath(agentName), msg);
  } else {
    writeLog(DEFAULT_LOG, msg);
  }
}
```

4. **所有模块统一使用 debugLog**：底层模块（task-session.ts、session-manager.ts、persistence.ts 等）从 logging.ts import debugLog，日志逻辑全局一致。不再需要 `writeLog(DEFAULT_LOG, msg)` 降级处理。

### 2.4 SessionData 类

```typescript
// session-manager.ts
import { PRIMARY_AGENTS } from "./constants";
import { debugLog } from "./logging";

export class SessionData {
  readonly createdAt: number;
  agentName?: string;
  readonly parentSessionID?: string;
  systemTransformCount = 0;

  constructor(agentName?: string, parentSessionID?: string) {
    this.createdAt = Date.now();
    this.agentName = agentName;
    this.parentSessionID = parentSessionID;
  }

  isPrimaryAgent(): boolean {
    return !!this.agentName && PRIMARY_AGENTS.includes(this.agentName);
  }

  /** 当前未使用，预留给编排 agent 子任务方案 */
  isChildSession(): boolean {
    return !!this.parentSessionID;
  }
}
```

### 2.5 SessionDataManager 类

```typescript
// session-manager.ts
import { debugLog } from "./logging";

export class SessionDataManager {
  private sessions = new Map<string, SessionData>();
  private pending = new Map<string, Promise<SessionData | undefined>>();
  private client: OpencodeClient | null;

  constructor(client: OpencodeClient | null) {
    this.client = client;
  }

  /** 统一创建/获取入口。所有 session 都创建 SessionData（不管 agent 类型）。 */
  async getOrCreate(sessionID: string): Promise<SessionData | undefined> {
    const existing = this.sessions.get(sessionID);
    if (existing) return existing;

    const inFlight = this.pending.get(sessionID);
    if (inFlight) return inFlight;

    const promise = this.createFromAPI(sessionID);
    this.pending.set(sessionID, promise);
    try {
      return await promise;
    } finally {
      this.pending.delete(sessionID);
    }
  }

  /** 只返回 PRIMARY agent 的 session。不创建，委托给 getOrCreate。 */
  async requirePrimary(hookName: string, sessionID?: string): Promise<SessionData | undefined> {
    if (!sessionID) {
      debugLog(`[${hookName}] 跳过 — 无 sessionID`);
      return undefined;
    }
    const session = await this.getOrCreate(sessionID);
    if (!session) return undefined;
    if (!session.isPrimaryAgent()) {
      debugLog(`[${hookName}] 跳过 — 非 PRIMARY agent=${session.agentName || "无"} sessionID=${sessionID}`, sessionID);
      return undefined;
    }
    return session;
  }

  /** 同步获取（不触发创建）。 */
  get(sessionID: string): SessionData | undefined {
    return this.sessions.get(sessionID);
  }

  /** 更新 agentName（chat.message 中 agent 切换时调用）。 */
  setAgentName(sessionID: string, agentName: string): void {
    const session = this.sessions.get(sessionID);
    if (session) session.agentName = agentName;
  }

  /** 删除（session.deleted 时调用）。同时清理 pending 防止竞态。 */
  delete(sessionID: string): void {
    this.sessions.delete(sessionID);
    this.pending.delete(sessionID);
  }

  /** 私有：从 API 创建 SessionData。唯一的 new SessionData() 调用点。 */
  private async createFromAPI(sessionID: string): Promise<SessionData | undefined> {
    if (!this.client) {
      debugLog(`SessionDataManager: client 未初始化 sessionID=${sessionID}`, sessionID);
      return undefined;
    }
    try {
      const response = await this.client.session.get({ path: { id: sessionID } });
      if (response.error || !response.data) {
        debugLog(`SessionDataManager: API 错误 sessionID=${sessionID}`, sessionID);
        return undefined;
      }
      const sessionInfo = response.data;
      const agentName = (sessionInfo as { agent?: string })?.agent;
      const parentSessionID = (sessionInfo as { parentID?: string })?.parentID;
      const session = new SessionData(agentName, parentSessionID);
      this.sessions.set(sessionID, session);
      debugLog(`SessionDataManager: 创建 sessionID=${sessionID} agent=${agentName || "无"} parentID=${parentSessionID || "无"}`, sessionID);
      return session;
    } catch (e) {
      debugLog(`SessionDataManager: 异常 sessionID=${sessionID} error=${e}`, sessionID);
      return undefined;
    }
  }
}
```

注意：SessionDataManager 统一使用 `debugLog`（从 logging.ts import）。循环依赖已通过 §2.3 的 getTaskDirRaw 拆分方案解决，不再需要 `writeLog(DEFAULT_LOG, msg)` 降级处理。

**API 恢复的局限性**：SDK 的 `Session` 类型不含 `agent` 字段，API 恢复时 `agentName` 可能为 `undefined`。依赖 `chat.message` 后续设置正确的 agentName。在 agentName 被设置前，`isPrimaryAgent()` 返回 false，`requirePrimary` 会跳过所有 hook。

### 2.6 调用点变更对照

| 旧调用 | 新调用 | 涉及文件 |
|--------|--------|---------|
| `ensureSession(sessionID)` | `ctx.sessionManager!.getOrCreate(sessionID)` | security-analysis.ts (chat.message) |
| `requireSessionWithPrimary(hook, sid)` | `ctx.sessionManager!.requirePrimary(hook, sid)` | security-analysis.ts、persistence.ts (maybeResumeAnalysis) |
| `sessions.get(sid)?.agentName` | `ctx.sessionManager!.get(sid)?.agentName` | security-analysis.ts (event handler) |
| `sessions.delete(sid)` | `ctx.sessionManager!.delete(sid)` | security-analysis.ts (session.deleted) |
| `getAgentName(sessionID)` | `getAgentName(sessionID)`（从 utils.ts import） | logging.ts (debugLog)。security-analysis.ts 不再调用（见下方 fallbackAgent 移除） |
| `opencodeClient` | `ctx.client` | persistence.ts、security-analysis.ts (abortSession) |
| `nonPrimarySessions.add/delete/has` | 删除 | 不再需要（所有 session 统一在 SessionDataManager 中） |

chat.message hook 行为变化：不再区分 PRIMARY/非 PRIMARY 做特殊处理，所有 agent 统一调 `getOrCreate` + `setAgentName`。过滤由 `requirePrimary` 在下游 hook 中执行（`isPrimaryAgent()` 返回 false 就跳过）。功能等价。

buildEnvSection 代码清理：移除冗余的 `fallbackAgent`。当前代码（624 行）`const fallbackAgent = getAgentName(sessionID)` 读取的是同一个 session 的 agentName（调用方已经从 `session.agentName` 传入），与参数 `agentName` 完全相同。移除后 buildEnvSection 不再依赖 getAgentName，security-analysis.ts 无需 import getAgentName。同理 shell.env hook 中 `getScriptDir(agentName, session.agentName)` 简化为 `getScriptDir(agentName)`。

### 2.7 全局上下文 PluginContext

将散落在模块级的全局可变状态统一收口到一个类中。

```typescript
// context.ts
import type { OpencodeClient } from "@opencode-ai/sdk";
import type { SessionDataManager } from "./session-manager";  // import type — 运行时零依赖

class PluginContext {
  client: OpencodeClient | null = null;
  directory: string = "";
  sessionManager: SessionDataManager | null = null;

  /** Plugin 函数启动时调用，必须在任何 hook 触发之前完成 */
  init(client: OpencodeClient, directory: string, sessionManager: SessionDataManager): void {
    this.client = client;
    this.directory = directory;
    this.sessionManager = sessionManager;
  }
}

export const ctx = new PluginContext();
```

设计要点：
- `import type { SessionDataManager }` 是 TypeScript 纯类型导入，Node type-stripping 模式下完全擦除，`context.ts` 运行时零依赖
- Plugin 函数中的初始化顺序：`new SessionDataManager(client)` → `ctx.init(client, directory, sessionManager)` → 注册 hooks（hooks 在 return 之后才注册，ctx 一定先初始化完成）
- 所有模块通过 `ctx.client`、`ctx.sessionManager` 访问全局状态，不需要参数传递

收口的全局状态：

| 原位置 | 原变量 | 新位置 |
|--------|--------|--------|
| 模块级 `let`（718 行） | `opencodeClient` | `ctx.client` |
| Plugin input 参数 | `directory` | `ctx.directory` |
| 新建 | — | `ctx.sessionManager`（替代模块级 `sessions`/`pendingEnsures` Map） |

不收入 ctx 的模块级状态（各模块的私有实现细节）：
- `taskDirCache`（utils.ts 内部缓存）
- `timelineBuffers`、`toolStartTimes`（timeline.ts 内部缓存）
- `snippetCache`、`frontmatterCache`（snippet.ts 内部缓存）

### 2.8 删除/迁移清单

从 security-analysis.ts 中删除或迁移的代码：

| 删除/迁移项 | 去向 | 原因 |
|------------|------|------|
| `interface SessionData` | → session-manager.ts（改为 class） | 内聚 |
| `const sessions = new Map<...>()` | → SessionDataManager.sessions | 内聚 |
| `const nonPrimarySessions = new Set<...>()` | 删除 | 所有 session 统一管理 |
| `const pendingEnsures = new Map<...>()` | → SessionDataManager.pending | 内聚 |
| `let opencodeClient` | → ctx.client | 全局上下文统一管理 |
| `function getAgentName()` | → utils.ts | debugLog 需要它，放在 logging 下方 |
| `function ensureSession()` | → SessionDataManager.getOrCreate | 合并 |
| `function doEnsureSession()` | → SessionDataManager.createFromAPI | 合并 |
| `function requireSessionWithPrimary()` | → SessionDataManager.requirePrimary | 合并 |
| `function debugLog()` | → logging.ts | 所有模块统一使用 |
| `function writeLog()` / `trimLogFile()` / `getLogFilePath()` | → logging.ts | 日志基础设施 |
| `function getTaskDir()` | → task-session.ts（调 utils.ts 的 getTaskDirRaw） | 拆分解决循环依赖 |
| `function removeTaskSession()` / `readJsonSafe()` | → task-session.ts | 任务目录映射 |
| 各常量 | → constants.ts | 常量集中 |

## §3 实现规范

### 3.0 改动范围

| 文件 | 改动类型 |
|------|---------|
| `.opencode/plugins/context.ts` | 新建 |
| `.opencode/plugins/constants.ts` | 新建 |
| `.opencode/plugins/utils.ts` | 新建 |
| `.opencode/plugins/logging.ts` | 新建 |
| `.opencode/plugins/task-session.ts` | 新建 |
| `.opencode/plugins/session-manager.ts` | 新建 |
| `.opencode/plugins/venv.ts` | 新建 |
| `.opencode/plugins/snippet.ts` | 新建 |
| `.opencode/plugins/persistence.ts` | 新建 |
| `.opencode/plugins/timeline.ts` | 新建 |
| `.opencode/plugins/security-analysis.ts` | 重构为主入口，删除迁移出去的代码 |

### 3.1 实施步骤拆分

按依赖顺序从底层到上层逐步拆分。每步完成后 `node --check` 验证。

**步骤 1. context.ts + constants.ts（基础层）**
- 新建 context.ts：PluginContext 类 + ctx 单例
- 新建 constants.ts：提取所有常量（PRIMARY_AGENTS、DATA_DIR、LOGS_DIR 等）
- security-analysis.ts 改为 import 常量 from constants.ts
- 预估行数: ~110 新增 + ~10 修改
- 验证点: `node --check` 通过；security-analysis.ts 中不再有内联常量定义
- 依赖: 无

**步骤 2. utils.ts + logging.ts（日志基础设施 + 循环依赖消除）**
- 新建 utils.ts：getTaskDirRaw（纯文件读取，返回 `{ path, error? }`）、getAgentName（读 ctx.sessionManager）、clearTaskDirCache
- 新建 logging.ts：writeLog、trimLogFile、getLogFilePath、debugLog（调 utils.ts 的 getTaskDirRaw + getAgentName）
- security-analysis.ts 改为 import debugLog from logging.ts，删除本地 debugLog/writeLog/trimLogFile/getLogFilePath 定义
- 预估行数: ~100 新增 + ~15 修改
- 验证点: `node --check` 通过；security-analysis.ts 中不再有 debugLog/writeLog/trimLogFile/getLogFilePath 定义
- 依赖: 步骤 1

**步骤 3. task-session.ts（任务目录映射）**
- 新建 task-session.ts：getTaskDir（调 utils.ts 的 getTaskDirRaw + debugLog）、removeTaskSession（调 clearTaskDirCache）、readJsonSafe
- security-analysis.ts 改为 import 这些函数，删除本地定义
- 预估行数: ~60 新增 + ~10 修改
- 验证点: `node --check` 通过
- 依赖: 步骤 1、2

**步骤 4. session-manager.ts（核心：SessionData + SessionDataManager）**
- 新建 session-manager.ts：SessionData 类 + SessionDataManager 类（使用 debugLog）
- security-analysis.ts：
  - 删除旧的 interface SessionData、sessions Map、nonPrimarySessions、pendingEnsures、ensureSession、doEnsureSession、requireSessionWithPrimary、getAgentName
  - 在 Plugin 函数中添加 `const sessionManager = new SessionDataManager(client)` + `ctx.init(client, directory, sessionManager)`
  - 所有调用点替换为 `ctx.sessionManager!.xxx()`
- 预估行数: ~130 新增 + ~50 修改
- 验证点:
  - `node --check` 通过
  - `rg -n "\b(ensureSession|requireSessionWithPrimary|getAgentName|nonPrimarySessions|pendingEnsures)\b" .opencode/plugins/security-analysis.ts` 无匹配（排除注释）
  - `rg -n "const sessions\b" .opencode/plugins/security-analysis.ts` 无匹配
- 依赖: 步骤 1、2、3

**步骤 5. venv.ts + snippet.ts**
- 新建 venv.ts：提取 Python venv 管理相关代码
- 新建 snippet.ts：提取占位符展开相关代码
- security-analysis.ts 改为 import
- 预估行数: ~200 新增 + ~10 修改
- ⚠️ 如果实施时实际超过 200 行，拆分为 5a（venv.ts）和 5b（snippet.ts）
- 验证点: `node --check` 通过
- 依赖: 步骤 1、2

**步骤 6. persistence.ts（分析持续性恢复）**
- 新建 persistence.ts：maybeResumeAnalysis、checkLastMessageAborted、getLastAssistantText、readPersistenceData、getMaxDuration、recordResumeAttempt
- 所有函数通过 `ctx.client`、`ctx.sessionManager!`、`debugLog`（import）访问外部资源
- security-analysis.ts 的 event hook 改为 `await maybeResumeAnalysis(sessionID)`（从 persistence.ts import）
- 预估行数: ~200 新增 + ~10 修改
- ⚠️ 如果实施时实际超过 200 行，拆分为 6a（helpers）和 6b（maybeResumeAnalysis）
- 验证点: `node --check` 通过
- 依赖: 步骤 1、2、3、4

**步骤 7. timeline.ts**
- 新建 timeline.ts：recordTimeline、flushTimeline、formatTimelineEntry、timelineBuffers
- security-analysis.ts 改为 import recordTimeline/flushTimeline
- `toolStartTimes` 留在 security-analysis.ts（仅 tool.execute.before/after 两个 hook 直接使用，不属于 timeline 模块职责）
- 预估行数: ~80 新增 + ~10 修改
- 验证点: `node --check` 通过
- 依赖: 步骤 2、3

**步骤 8. 最终清理**
- security-analysis.ts 确认为主入口：Plugin 函数 + hooks + abortSession + buildEnvSection + getCompactionContext/Reminder
- 确认所有 import 正确
- 确认无残留的旧代码（旧函数定义、旧全局变量）
- 预估行数: ~30 修改
- 验证点:
  - `node --check` 通过
  - security-analysis.ts 行数 < 550
  - `wc -l .opencode/plugins/*.ts` 查看各文件行数
  - 端到端验证：OpenCode 加载插件后确认 `SecurityAnalysisPlugin` export 被正确识别
- 依赖: 步骤 1~7

## §4 验收标准

### 功能验收
- `node --check` 语法检查通过（所有 .ts 文件）
- 端到端验证：OpenCode 加载插件后确认 `SecurityAnalysisPlugin` export 被正确识别（验证相对 import 在 type-stripping 模式下工作）
- 所有旧函数名在 security-analysis.ts 中零引用（排除注释）
- 所有旧全局变量在 security-analysis.ts 中零引用
- chat.message 正常注册 session（所有 agent 统一处理，不再区分 PRIMARY/非 PRIMARY）
- system.transform 正常注入环境信息
- shell.env 正常注入环境变量
- session.idle 正常恢复

### 回归验收
- 非 PRIMARY session 执行 bash 时 shell.env 静默跳过（由 requirePrimary 过滤）
- PRIMARY session 执行 bash 时 shell.env 正常注入所有环境变量
- config.json 不存在时 system.transform 调 abortSession 终止会话
- 插件重启后 session 能通过 API 恢复（agentName 可能为 undefined，依赖 chat.message 设置）

### 架构验收
- 11 个文件，每个文件职责单一
- 依赖链无循环（context → constants → utils → logging → task-session → session-manager → ... → security-analysis）
- debugLog 提取到 logging.ts，所有模块统一使用（不再有 writeLog(DEFAULT_LOG) 降级）
- getTaskDirRaw（纯函数）在 utils.ts 中，debugLog 只调 getTaskDirRaw 不调 getTaskDir，彻底消除递归风险
- SessionData 的 `new` 调用只在 SessionDataManager.createFromAPI 中
- PluginContext 统一管理全局状态（client、directory、sessionManager），模块级不再有散落的 `let opencodeClient`
- buildEnvSection 留在 security-analysis.ts（不移出）
- security-analysis.ts < 550 行

## §5 与现有需求文档的关系

- `2026-05-30-env-injection-timing-fix.md`：环境变量注入迁移到 shell.env（已实施）
- `2026-05-26-plugin-inject-python-cmd.md`：PYTHON_CMD 注入（已实施）
- `2026-06-13-analysis-persistence.md`：分析持续性恢复（已实施，maybeResumeAnalysis 函数已提取）
- 本文档：插件代码拆分 + SessionDataManager 统一管理 + 循环依赖消除（getTaskDirRaw 拆分）+ PluginContext 全局上下文 + debugLog 统一提取
