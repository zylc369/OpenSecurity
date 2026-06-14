# OpenCode Agent 格式规范

> 基于 oh-my-openagent（vendor/oh-my-openagent）源码提取。
> **警告**: OpenCode Agent 格式可能随版本变化。

## Agent 文件格式

### Markdown 格式（推荐）

放在 `.opencode/agents/` 目录下，使用 YAML frontmatter：

```markdown
---
name: my-agent          # 可选，默认取文件名（不含 .md）
description: 做某件事    # 可选，Agent 描述
model: claude-opus-4    # 可选，模型名称（会自动映射到 provider/model 格式）
tools: Read,Write,Bash  # 可选，逗号分隔的工具列表
mode: subagent          # 可选，默认 "subagent"
---

系统提示内容写在这里。这就是 Agent 的完整 system prompt。
```

### JSON 格式

```json
{
  "name": "my-agent",
  "description": "做某件事",
  "model": "claude-opus-4",
  "tools": ["Read", "Write", "Bash"],
  "mode": "subagent",
  "prompt": "系统提示内容"
}
```

---

## Frontmatter 字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `name` | `string` | 否 | Agent 名称，默认取文件名（不含 `.md`） |
| `description` | `string` | 否 | Agent 描述，用于 UI 展示和 Agent 选择 |
| `model` | `string` | 否 | 模型名称（如 `claude-opus-4`），自动映射 |
| `tools` | `string` | 否 | 逗号分隔的工具白名单（如 `Read,Write,Bash`） |
| `mode` | `string` | 否 | `"primary"` / `"subagent"` / `"all"`，默认 `"subagent"` |

---

## Mode 说明

| Mode | 行为 | 适用场景 |
|------|------|---------|
| `primary` | 遵守用户 UI 中选择的模型 | 用户直接交互的主 Agent |
| `subagent` | 使用自己的 fallback chain，忽略 UI 模型选择 | 后台自动调度的子 Agent |
| `all` | 两种场景都可用 | 通用型 Agent |

**BinaryAnalysis Agent 使用 `mode: primary`**，因为用户直接与此 Agent 交互。

---

## Agent 搜索路径（优先级从高到低）

| 优先级 | 路径 | 说明 |
|--------|------|------|
| 1 | `$CLAUDE_CONFIG_DIR/agents/*.md` | Claude Code 用户级 Agent |
| 2 | `<project>/.claude/agents/*.md` | Claude Code 项目级 Agent |
| 3 | `$OPENCODE_CONFIG_DIR/agents/*.md` | OpenCode 全局 Agent |
| 4 | `<project>/.opencode/agents/*.md` | **OpenCode 项目级 Agent**（BinaryAnalysis 用这个） |
| 5 | `opencode.json` 内联定义 | 配置文件中的 agents 字段 |
| 6 | `opencode.json` 的 `agent_definitions` 路径 | 配置文件指向的外部文件 |

**同名 Agent**: 先发现的优先（first-seen wins）。

---

## Agent 配置覆盖（通过 oh-my-opencode.jsonc）

可以在 `.opencode/oh-my-opencode.jsonc` 中覆盖 Agent 配置：

```jsonc
{
  "agents": {
    "binary-analysis": {
      "model": "claude-opus-4",
      "tools": { "Read": true, "Write": true, "Bash": true },
      "temperature": 0.7,
      "prompt_append": "附加提示内容",
      "disable": false
    }
  }
}
```

### 可覆盖字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `model` | `string` | 模型名称（deprecated，推荐用 category） |
| `category` | `string` | 模型分类 |
| `fallback_models` | `string \| object[]` | 回退模型链 |
| `variant` | `string` | 模型变体 |
| `skills` | `string[]` | 可用技能 |
| `temperature` | `number` | 温度 |
| `top_p` | `number` | Top-P |
| `prompt` | `string` | 完整替换系统提示 |
| `prompt_append` | `string` | 追加到系统提示末尾（支持 `file://` URI） |
| `tools` | `Record<string, boolean>` | 工具启用/禁用 |
| `disable` | `boolean` | 禁用 Agent |
| `description` | `string` | 覆盖描述 |
| `mode` | `string` | 覆盖模式 |
| `color` | `string` | UI 颜色（hex） |
| `maxTokens` | `number` | 最大输出 token |
| `thinking` | `object` | 思考模式（type + budgetTokens） |
| `reasoningEffort` | `string` | 推理努力程度 |
| `textVerbosity` | `string` | 文本详细度 |

---

## 限制

- **Agent 不支持 `!` 反引号动态注入**（不同于 Command）— 动态信息必须通过 Plugin 注入
- **Agent prompt 不支持模板变量**（如 `$ARGUMENTS`）— 只有 Command 支持
- **Agent 不能直接访问文件系统** — 只能通过工具（Read/Write）

---

## BinaryAnalysis Agent 的实现

- **文件**: `.opencode/agents/binary-analysis.md`
- **Mode**: `primary`（用户直接交互）
- **动态信息**: 通过 Plugin（`security-analysis.ts`）的 `system.transform` hook 注入环境信息
- **规则持久化**: 通过 Plugin 的 `compacting` hook 在压缩时注入关键规则

**来源文件**:
- `vendor/oh-my-openagent/src/features/claude-code-agent-loader/loader.ts` — Agent 加载逻辑
- `vendor/oh-my-openagent/src/features/claude-code-agent-loader/agent-definitions-loader.ts` — Markdown 解析
- `vendor/oh-my-openagent/src/shared/frontmatter.ts` — Frontmatter 解析
- `vendor/oh-my-openagent/src/config/schema/agent-overrides.ts` — 配置覆盖 schema
