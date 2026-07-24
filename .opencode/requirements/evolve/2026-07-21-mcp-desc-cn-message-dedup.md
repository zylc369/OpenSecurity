# MCP 描述中文化 + message 参数 + 语言策略统一 + 去重

## §1 背景与目标

### 来源痛点

调研发现 4 类问题：

| # | 问题 | 根因 |
|---|------|------|
| 1 | MCP 描述用英文，项目维护者看不懂 | 照搬 PentAGI 英文描述 |
| 2 | events 工具缺 message 参数 | PentAGI 有，我们漏了 |
| 3 | knowledge 工具 message 参数是死代码（接收了不使用） | 没实现消费端 |
| 4 | MCP schema 说 "ALWAYS English" 但实际应该用中文查询 | 照搬 PentAGI 语言策略，但 BGE-M3 + 中文存储 ≠ OpenAI + 英文存储 |
| 5 | agent prompt 与 MCP schema 参数描述重复 | 两处分别维护，已出现冲突 |

### PentAGI message 的定位（源码确认）

message 是**所有工具都有的参数**——用户可见的操作日志（"agent 正在做什么"的 1-2 句话）。

```
executor.go:510 getMessage(args) → 从工具参数 JSON 提取 message
executor.go:289 mlp.PutMsg() → 存入 msglogs 数据库表
前端读取 → 时间线展示
```

我们对应：plugin 的 `tool.execute.after` hook 从 `input.args.message` 提取，写入 timeline。

### 改造目标

1. knowledge/events MCP 所有描述改中文
2. events 工具加 message 参数
3. knowledge 工具 message 描述改准确
4. plugin tool.execute.after 消费 message 写入 timeline
5. 语言策略统一为中文（BGE-M3 同语言匹配最优）
6. agent prompt 去除与 MCP schema 重复的参数描述

---

## §2 技术方案

### 2.1 MCP 描述改中文

knowledge/server.py 和 events/server.py 的 `@mcp.tool(description=...)` 和 `Annotated[..., Field(description=...)]` 全部改中文。

### 2.2 events 工具加 message 参数

每个 events 搜索工具加：
```python
message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
```

### 2.3 语言策略修正

knowledge MCP 的 questions/answer/question 参数描述从 "ALWAYS English" 改为中文策略：
- questions：用中文查询（与存储内容语言一致，BGE-M3 同语言匹配最优）
- answer：中文叙述 + 英文技术术语原样保留
- question（store）：中文问句，用"未来谁会查"的角度表述

### 2.4 plugin 消费 message

security-analysis.ts 的 `tool.execute.after` hook：
```typescript
const msg = (input.args as Record<string, unknown>)?.message;
if (typeof msg === "string" && msg.trim()) {
    recordTimeline(sid, {
        timestamp: Date.now(),
        type: "tool.after",
        tool: toolName,
        detail: msg.slice(0, 80),  // ← 新增：用 message 作为 timeline 描述
        duration: ...,
    });
}
```

### 2.5 agent prompt 去重

#### knowledge-management.md

去除参数写法指引（MCP schema 已有），只保留何时调/何时存：
```markdown
### 存分析结论
- 得出明确分析结论后，必须存储：
  - store_answer：存分析结论
  - store_guide：存可复用的操作步骤（如果有）
  - store_code：存可复用的 PoC/脚本（如果有）
```

#### searcher.md

语言策略段落保留（这是 MCP schema 没有的策略信息），但去除参数基本含义描述（MCP schema 已有）。

---

## §3 实施步骤

### 步骤 1：knowledge/server.py 描述改中文 + 语言策略修正
### 步骤 2：events/server.py 描述改中文 + 加 message 参数
### 步骤 3：plugin 消费 message
### 步骤 4：knowledge-management.md 去重
### 步骤 5：searcher.md 去重
### 步骤 6：验证 MCP schema 全部参数有中文 description + message
