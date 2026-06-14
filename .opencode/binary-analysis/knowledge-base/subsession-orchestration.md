# OpenCode Plugin 子会话编排模式

> 本文档为 security-analysis-evolve Agent 的 OpenCode Plugin 开发参考。
> 聚焦 Plugin custom tool 中的子会话编排：如何正确创建、发送任务、等待完成、获取结果。
> 不依赖主 prompt 上下文即可理解。

---

## 1. 核心规则：用 promptAsync，不用 prompt

| API | 行为 | 适用场景 |
|-----|------|---------|
| `session.prompt` | **同步阻塞**：HTTP 请求等到子 Agent 完成全部工作后才返回 | ❌ **禁止在 Plugin custom tool 中使用** |
| `session.promptAsync` | **异步立即返回**：HTTP 请求立即返回，子 Agent 在后台执行 | ✅ Plugin custom tool 的子会话编排必须用这个 |

**为什么不能用 `session.prompt`**：

Plugin custom tool 的 `execute` 函数在 tool 执行上下文中运行。调用 `session.prompt` 会阻塞 tool execute，HTTP 请求一直挂着等待子 Agent 的 loop 退出。如果子 Agent 执行时间长（如分析任务），tool execute 会被卡死，最终被 OpenCode 框架强杀。

**参考实现**：oh-my-openagent `src/tools/delegate-task/` 使用 `promptAsync` + poll 模式，已在生产环境验证。

---

## 2. 正确的编排流程

```
步骤 1: session.create({ parentID })      → 创建子会话
步骤 2: session.promptAsync({ ... })       → 异步发送任务（立即返回）
步骤 3: 轮询 session.status()              → 每 2s 检查状态
        直到 status 为 idle 或超时
步骤 4: session.messages({ id })            → 读取子 Agent 输出
步骤 5: session.abort({ id })               → 超时或取消时清理
```

---

## 3. 关键 API

### 3.1 promptAsync

```typescript
await client.session.promptAsync({
  path: { id: subSessionID },
  body: {
    agent: "web-analysis",
    system: systemContent,
    parts: [{ type: "text", text: taskPrompt }],
  },
});
// 立即返回，不等待子 Agent 完成
```

### 3.2 status

```typescript
const result = await client.session.status();
// 返回: { data: { [sessionID]: { type: "busy" | "idle" } } }
```

### 3.3 messages

```typescript
const result = await client.session.messages({
  path: { id: subSessionID },
});
// 返回: { data: [{ info: { role, finish, id, time }, parts: [{ type, text }] }] }
```

### 3.4 abort

```typescript
await client.session.abort({
  path: { id: subSessionID },
});
// 强制终止子会话
```

---

## 4. 子会话完成判断

从 messages 列表中判断子会话是否已完成：

```
1. 找到最后一个 assistant message
2. assistant 没有 finish 字段 → 未完成
3. assistant.finish 为 "tool-calls" 或 "unknown" → 未完成（还有工具调用）
4. assistant 有 pending tool parts（type 为 "tool"/"tool_use"/"tool-call"）→ 未完成
5. 最后的 user.id >= assistant.id → 未完成
6. 其他 → 完成
```

注意：即使 `session.status()` 返回 idle，也必须通过 messages 确认完成，因为 idle 可能在 assistant 回复之前就返回。

---

## 5. 超时处理

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `POLL_INTERVAL_MS` | 2000 | 轮询间隔（固定） |
| `delegate_timeout_minutes` | 10 | 超时时间（分钟），通过 `~/bw-security-analysis/config.json` 配置 |

配置示例：

```json
{
  "delegate_timeout_minutes": 15
}
```

超时后必须调用 `session.abort()` 终止子会话，否则子 Agent 会变成孤儿进程继续消耗资源。

---

## 6. 错误处理

| 场景 | 处理 |
|------|------|
| promptAsync 返回 error | abort 子会话（子会话已创建但未启动，需清理）+ 返回错误 |
| 轮询超时 | abort 子会话 + 返回超时错误 |
| 父会话被取消 | 用 `context.abort`（AbortSignal）检测。先尝试获取消息，如果子会话恰好已完成则正常返回；否则 abort 子会话 + 返回取消错误 |
| messages 读取失败 | 重试几次，仍失败则 abort |
| 子 Agent 无文本输出 | 返回兜底信息（"未返回文本结果"） |

---

## 7. 与 OpenCode 原生 Task tool 的区别

| | 原生 Task tool (`src/tool/task.ts`) | Plugin custom tool |
|---|---|---|
| 调用方式 | 直接在 Effect runtime 内调用 | 通过 SDK HTTP API 调用 |
| 性能 | 更好（无 HTTP 开销） | 有 HTTP 轮询开销 |
| 可用性 | 仅 OpenCode 内部 | Plugin 可用 |
| 建议 | 如果能复用原生 Task tool，优先使用 | Plugin 中只能用 SDK API |

---

## 8. 常见陷阱

| 陷阱 | 说明 |
|------|------|
| 在 tool execute 中用 `session.prompt` | 会导致 tool execute 被 HTTP 响应阻塞，最终被框架强杀 |
| 不检查 messages 只看 status | idle 不代表完成，可能在 assistant 回复之前就变成 idle |
| 不设超时 | 子 Agent 可能无限循环，必须设超时上限 |
| 超时后不 abort | 子 Agent 变成孤儿，继续消耗 LLM token |
| 忘记在 finally 中清理 sessions Map | 子会话的 hook 处理会残留 |
| 用 `sessions.get(parentID)` 检测取消 | sessions Map 由 Plugin 自管理，框架强杀 tool 时不会清理条目，检查永远不触发。必须用 `context.abort`（AbortSignal） |
