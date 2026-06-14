# 需求文档: 分析持续性增强 — 自动恢复中断的安全分析

## §1 背景与目标

**来源痛点**: 安全分析 Agent（binary-analysis、mobile-analysis、web-analysis、ai-security-analysis、security-coordinator）执行几十分钟后自动停止，输出候选方案或咨询用户。用户期望：如果分析没完成，应该一直分析下去不要问用户。

**根因确认**: Agent prompt 已充分强调"持续工作不停下"（execution-discipline.md 有大量禁止停顿规则），但 LLM 在长时间运行后仍会自然停止生成（上下文耗尽、自身判断需要确认等）。这不是 prompt 问题，是 LLM 行为层面的限制，需要 Plugin 层面的自动恢复机制。

**预期收益**:
- 减少对话轮次：从"AI 停止 → 用户手动继续 → AI 继续"的 2 轮交互，变为自动恢复的 0 轮交互
- 提升分析速度：消除用户手动介入的延迟（可能几十分钟到数小时）
- 提升结果连贯性：AI 连续工作时分析思路不中断

## §2 技术方案

### 2.1 核心机制：Hook `session.idle` 事件 + `promptAsync` 自动恢复

**原理**: OpenCode 在 session 空闲时发出 `session.idle` 事件。Plugin 的 `event` hook 可以捕获此事件，判断该 session 是否属于安全分析 Agent 的主 session，如果是且未超过最大持续时间，则通过 `client.session.promptAsync()` API 自动向该 session 发送一条恢复提示消息。

**恢复提示内容**: `你之前的分析是否已经完成了？如果已经完成，请直接输出最终结论。如果尚未完成，请自主继续分析，不要停下来向用户提问。`

**判断逻辑**:
1. 事件类型为 `session.idle`
2. 通过 `requireSessionWithPrimary` 判断是否为主 Agent 的主 session
  3. 非 PRIMARY_AGENT 的 session（包括子 session 和 security-analysis-evolve）直接跳过
  4. 当前时间 - session.createdAt < 最大持续时间（默认 6 小时或任务指定时间）
  5. 该 session 有对应的 `$TASK_DIR`（无 taskDir = 简单问答，不需要恢复）
  6. `promptAsync` 调用参数（v1 SDK 格式）: `{ path: { id: sessionID }, body: { parts: [{ type: "text", text: RESUME_PROMPT }] } }`

**子 session 判断**: 复用现有 `requireSessionWithPrimary` 逻辑。该函数在 Map miss 时通过 `client.session.get` API 查询 session info，并递归解析父链获取 `primaryAgent`。对于子 session（有 `parentID`），`agentName` 通常是 `"general"` 等非 PRIMARY_AGENT 名，会被 `PRIMARY_AGENTS.includes(agentName)` 过滤掉。

**`session.idle` 事件 properties**: `{ sessionID: string }`。与 `session.created` 等事件不同，`session.idle` 没有 `info` 字段，只从 `properties.sessionID` 提取。

### 2.2 最大持续时间控制

- 默认最大持续时间：6 小时（21600000 毫秒）
- 用户可以在任务启动时通过提示词指定最大持续时间（如"分析 2 小时"）
- 指定时间写入 `$TASK_DIR/.persistence.json` 文件
- 恢复前读取该文件，优先使用任务指定时间
- 文件格式为 JSON：
  ```json
  {
    "max_duration_hours": 6,
    "resume_count": 3,
    "last_resume_at": "2026-06-13T10:30:00.000Z"
  }
  ```
- 每次成功发送恢复消息后，`resume_count` +1，`last_resume_at` 更新为当前时间

### 2.3 子 Agent 不恢复

- Task 工具创建的子 session（有 `parentID`）不触发恢复
- security-coordinator 作为编排 Agent，其子 session 也不触发恢复
- 只对主 Agent 的主 session 做恢复

### 2.4 日志记录

恢复动作前后都写日志，便于调试：
- 恢复前日志：sessionID、agent、已持续时间、最大持续时间
- 恢复后日志：sessionID、发送的消息内容
- 跳过日志：sessionID、跳过原因（子 session / 超时 / 非 PRIMARY_AGENT）

## §3 实现规范

### 3.1 实施步骤拆分

#### 步骤 1: 在 SessionData 中添加创建时间追踪

- **文件**: `.opencode/plugins/security-analysis.ts`
- **预估行数**: ~10 行
- **验证点**: `SessionData` 接口已有 `createdAt` 字段（实际已有），确认用于持续时间计算
- **依赖**: 无

#### 步骤 2: 添加最大持续时间常量和恢复提示消息

- **文件**: `.opencode/plugins/security-analysis.ts`
- **预估行数**: ~5 行
- **验证点**: 常量定义正确，类型注入正确
- **依赖**: 步骤 1

```
const MAX_DURATION_DEFAULT = 6 * 60 * 60 * 1000; // 6 小时，单位毫秒
const PERSISTENCE_FILE = ".persistence.json";
const RESUME_PROMPT = "你之前的分析是否已经完成了？如果已经完成，请直接输出最终结论。如果尚未完成，请自主继续分析，不要停下来向用户提问。";
```

