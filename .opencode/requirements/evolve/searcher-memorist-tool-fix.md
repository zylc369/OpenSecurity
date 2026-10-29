# searcher/memorist 工具区分修复 — 追踪文档

## 问题根因

PentAGI 中 searcher 和 memorist 调用**不同的向量库工具**（`search_answer` vs `search_in_memory`），查**不同的 doc_type**（`answer` vs `memory`）。我在转写时合并为一个 `search_answer`，导致 memorist.md 错误地用了 searcher 的工具名。

## 一期改动（本期执行）

| # | 改动 | 文件 | 状态 |
|---|---|---|---|
| 1 | memory MCP 新增 `search_in_memory` 工具 + doc_type 字段 | `db.py` + `server.py` | ✅ 完成 |
| 2 | searcher.md 增加 doc_type=answer 说明 | `agents/searcher.md` | ✅ 完成 |
| 3 | memorist.md 改用 `search_in_memory` + 删除 `store_answer` | `agents/memorist.md` | ✅ 完成 |
| 4 | 删除旧 memory.db（重建含 doc_type 的 schema） | `~/bw-security-analysis/memory.db` | ✅ 完成 |
| 5 | retrieval-strategy.md 工具名同步修改 | `memorist/knowledge-base/retrieval-strategy.md` | ✅ 无需改动（文件未直接引用工具名） |

## 二期待做（后续工程）

| # | 事项 | 说明 | 依赖 |
|---|---|---|---|
| 1 | doc_type=memory 自动写入 | PentAGI 用 executor.go storeToolResult 自动记录工具执行（14 种工具）。OpenSecurity 需用 OpenCode 的 `tool.execute.after` hook 实现，在工具执行后自动调用 memory MCP 的 store_in_memory（需新增此工具或用内部 API） | 一期完成 |
| 2 | Graphiti 自动写入 | PentAGI 用 performer.go 自动存 LLM 返回（agent response）+ 工具执行到 Graphiti。OpenSecurity 需在 plugin 的 `tool.execute.after` 或 `chat.message` hook 中实现自动写入 | 无 |
| 3 | Graphiti 真实查询（替换 stub） | 接入 Neo4j + Graphiti 服务端，替换 graphiti/server.py 中的 stub 返回 | 二期-2 完成 |
| 4 | code/guide doc_type 支持 | PentAGI 有 4 种 doc_type（answer/memory/code/guide），OpenSecurity 当前只需 answer + memory。code 类型对应 coder agent（PentAGI 有），guide 类型对应 pentester agent | PentAGI 其他 agent 进化时 |
| 5 | store_in_memory 工具 | PentAGI 也没有这个工具（memory 类型只由框架自动写入，不由 LLM 显式写入）。但 OpenSecurity 如果不走自动写入路线，可能需要 LLM 显式调用 | 二期-1 的方案选择 |
| 6 | 向量库 delete/update 工具 | PentAGI 和 OpenSecurity 都没有删除/修改向量库记录的工具。长期需要"标记错误记忆为失效"的能力 | 实测后评估 |
| 7 | **memorist 注入 `$ROOT_TASK_DIR`** | memorist 作为子 agent，当前 `$TASK_DIR` 指向自己的空子任务目录（`<rootTaskDir>/subtasks/<memorist_session>/memorist/`）。需要注入根任务目录 `$ROOT_TASK_DIR`（从 SessionData.rootTaskDir 获取），让 memorist 能读根 agent 的历史产物。改 `security-analysis.ts` 的 expandSearcherDomainPlaceholder 函数 | 一期（优先） |
| 8 | **memorist.md 重写** | 整体重写：搜索优先级明确（Graphiti 优先 → search_in_memory 补充 → Read/Bash 验证）、术语统一（知识图谱 vs 向量库、情景记忆）、搜索类型决策表（不含参数）、合并 retrieval-strategy.md、删除冗余、语言策略统一为中文+英文术语 | ✅ 完成 |
| 9 | **retrieval-strategy.md 删除** | 内容已合并到 memorist.md | ✅ 完成 |

## 修复后的工具分工

| 维度 | searcher | memorist |
|---|---|---|
| 查向量库 | ✅ `search_answer`（doc_type=answer） | ✅ `search_in_memory`（doc_type=memory） |
| 写向量库 | ✅ `store_answer`（doc_type=answer） | ❌ 不写（与 PentAGI 一致） |
| 查 Graphiti | ❌ 不直接查（通过 memorist 间接） | ✅ 7 种 search（stub） |
| 读文件/执行命令 | ❌ 不需要 | ✅ Read/Glob/Grep/Bash |
| 委派 memorist | ✅ Task(subagent_type: memorist) | ❌ 不委派 |
