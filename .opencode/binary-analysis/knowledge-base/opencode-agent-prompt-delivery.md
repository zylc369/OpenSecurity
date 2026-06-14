# Agent Prompt 投递机制：从 MD 文件到 LLM 请求

> 基于 OpenCode 源码分析（`vendor/opencode/packages/opencode/src/`）。
> **警告**: 非公开 API，随版本变化。升级后应对比验证。

## 核心结论

**Agent MD 文件的正文内容在每次 LLM 请求时都作为 system prompt 发送。**

这不是一次性发送，而是 agentic loop 的每一步（包括 tool call 后的后续请求）都会完整发送。
因此 agent prompt 的长度直接影响 token 开销，prompt 瘦身不是优化而是必须。

---

## 完整调用链

### 第 1 步：MD 文件 → agent.prompt

**源码**: `src/config/agent.ts` `load()` 函数

```
.opencode/agents/binary-analysis.md
    │
    ▼  Glob.scan("{agent,agents}/**/*.md")
    │
    ▼  ConfigMarkdown.parse(item)
    │  → md.data = frontmatter 字段（model, mode, description 等）
    │  → md.content = 正文内容
    │
    ▼  config = { name: "binary-analysis", ...md.data, prompt: md.content.trim() }
```

**要点**：
- 正文内容被存为 `agent.prompt` 字段
- 如果同名 agent 已存在（如内置 agent），`prompt` 字段会覆盖默认值
- 扫描路径模式：`.opencode/agent/` 或 `.opencode/agents/` 下的所有 `.md` 文件

### 第 2 步：Agent 注册

**源码**: `src/agent/agent.ts` 第 234-261 行

```typescript
for (const [key, value] of Object.entries(cfg.agent ?? {})) {
    if (value.disable) { delete agents[key]; continue }
    let item = agents[key]
    if (!item) item = agents[key] = { name: key, mode: "all", ... }
    item.prompt = value.prompt ?? item.prompt  // MD 正文覆盖
    // ... 其他字段合并
}
```

**要点**：
- 内置 agent（build, plan, general, explore 等）有默认 prompt
- 用户自定义 MD 文件的 prompt 会覆盖同名的内置 prompt
- 如果 agent 没有 prompt，则使用 provider 默认 prompt（如 anthropic.txt, gpt.txt）

### 第 3 步：Session runLoop 中组装 system 数组

**源码**: `src/session/prompt.ts` 第 1442-1462 行

每次 agentic loop 的 step 中：

```typescript
const [skills, env, instructions, modelMsgs] = yield* Effect.all([
    sys.skills(agent),                         // skills 描述（如果 agent 有 skill 权限）
    Effect.sync(() => sys.environment(model)), // 环境信息（模型ID/工作目录/平台/日期）
    instruction.system().pipe(Effect.orDie),   // AGENTS.md / CLAUDE.md 指令文件内容
    MessageV2.toModelMessagesEffect(msgs, model), // 对话历史
])
const system = [...env, ...instructions, ...(skills ? [skills] : [])]

yield* handle.process({
    user: lastUser,
    agent,        // ← 包含 agent.prompt（MD 正文）
    system,       // ← [env, instructions, skills]
    messages: modelMsgs,
    tools,
    model,
})
```

**要点**：
- `system` 数组包含环境信息、指令文件、skills
- `agent` 对象包含完整的 `agent.prompt`
- 这两者都被传入 `handle.process()`，最终到达 `llm.stream()`

### 第 4 步：LLM 中组装最终 system message（关键！）

**源码**: `src/session/llm.ts` 第 99-124 行

```typescript
const system: string[] = []
system.push(
    [
        // ① agent.prompt（来自 MD 文件）—— 优先于 provider 默认 prompt
        ...(input.agent.prompt ? [input.agent.prompt] : SystemPrompt.provider(input.model)),
        // ② 从 prompt.ts 传入的 system（env + instructions + skills）
        ...input.system,
        // ③ 用户消息级别的 system（PromptInput.system 字段）
        ...(input.user.system ? [input.user.system] : []),
    ]
        .filter((x) => x)
        .join("\n"),  // ①②③ 全部 join 成一个字符串作为 system[0]
)

// ④ Plugin system.transform hook 可以 push 更多内容到 system 数组
yield* plugin.trigger(
    "experimental.chat.system.transform",
    { sessionID: input.sessionID, model: input.model },
    { system },  // plugin 可以往 system 数组 push 新元素
)
```

