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

## description 是唯一路由层（写 agent 的硬要求）

OpenCode 每次请求都会把所有 `mode` 不为 `primary` 的 agent（即 `mode: all` 与 `mode: subagent`）的 `description` 注入 Task 工具说明（格式 `- 名称: description`；缺 description 时替换为"仅限手动调用"文案）。**主 agent 只能看到 description，看不到正文**——因此：

1. description 必须包含：**做什么 + 为什么这么做（避免什么损失）+ 最终目的（拿到什么结果）+ 何时主动委派（明确触发条件）+ 范围/排除 + 必须传什么/返回什么**——调用方据此判断这个委派何时值得发起、能拿到什么。输入契约写在正文里等于没写（主 agent 读不到）。
2. 想获得更主动的委派，使用明确的触发句式（如"卡壳时主动委派：同一方向连续失败≥5 次…"）。
3. 单行、不出现 `|` 字符——description 会被渲染进"可委派 Agent"表格单元格，多行或竖线会破坏表格。
4. 同一原则适用于 skill description 与 MCP 工具 description——三者都是模型的调用路由层（模型据其决定何时调用、传什么参数）。
5. 面向调用方与人类可读：不用只有作者懂的内部代号（方法论黑话）；必要术语用一句白话解释（坏例：`拆零件求值时刻/维度表已变未变`；好例：`把关键校验代码拆开、标出每个值何时确定`）。
6. **描述与正文分工**：description 只写【是什么 / 为什么值得调用（动机与目的）/ 什么情况下调用 / 如何调用（必须传什么、返回什么）】；执行方法、判断标准、步骤写在正文，且正文按"什么情况用什么方案"组织，不写与场景无关的机械规则（反例：无条件规定"挑成本最低的实验"——挑选标准应服务于目标，即该实验能否改变当前判断）。

示例：
- ✅ `密码学分析 — 输入密码学题目（脚本/参数/密文）和分析需求，自动完成密码学攻击与 flag 求解`（含输入契约）
- ✅ `无记忆评审分身：对卡壳中的分析做不带任何既有结论的独立重判，这是为了避免既有结论的干扰，目的是找到真正的突破点。…委派必须传：目标 + 原始材料绝对路径 + 分析台账（ledger.md）；返回…`（先说清"为什么 + 目的"，再给触发条件与输入契约）
- ❌ 只有"是什么"：`长期记忆专家 —— 检索历史上下文`（无触发、无输入 → 不会被可靠自动调用）

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
- **规则持久化**: agent prompt 在系统提示（每次 LLM 请求都有，不随压缩丢失）；compacting hook 注入分析状态保留 + TASK_DIR，并置 justCompacted 标识触发 system.transform 强制重注入环境信息

**来源文件**:
- `vendor/oh-my-openagent/src/features/claude-code-agent-loader/loader.ts` — Agent 加载逻辑
- `vendor/oh-my-openagent/src/features/claude-code-agent-loader/agent-definitions-loader.ts` — Markdown 解析
- `vendor/oh-my-openagent/src/shared/frontmatter.ts` — Frontmatter 解析
- `vendor/oh-my-openagent/src/config/schema/agent-overrides.ts` — 配置覆盖 schema
