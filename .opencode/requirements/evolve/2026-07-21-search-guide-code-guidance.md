# 知识闭环修复：search_guide / search_code 调用指引

## §1 背景与目标

### 来源痛点

调研发现 knowledge 向量库的 guide 和 code 类型存在**知识闭环断裂**：

| 类型 | 存（写） | 搜（读） | 闭环？ |
|------|---------|---------|--------|
| answer | ✅ knowledge-management.md 引导 store_answer | ✅ searcher.md 引导 search_answer | ✅ |
| **guide** | ✅ knowledge-management.md 引导 store_guide | **❌ 无指引** | **❌ 断链** |
| **code** | ✅ knowledge-management.md 引导 store_code | **❌ 无指引** | **❌ 断链** |
| memory | ✅ 插件自动写入 | ✅ memorist.md 引导 search_in_memory | ✅ |

领域 agent 存了 guide/code 但**从来不会搜**——知识库里的指南和代码永远不会被复用。

### 根因

之前去重时删了 searcher.md 里 search_guide/search_code 的详细说明（与 MCP schema 重复的参数描述），但**只删了参数描述，没留下"何时调"的策略指引**。而 knowledge-management.md 只讲了 store（存），没讲 search（搜）。

### 改造目标

1. knowledge-management.md 加 search_guide/search_code 的"何时调"指引
2. 领域 agent 直接调（不委派 searcher——search_guide/search_code 足够简单）
3. 闭环：存了能搜到，搜到能复用

### 设计决策

search_guide/search_code 领域 agent 直接调，不走 searcher。理由：
- search_answer 需要复杂策略（语言策略、type 选择、决策树、可能触发 websearch）→ 委派 searcher
- search_guide/search_code 简单（传 questions + type/lang，拿结果）→ 直接调
- 领域 agent 比 searcher 更懂自己需要什么指南/代码

---

## §2 技术方案

### 2.1 knowledge-management.md 改动

在"查已有知识"段落加两条：

```markdown
### 查已有知识
遇到以下情况时，委派 searcher（Task 工具，subagent_type=searcher）查已有知识：
- **需要确定分析方向时**：查是否已有同类目标/漏洞/技术的分析记录
- **遇到不熟悉的技术时**：查外部资料

以下情况直接调 MCP 工具（不需要委派 searcher）：
- **需要操作指引时**：调 `mcp__knowledge__search_guide` 查是否已有可复用的操作步骤/配置方法
- **需要编写较复杂的脚本时**（exploit/PoC/多步骤工具）：先调 `mcp__knowledge__search_code` 查是否已有同类可复用代码
```

### 2.2 不改动的部分

- searcher.md：searcher 的流程不变（searcher 仍然以 search_answer 为主）
- memorist.md：不变
- MCP schema：不变（已有中文描述）
- events：不变

---

## §3 实施步骤

### 步骤 1：knowledge-management.md 加 search 指引

- 文件：`agents-rules/knowledge-management.md`
- 改动：在"查已有知识"段落加 search_guide/search_code 的调用指引
- 预估行数：~5 行
- 验证点：grep search_guide/search_code 有匹配

### 步骤 2：验证闭环

确认 guide/code 的存→搜闭环：
- store_guide → knowledge-management.md "存" ✅
- search_guide → knowledge-management.md "搜" ✅（本次新增）
- store_code → knowledge-management.md "存" ✅
- search_code → knowledge-management.md "搜" ✅（本次新增）