**要点**：
- `system[0]` = agent prompt + env + instructions + skills（join 成一个字符串）
- `system[1]` = plugin transform push 的内容（如果有的话）
- agent prompt 有 prompt 时，**完全替代** provider 默认 prompt
- 优先级：agent prompt > provider 默认 prompt（anthropic.txt 等）

### 第 5 步：转为 LLM 消息并发送

**源码**: `src/session/llm.ts` 第 148-160 行

```typescript
messages = [
    ...system.map((x): ModelMessage => ({
        role: "system",
        content: x,
    })),
    ...input.messages,  // 对话历史
]
// → 传给 streamText() 发送 HTTP 请求
```

---

## 时序图（简化版）

```
用户发消息
    │
    ├─ chat.message hook（插件记录 agentName）
    │
    └─ runLoop while (true)
        │
        ├─ step N:
        │   ├─ 构建 system = [env, instructions, skills]
        │   ├─ handle.process({ agent, system, messages, tools })
        │   │    └─ llm.stream(streamInput)
        │   │         ├─ system[0] = agent.prompt + system + user.system  ← 每次！
        │   │         ├─ system.transform hook（插件可 push system[1]+）
        │   │         └─ messages = [system..., 对话历史...] → 发给 LLM
        │   │
        │   ├─ LLM 响应有 tool call → 执行工具 → continue 循环
        │   └─ LLM 响应 finish → break 循环
        │
        └─ 循环结束
```

---

## 对 Agent Prompt 设计的影响

### 1. Token 开销公式

```
单次请求 token ≈ agent.prompt + env + instructions + skills + plugin注入 + 对话历史
                 ↑────────── 你能控制的 ──────────↑   ↑── 插件控制 ──↑   ↑─ 系统控制 ─↑
```

agentic loop 通常 5-20 步，每步都发送完整 agent prompt：
```
总 prompt token ≈ 步数 × (agent.prompt + env + instructions + skills + plugin注入) + 对话历史
```

### 2. 瘦身的意义

- agent prompt 450 行限制不是随意设定，而是基于 token 预算
- 600 行 prompt × 20 步 = 12000 行重复发送
- 详细流程应该移到 knowledge-base，主 prompt 只保留核心规则和触发条件

### 3. 与 Plugin system.transform 的关系

| 内容 | 位置 | 发送频率 | 谁控制 |
|------|------|---------|--------|
| Agent MD 正文 | `system[0]` 前段 | 每次 | Agent prompt 作者 |
| env + instructions + skills | `system[0]` 后段 | 每次 | OpenCode 自动 |
| Plugin 注入 | `system[1]+` | 取决于插件逻辑 | Plugin 开发者 |

**system.transform hook 的作用**：往 `system` 数组追加元素（`system[1]`、`system[2]`...）。
插件可以做频率控制（如每 10 次请求注入一次），但 agent prompt 无法做频率控制——它焊死在 `system[0]` 里。

### 4. AGENTS.md 的双重发送

`instruction.system()` 读取的 AGENTS.md 内容会被加入 `input.system`（`system[0]` 后段），
所以 AGENTS.md 也是**每次请求都发送**。如果 AGENTS.md 和 agent prompt 有重复内容，就是浪费。

---

## 源码文件索引

| 文件 | 关键行 | 作用 |
|------|--------|------|
| `src/config/agent.ts` | `load()` 110-140 | MD 文件扫描和 prompt 提取 |
| `src/agent/agent.ts` | 234-261 | Agent 注册和 prompt 合并 |
| `src/session/prompt.ts` | 1442-1462 | runLoop 中组装 system 数组 |
| `src/session/llm.ts` | 99-124 | 最终 system message 组装 |
| `src/session/llm.ts` | 148-160 | 转为 LLM 消息格式 |
| `src/session/system.ts` | 19-33, 48-77 | Provider 默认 prompt 选择、env 信息 |
| `src/session/instruction.ts` | 163-177 | AGENTS.md/CLAUDE.md 内容读取 |
