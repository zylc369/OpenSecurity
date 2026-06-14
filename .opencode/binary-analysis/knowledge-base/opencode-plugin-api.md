# OpenCode Plugin API 参考

> 基于 oh-my-openagent（vendor/oh-my-openagent）源码提取。
> **警告**: OpenCode Plugin API 不是公开文档，可能随版本变化。每次升级 OpenCode 后应对比验证。

## Plugin 入口格式

```javascript
// .opencode/plugins/xxx.mjs (ESM)
export const MyPlugin = async ({ directory, client, project }) => {
  return {
    // hooks...
  };
};
```

- 文件放在 `.opencode/plugins/` 目录下，OpenCode 自动加载
- 使用 `.mjs` 扩展名确保 ESM
- 导出一个具名函数，返回 hooks 对象

### 输入参数

| 字段 | 类型 | 说明 |
|------|------|------|
| `directory` | `string` | 项目根目录路径 |
| `client` | `object` | OpenCode 客户端 API（session 管理、tui 等） |

> 注：完整参数列表来自 `@opencode-ai/plugin` 外部包，无法从 oh-my-openagent 源码确认。上面仅列出已验证的字段。

---

## 可用 Hooks

### `experimental.chat.system.transform`

**触发时机**: 每轮对话发送给模型前

**签名**:
```typescript
async (input: {
  sessionID?: string;
  model: { id: string; providerID: string; [key: string]: unknown };
}, output: {
  system: string[];  // ← 是 string 数组，不是 string！
}) => Promise<void>
```

**用途**: 修改系统提示（system prompt）。通过 `output.system.push(content)` 注入内容。

**注意**: oh-my-openagent 当前此 hook 是 no-op（空实现），说明此 hook 可用但内部未使用。

**来源**: `vendor/oh-my-openagent/src/plugin/system-transform.ts`

---

### `experimental.session.compacting`

**触发时机**: 上下文压缩前

**签名**:
```typescript
async (input: {
  sessionID: string;
}, output: {
  context: string[];  // ← 是 string 数组
}) => Promise<void>
```

**用途**: 在压缩时注入需要保留的上下文信息。通过 `output.context.push(content)` 注入。

**三阶段模式**（oh-my-openagent 的完整实现）:
1. **capture（压缩前）**: 保存 session 状态快照
2. **inject（压缩时）**: 向 `output.context` 注入结构化提示
3. **restore（压缩后）**: 通过 `event` hook 的 `session.compacted` 事件恢复状态

**来源**: `vendor/oh-my-openagent/src/index.ts:113-127`

---

### `experimental.chat.messages.transform`

**触发时机**: 消息历史发送给模型前

**签名**:
```typescript
async (input: Record<string, never>, output: {
  messages: Array<{ info: Message; parts: Part[] }>;
}) => Promise<void>
```

**用途**: 修改消息历史。oh-my-openagent 用此 hook 注入上下文（ContextCollector）、验证 thinking block、验证 tool pair。

**来源**: `vendor/oh-my-openagent/src/plugin/messages-transform.ts`

---

### `chat.message`

**触发时机**: 用户发送消息时

**签名**:
```typescript
async (input: {
  sessionID: string;
  agent?: string;
  model?: { providerID: string; modelID: string };
}, output: {
  message: Record<string, unknown>;
  parts: Array<{ type: string; text?: string }>;
}) => Promise<void>
```

**用途**: 拦截用户消息、修改模型选择、关键词检测。

**来源**: `vendor/oh-my-openagent/src/plugin/chat-message.ts`

---

### `event`

**触发时机**: session 状态变化时

**签名**:
```typescript
async (input: {
  event: {
    type: string;
    properties?: Record<string, unknown>;
  };
}) => Promise<void>
```

**事件类型**:

| 事件 | 说明 | properties 关键字段 |
|------|------|-------------------|
| `session.created` | session 创建 | `sessionID`, `info.id/title/parentID` |
| `session.deleted` | session 删除 | `sessionID`, `info.id` |
| `session.idle` | session 空闲 | `sessionID` |
| `session.compacted` | session 压缩完成 | `sessionID` |
| `session.error` | session 错误 | `sessionID`, `error`, `messageID` |
| `session.status` | 状态变更（retry 等） | `sessionID`, `status.type/message/attempt` |
| `message.updated` | 消息更新 | `info.sessionID/role/agent/id/providerID/modelID` |
| `message.removed` | 消息删除 | `sessionID`, `messageID` |
| `message.part.delta` | 消息部分增量 | `sessionID`, `messageID`, `field`, `delta` |
| `message.part.updated` | 消息部分更新 | `part.sessionID/messageID/type/text` |

**来源**: `vendor/oh-my-openagent/src/plugin/event.ts`

---

### `chat.params`

**触发时机**: 构建请求参数时

**签名**:
```typescript
async (input: unknown, output: unknown) => Promise<void>
```

**用途**: 修改 temperature、topP、maxOutputTokens、reasoning effort 等参数。

---

### `chat.headers`

**触发时机**: 构建 HTTP 请求头时

**用途**: 注入自定义 HTTP 头（如 x-initiator）。

---

### `tool.execute.before`

**触发时机**: 工具执行前

**签名**:
```typescript
async (input: { tool: string; args: Record<string, unknown> }, output: {
  // 可修改工具参数或阻止执行
}) => Promise<void>
```

**用途**: 工具调用前的拦截（文件保护、参数校验、上下文注入等）。

---

### `tool.execute.after`

**触发时机**: 工具执行后

**用途**: 工具调用后的处理（输出截断、格式化、元数据提取等）。

---

### `command.execute.before`

**触发时机**: 斜杠命令执行前

**用途**: 拦截特定命令（如 /ralph-loop、/start-work）。

---

### `config`

**触发时机**: 配置加载时

**用途**: 修改 OpenCode 配置（agent、tool、MCP、command 等）。

---

## 安全创建模式

oh-my-openagent 使用 `safeHookCreation`（默认 true）: 每个 hook 创建时包裹 try/catch，创建失败返回 null 而不是崩溃整个 plugin。

**建议**: 在 BinaryAnalysis Plugin 中不需要此模式（只有一个 plugin，不需要防御性编程），但了解此机制有助于排查问题。

---

## 快速参考

| Hook | output 类型 | 注入方法 |
|------|-----------|---------|
| `system.transform` | `{ system: string[] }` | `output.system.push(text)` |
| `compacting` | `{ context: string[] }` | `output.context.push(text)` |
| `messages.transform` | `{ messages: [...] }` | 修改 messages 数组 |
| `chat.message` | `{ message, parts }` | 修改 message/parts |
| `event` | 无 output | 只读 input.event |

**常见错误**: 把 `output.system` 当作 string 而非 string[]。正确: `output.system.push()`，错误: `output.system += ...`。
