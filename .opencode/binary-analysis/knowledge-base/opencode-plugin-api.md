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

> **注**: security-analysis.ts 未采用 restore 阶段——状态恢复由 compacting hook 在压缩前注入（分析状态保留 + TASK_DIR）+ system.transform 的 justCompacted 强制重注入环境信息；event hook 的 `session.compacted` 仅记录日志。

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

### 权限询问事件与自动回复（v1/v2）

权限询问产生时发布 `permission.asked`，被回复（用户点击或程序回复）后发布 `permission.replied`；v2 事件名为 `permission.v2.asked` / `permission.v2.replied`（字段重命名，见下表）。插件的 `event` hook 可收到这两组事件，与 agent 无关（所有会话生效）。

**事件字段对照**：

| 字段语义 | v1 `permission.asked` | v2 `permission.v2.asked` |
|---------|----------------------|--------------------------|
| 请求 ID | `id`（`per_` 前缀） | `id` |
| 会话 ID | `sessionID` | `sessionID` |
| 权限类型 | `permission`（`external_directory` / `edit` / `bash` 等） | `action` |
| 请求模式 | `patterns`（数组） | `resources` |
| 记住项 | `always` | `save` |
| 工具调用来源 | `tool: {messageID, callID}` | `source` |
| 元数据 | `metadata` | `metadata` |

**回复端点**：

| 端点 | body | message 反馈 |
|------|------|-------------|
| `POST /permission/{requestID}/reply`（推荐） | `{reply: "once"/"always"/"reject", message?}` | 支持 |
| `POST /session/{sessionID}/permissions/{permissionID}`（旧） | `{response: "once"/"always"/"reject"}` | 不支持 |

v1 SDK 注入 client 无 `permission` 命名空间，旧端点对应 SDK 方法 `client.postSessionIdPermissionsPermissionId({path: {id, permissionID}, body: {response}})`；新端点用同一 client 的 hey-api 底层方法调用（`client._client.post({url, headers, body})`——SDK 生成方法内部即调它，baseUrl/认证/拦截器统一复用，比裸 fetch 更符合请求收口）。v2 端点：`POST /api/session/{sessionID}/permission/{requestID}/reply`，body `{reply, message?}`（v2 SDK 面 `client.permission.reply({requestID, reply, message})`）。

**message 反馈机制**：`reply: "reject"` 携带 `message` 时，被拒工具的错误结果变为 `The user rejected permission to use this specific tool call with the following feedback: <message>`；模型读到反馈后继续执行（不中断会话、不创建新消息）。不带 `message` 则为通用拒绝文案。

**未生成端点的统一调用方式**：插件 input 注入的 client 是 hey-api 生成客户端，底层方法面对所有端点可用——`client._client.post({url: "/permission/{id}/reply", headers: {"Content-Type": "application/json"}, body: {...}})`；返回 `{data, error, request, response}`（默认不 throw，按 `response.status` 判定; 200/404 语义见上文）。`_client` 还有 `get/put/delete/request/buildUrl/getConfig` 等方法（hey-api 公开运行时面）。不要在插件里裸 fetch opencode server——绕开 client 的 baseUrl/认证配置，破坏请求收口。

**⚠ `permission.ask` plugin hook 未接线**：`Hooks` 类型里有 `"permission.ask"` 定义，但运行时无触发点（1.18.32 与 dev 最新版均无）——权限拦截与自动回复必须走「事件 + reply 端点」路径，不要依赖该 hook。

**bash 工具 external_directory 触发范围**：bash 命令的 `external_directory` 询问只检查 **workdir** 与**特定命令的参数路径**，其余命令（如 `ls`、`find`）访问外部路径不触发：

- **workdir 在工作区外** → 触发（无论命令内容）。
- **以下命令解析参数路径**（`realpath` 解析后在工作区外 → 触发）：`cd`、`rm`、`cp`、`mv`、`mkdir`、`touch`、`chmod`、`chown`、`cat`。
- 触发时 pattern 为 `父目录/*`（`always` 同）——按目录粒度询问。
- 命令解析器只扫描命令行静态路径，脚本文件内部访问不扫描（`python script.py` 命令行无外部路径即不触发，脚本内 `open("/outside/file")` 正常执行）。
- 需要稳定触发询问做测试时：用 `cat <外部文件>` 或把 `workdir` 设为外部目录；`ls <外部目录>` 不触发。

---

### `chat.params`

**触发时机**: 构建请求参数时

**签名**:
```typescript
async (input: unknown, output: unknown) => Promise<void>
```

**用途**: 修改 temperature、topP、maxOutputTokens、reasoning effort 等参数。

**output.options 可修改**: options 是 merge(provider 基础项, model.options, agent.options, variant) 的结果——agent frontmatter 的未知字段会透传进来（详见 `$AGENT_DIR/knowledge-base/opencode-references.md` 的"agent frontmatter 未知字段透传"节）; hook 内 `delete output.options["<字段>"]` 在请求发出前生效。

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