#### 步骤 3: 添加持续性状态文件读写函数

- **文件**: `.opencode/plugins/security-analysis.ts`
- **预估行数**: ~60 行
- **验证点**: 
  1. `readPersistenceData` 从 `$TASK_DIR/.persistence.json` 读取 JSON，文件不存在或无效时返回 null
  2. `getMaxDuration` 使用 `readPersistenceData` 获取 `max_duration_hours`，回退到默认 6 小时
  3. `recordResumeAttempt` 在成功恢复后更新 `.persistence.json` 的 `resume_count` 和 `last_resume_at`
  4. 文件格式包含 `max_duration_hours`、`resume_count`、`last_resume_at` 三个字段
- **依赖**: 步骤 2

```typescript
interface PersistenceData {
  max_duration_hours: number;
  resume_count: number;
  last_resume_at: string | null;
}

function readPersistenceData(sessionID: string): PersistenceData | null {
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) return null;
  const filePath = join(taskDir, ".persistence.json");
  try {
    const content = readFileSync(filePath, "utf-8").trim();
    const data = JSON.parse(content) as PersistenceData;
    // 校验 max_duration_hours
    if (typeof data.max_duration_hours === "number" && data.max_duration_hours > 0 && data.max_duration_hours <= 24) {
      return { ... };
    }
  } catch { /* 文件不存在或 JSON 解析失败 */ }
  return null;
}

function getMaxDuration(sessionID: string): number {
  const data = readPersistenceData(sessionID);
  if (data) return Math.floor(data.max_duration_hours * 3600 * 1000);
  return MAX_DURATION_DEFAULT;
}

function recordResumeAttempt(sessionID: string): void {
  // 读取现有数据 → 递增 resume_count → 更新 last_resume_at → 写回文件
}
```

#### 步骤 4: 在 event hook 中添加 `session.idle` 处理逻辑

- **文件**: `.opencode/plugins/security-analysis.ts`
- **预估行数**: ~80 行
- **验证点**:
  1. `session.idle` 事件被捕获（`properties.sessionID`）
  2. 通过 `requireSessionWithPrimary` 判断是否为主 Agent 的主 session
  3. 超过最大持续时间时不发送
  4. 子 session（Task 工具创建的，agent 为 "general" 等）不触发恢复
  5. security-analysis-evolve agent 不触发恢复（进化 Agent 不做分析工作）
  6. 无 taskDir 的 session 不触发恢复（简单问答，不是正式分析任务）
  8. `promptAsync` 调用参数正确（v1 SDK 格式: `{ path: { id: sessionID }, body: { parts: [{ type: "text", text: RESUME_PROMPT }] } }`）
  8. 日志正确输出（恢复前、恢复后、跳过时各有日志）
  9. `recordResumeAttempt` 在成功恢复后更新 `.persistence.json`
- **依赖**: 步骤 2、3

关键逻辑：
```typescript
if (event.type === "session.idle") {
  const sessionID = props.sessionID as string | undefined;
  if (!sessionID) return;
  
  // 1. 用 requireSessionWithPrimary 判断是否为主 Agent 的主 session
  const session = await requireSessionWithPrimary("session.idle", sessionID);
  if (!session) {
    debugLog(`session.idle: 跳过 — 非 PRIMARY sessionID=${sessionID}`, sessionID);
    return;
  }
  
  // 2. security-analysis-evolve 不触发恢复
  if (session.primaryAgent === AGENT_SECURITY_ANALYSIS_EVOLVE) {
    debugLog(`session.idle: 跳过 — evolve agent 不做分析工作, sessionID=${sessionID}`, sessionID);
    return;
  }
  
  // 3. 无 taskDir 的 session 不触发恢复（简单问答，不是正式分析任务）
  const taskDir = getTaskDir(sessionID);
  if (!taskDir) {
    debugLog(`session.idle: 跳过 — 无 taskDir（非正式分析任务）, sessionID=${sessionID}`, sessionID);
    return;
  }
  
  // 4. 计算已持续时间
  const elapsed = Date.now() - session.createdAt;
  const maxDuration = getMaxDuration(sessionID);
  if (elapsed >= maxDuration) {
    debugLog(`session.idle: 跳过 — 已超时 sessionID=${sessionID} elapsed=${Math.floor(elapsed/60000)}m max=${Math.floor(maxDuration/60000)}m`, sessionID);
    return;
  }
  
  // 5. 使用 promptAsync 发送恢复消息（v1 SDK 格式）
  debugLog(`session.idle: 恢复分析 sessionID=${sessionID} agent=${session.primaryAgent} elapsed=...`, sessionID);
  await opencodeClient.session.promptAsync({
    path: { id: sessionID },
    body: { parts: [{ type: "text" as const, text: RESUME_PROMPT }] },
  });
  recordResumeAttempt(sessionID);
}
```

#### 步骤 5: 确认 createdAt 追踪已存在

