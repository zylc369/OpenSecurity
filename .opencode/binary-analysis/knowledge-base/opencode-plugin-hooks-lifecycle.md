# OpenCode Plugin Hooks 生命周期与执行顺序

> 基于 OpenCode 源码 (`opencode/packages/opencode/src/`) 分析。
> **警告**: 非公开 API，随版本变化。升级后应对比验证。

## 一、完整时序图

### 主 Session（用户新建对话 → 选择 Agent → 发送消息）

```
用户点击 "New Session"
    │
    ▼
Session.create()                           ← opencode/src/session/index.ts:404
    │
    ├── SyncEvent.run(Event.Created)        ← 发布到 ProjectBus
    │       │
    │       ▼
    │   [Plugin] event hook                 ← fire-and-forget（不 await）
    │   event.type === "session.created"
    │   properties: { sessionID, info: { id, parentID, title, ... } }
    │
    ▼
API 返回 session info（UI 显示空对话）

    ⋮  用户输入消息（秒~分钟延迟）
    ⋮

用户发送消息
    │
    ▼
SessionPrompt.prompt()                     ← opencode/src/session/prompt.ts:1266
    │
    ├── createUserMessage()
    │       │
    │       ▼
    │   [Plugin] chat.message hook          ← AWAITED（宿主等待完成）
    │   input: { sessionID, agent, model, messageID }
    │   output: { message, parts }
    │
    ▼
runLoop() while 循环（每轮 tool call 都会循环）
    │
    ├── [Plugin] experimental.chat.messages.transform    ← AWAITED
    │   output: { messages: [...] }
    │
    ├── handle.process() → LLM.stream()                ← opencode/src/session/llm.ts:102
    │       │
    │       ├── const system: string[] = []             ← 每次重建，不累积！
    │       │   system[0] = agent.prompt + input.system + user.system
    │       │
    │       ├── [Plugin] experimental.chat.system.transform  ← AWAITED
    │       │   output: { system }  ← 就是上面新建的数组
    │       │
    │       ├── [Plugin] chat.params                         ← AWAITED
    │       ├── [Plugin] chat.headers                       ← AWAITED
    │       │
    │       ▼
    │   发送 LLM HTTP 请求
    │
    ├── 处理 LLM 响应
    │   ├── tool call → 执行工具
    │   │   ├── [Plugin] tool.execute.before    ← AWAITED
    │   │   ├── 执行工具
    │   │   └── [Plugin] tool.execute.after     ← AWAITED
    │   └── 纯文本 → 返回给用户
    │
    └── 回到循环顶部（如有 tool call）
```

### 子 Session（Task 工具创建）

```
[Plugin] 调用 Task 工具
    │
    ▼
sync-task.ts: createSyncSession()          ← await API 调用
    │
    ├── [宿主] Session.create({ parentID: "..." })
    │       │
    │       ├── SyncEvent.run(Event.Created)
    │       │       │
    │       │       ▼
    │       │   [Plugin] event hook          ← fire-and-forget
    │       │   properties.info.parentID !== undefined
    │       │
    │       ▼
    │   API 返回 session info
    │
    ├── setSessionAgent(sessionID, agentToUse)
    ├── onSyncSessionCreated() 回调
    ├── await new Promise(r => setTimeout(r, 200))   ← 200ms 等待
    │
    ▼
sync-task.ts: sendSyncPrompt()             ← await API 调用
    │
    ▼
[宿主] SessionPrompt.prompt()
    │
    ├── [Plugin] chat.message               ← AWAITED
    │   input.agent = 子 agent 名（如 "general"）
    │
    ▼
runLoop()（同主 session）
```

## 二、关键时序规则

### 规则 1：`session.created` 先于 `chat.message`

无论主/子 session，`session.created` 总是先触发（因为 session 必须先存在才能发消息）。

但 `session.created` 是 **fire-and-forget**（宿主不等待插件处理完），而 `chat.message` 是 **awaited**。

**对子 session 的竞态风险**：
- `sync-task.ts` 在 `createSyncSession` 返回后有 200ms 延迟（`onSyncSessionCreated` 回调）
- 这 200ms 确保 `session.created` 事件在 Effect runtime 中被消费后再触发 `chat.message`
- **生产环境安全**；但如果跳过 200ms 延迟，理论上可能竞态

### 规则 2：`output.system` 每次重建

```typescript
// opencode/src/session/llm.ts:102
const system: string[] = []  // 每次 LLM 请求都新建空数组
```

- 第 N 次 `system.transform` 的 `output.system` **不包含**第 1~N-1 次 push 的内容
- 必须每次都 push 需要注入的内容（如环境信息）
- 这是 LLM API 的本质：每次请求都是独立的，系统提示不会自动累积

### 规则 3：Awaited vs Fire-and-forget

| Hook | 是否 Awaited | 影响 |
|------|-------------|------|
| `event`（含所有 session.* 事件） | **否** | 宿主不等待插件处理完就继续 |
| `chat.message` | **是** | 宿主等待所有插件处理完 |
| `experimental.chat.messages.transform` | **是** | 同上 |
| `experimental.chat.system.transform` | **是** | 同上 |
| `experimental.session.compacting` | **是** | 同上 |
| `chat.params` | **是** | 同上 |
| `chat.headers` | **是** | 同上 |
| `tool.execute.before` | **是** | 同上 |
| `tool.execute.after` | **是** | 同上 |

**影响**：
- `event` hook 中不能做需要阻塞宿主流程的操作
- 其他 hook 中可以安全地修改 output，宿主会等待修改完成

### 规则 4：runLoop 循环中的 Hook 顺序

每次 LLM 请求（包括 tool call 后的后续请求）都完整执行：
```
messages.transform → system.transform → chat.params → chat.headers → LLM 请求
```

**tool call 链**中，每次循环都会触发 `system.transform`，所以环境信息会被重复注入（但这是正确行为，因为 `output.system` 每次重建）。

## 三、Session 生命周期事件

```
session.created          session.compacted (可能多次)         session.deleted
     │                        │                                   │
     ▼                        ▼                                   ▼
 初始化状态              触发 compacting hook              清理所有状态
 设置 createdAt          注入保留信息                      删除 Map 条目
 子 session 继承         设置 session.compacted            删除 task session
                         事件（用于恢复）
```

### `session.created` 事件 properties 结构

```typescript
{
  sessionID: string,
  info: {
    id: string,
    parentID?: string,    // 子 session 时存在
    title?: string,
    // ... 其他 Session 字段
  }
}
```

**提取 sessionID 的正确方式**：
```typescript
const sessionID = props.info?.id ?? props.sessionID;
```
优先用 `props.info.id`（更权威），回退到 `props.sessionID`（`session.compacted` 等事件没有 `info`）。

### `session.deleted` 会级联

OpenCode 删除 session 时递归删除所有子 session，每个子 session 都会触发独立的 `session.deleted` 事件。

## 四、常见陷阱

### 陷阱 1：`event` hook 中依赖尚未就绪的状态

`session.created` 是 fire-and-forget，可能与其他 hook 并发执行。如果在 `session.created` 中设置状态，不要假设后续 hook 一定能读到。

**安全做法**：`session.created` 只做状态初始化（设置 Map 条目），不做需要顺序保证的逻辑。

### 陷阱 2：以为 `output.system` 会累积

在 `system.transform` 中 push 的内容只存在于当前请求。下次请求需要重新 push。

### 陷阱 3：子 session 的 agent 与 primaryAgent 混淆

- `sessionAgentMap` 记录的是当前 session 实际使用的 agent（可能是 `"general"` 等子 agent）
- `sessionPrimaryAgent` 记录的是当前 session 所属的主 agent（从父 session 继承）
- 日志路由应使用 `sessionPrimaryAgent`，工具过滤应使用 `sessionAgentMap`

### 陷阱 4：`compacting` vs `compacted`

- `experimental.session.compacting`（hook）：压缩**前**触发，可注入保留信息到 `output.context`
- `session.compacted`（event）：压缩**后**触发，只读，可用于状态恢复

### 陷阱 5：`session.idle` 恢复机制

- `session.idle` 事件在 session 空闲时触发，Plugin 利用此事件自动恢复安全分析 Agent 的主 session
- 恢复条件（全部满足才触发恢复）:
  1. session.idle 事件触发
  2. `primaryAgent` 属于 PRIMARY_AGENTS（排除子 session）
  3. `primaryAgent` 不是 security-analysis-evolve（进化 Agent 不做分析工作）
  4. 该 session 有对应的 `$TASK_DIR`（无 taskDir = 简单问答，不需要恢复）
  5. 未超过最大持续时间
- 恢复方式：通过 `client.session.promptAsync()` 发送恢复消息
- 选择 `promptAsync` 而非 `prompt` 的原因：event hook 是 fire-and-forget，`promptAsync` 立即返回不阻塞宿主；`prompt` 流式消费响应会阻塞 event hook
- **v1 SDK 调用格式**: `{ path: { id: sessionID }, body: { parts: [{ type: "text" as const, text: "..." }] } }`（与 v2 SDK 的扁平格式 `{ sessionID, parts: [...] }` 不同）
- 持续性状态文件：`$TASK_DIR/.persistence.json`，格式 `{"max_duration_hours": 6, "resume_count": 3, "last_resume_at": "..."}`
  - 由 `create_task_dir.py` 在任务初始化时创建（默认 6 小时，resume_count=0）
  - 每次成功恢复后 resume_count +1，last_resume_at 更新为当前时间
  - 用户或 Agent 可修改 `max_duration_hours` 自定义最大持续时间（0 < hours ≤ 24）

## 五、Plugin 数据架构模式

### 推荐：多 Map 模式

```typescript
const sessionStates = new Map<string, SessionState>();      // 生命周期追踪
const sessionAgentMap = new Map<string, string>();           // 当前 agent 名
const sessionPrimaryAgent = new Map<string, string>();       // 主 agent 名（日志路由用）
```

### 设置时机

| Map | 设置位置 | 设置时机 |
|-----|---------|---------|
| `primaryAgent` | `chat.message` | 主 session 首次出现 PRIMARY_AGENTS 时 |
| `primaryAgent` | `ensureSession` | 子 session 从父链递归继承（通过 client API 查询 parentID） |
| `agentName` | `chat.message` | 每条消息时更新 |

> 注意：旧版本在 `event: session.created` 中做继承，当前版本改为 `ensureSession` 按需懒恢复（插件重启后也能恢复）。

### 清理时机

`event: session.deleted` 中统一清理所有 Map 条目 + task session 文件。