- **文件**: `.opencode/plugins/security-analysis.ts`
- **预估行数**: 0 行（确认现有实现，可能不需要改动）
- **验证点**: `SessionData.createdAt` 字段在 `doEnsureSession` 中已正确设置为 `Date.now()`，且在 `chat.message` 中已正确保留。确认无遗漏。
- **依赖**: 无

#### 步骤 6: 添加恢复上下文注入到 compacting hook

- **文件**: `.opencode/plugins/security-analysis.ts`
- **预估行数**: ~10 行
- **验证点**: 压缩恢复提示中包含"这是自动恢复的分析会话，如果分析尚未完成请继续分析"的说明，避免压缩后 AI 以为用户已经放弃
- **依赖**: 无

#### 步骤 7: 更新知识库文档

- **文件**: `.opencode/binary-analysis/knowledge-base/opencode-plugin-hooks-lifecycle.md`
- **预估行数**: ~20 行
- **验证点**: 文档中记录了 `session.idle` 恢复机制的行为
- **依赖**: 步骤 4

### 3.2 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `.opencode/plugins/security-analysis.ts` | 修改 | ~160 行 |
| `.opencode/binary-analysis/scripts/create_task_dir.py` | 修改 | ~25 行（新增 `_init_persistence` 函数 + `--max-duration` 参数） |
| `.opencode/binary-analysis/knowledge-base/opencode-plugin-hooks-lifecycle.md` | 修改 | ~15 行 |
| `.opencode/binary-analysis/knowledge-base/task-initialization.md` | 修改 | ~15 行（新增 `--max-duration` 参数说明） |

### 3.3 编码规则

1. `event` hook 是 fire-and-forget，不能阻塞宿主流程。恢复消息发送用 `promptAsync`（异步，不等待完整响应）
2. 恢复提示消息应该简洁直接，不要包含冗长的系统提示
3. 持续时间计算使用 `Date.now() - session.createdAt`
4. 所有恢复动作前后必须写日志（`debugLog`）
5. 子 session 判断：复用 `requireSessionWithPrimary` 函数。子 session 的 `agentName` 通常为 "general" 等非 PRIMARY_AGENT 名，会被 `PRIMARY_AGENTS.includes()` 过滤。无需额外检查 `parentID`。
6. `promptAsync` 调用必须使用 v1 SDK 格式: `{ path: { id: sessionID }, body: { parts: [{ type: "text" as const, text: RESUME_PROMPT }] } }`。注意 v1 和 v2 SDK 的参数格式不同，v1 用 `path` + `body`，v2 用扁平 `sessionID` + `parts`
7. `security-analysis-evolve` Agent 虽然在 `PRIMARY_AGENTS` 列表中，但它是进化 Agent 不做分析工作，应排除恢复

## §4 验收标准

### 4.1 功能验收

- [ ] 安全分析 Agent 的主 session 空闲后，Plugin 自动发送恢复消息
- [ ] 恢复消息内容为："你之前的分析是否已经完成了？如果已经完成，请直接输出最终结论。如果尚未完成，请自主继续分析，不要停下来向用户提问。"
- [ ] 子 session（Task 工具创建的子 Agent session，如 "general"）不触发恢复
- [ ] security-analysis-evolve Agent 不触发恢复（进化 Agent 不做分析工作）
- [ ] 无 taskDir 的 session 不触发恢复（简单问答，不是正式分析任务）
- [ ] 超过最大持续时间（默认 6 小时）后不再恢复
- [ ] 任务目录下存在 `.persistence.json` 文件时，使用 `max_duration_hours` 字段指定的持续时间
- [ ] `.persistence.json` 文件格式为 JSON，包含 `max_duration_hours`、`resume_count`、`last_resume_at` 三个字段
- [ ] 每次成功发送恢复消息后，`.persistence.json` 的 `resume_count` +1，`last_resume_at` 更新为当前时间
- [ ] `promptAsync` 调用使用 v1 SDK 格式：`{ path: { id: sessionID }, body: { parts: [{ type: "text", text: RESUME_PROMPT }] } }`

### 4.2 回归验收

- [ ] 原有 Plugin 功能不受影响：环境注入、占位符展开、session 管理、compact hook
- [ ] 原有工具执行拦截仍然正常工作
- [ ] 非 PRIMARY_AGENT 的 session 不会触发恢复

### 4.3 架构验收

- [ ] 新增代码主要在 `security-analysis.ts` 中，`create_task_dir.py` 新增了 `--max-duration` 参数和 `_init_persistence` 函数
- [ ] 恢复逻辑仅在 `event` hook 中，没有引入新 hook
- [ ] 日志通过现有 `debugLog` 机制输出
- [ ] 没有新增独立文件

## §5 与现有需求文档的关系

- `2026-05-23-enforce-no-ask-user.md`：已在 prompt 层面强调"不要问用户"，本需求从 Plugin 层面补充自动恢复机制
- `2026-05-24-autonomous-exploration.md`：定义了自主探索规则，本需求确保这些规则在 LLM 自然停止后仍能继续执行
- `2026-05-26-plugin-inject-python-cmd.md`：Plugin 基础设施改进，本需求基于此插件架构