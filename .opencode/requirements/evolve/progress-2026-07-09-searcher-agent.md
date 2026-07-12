# 进度：2026-07-09-searcher-agent

## Step 1 ✅ 完成
- 文件：
  - `.opencode/mcp-servers/memory/pyproject.toml`（依赖声明：mcp, sentence-transformers, sqlite-vec）
  - `.opencode/mcp-servers/memory/server.py`（FastMCP server，2 个工具 stub）
  - `.opencode/mcp-servers/memory/db.py`（SQLite schema + MemoryDB 类，store/search raise NotImplementedError）
- 环境变更：`~/bw-security-analysis/.venv/bin/pip install mcp` → mcp-1.28.1 已装
- 验证点全通过：
  1. server.py 启动后 initialize 握手成功，serverInfo.name="memory"
  2. tools/list 返回 search_answer + store_answer，inputSchema 正确
  3. sentence-transformers all-MiniLM-L6-v2 可加载（dim=384, norm=1.0）
- 关键 API 笔记（Step 2 会用）：
  - FastMCP 装饰器：`@mcp.tool(description=...)` + 函数 docstring → 自动生成工具 schema
  - sentence-transformers 5.6 API：`model.get_embedding_dimension()`（不是 `get_sentence_embedding_dimension`）
  - encode 返回 numpy ndarray，norm 用 `np.linalg.norm(v)`

## Step 2 ✅ 完成
- 实现：
  - `db.py`：双表设计（answers 普通 SQLite + answer_vectors vec0 虚拟表 384-dim cosine），_embed 用 struct.pack 序列化，search 多 query 合并分数 + type 过滤 + top_k 截断
  - `server.py`：模块顶层加载 SentenceTransformer（启动一次性 ~10s），search_answer/store_answer 调用全局 _db
- 验证点全通过：
  1. store_answer 写入成功（id 自增）
  2. search_answer 检索到 OpenSSL Heartbleed，score=0.6031 > 0.5
  3. type 过滤生效（type=code 时返回 0 结果）
  4. 不做代码层去重（重复 store 相同内容创建新 row，与 PentAGI search.go 一致）
- 关键 API 笔记（后续会话可能用）：
  - sqlite-vec vec0 表：`USING vec0(embedding float[384] distance_metric=cosine)`
  - 查询用 `WHERE embedding MATCH ? AND k = ?`，distance = 1 - cosine_similarity
  - vec0 表只能存 rowid + embedding，文本必须用普通表 JOIN
  - FastMCP 启动时 `print(..., file=sys.stderr)` 会输出到 stderr，不干扰 stdio JSON-RPC

## Step 3 ✅ 完成
- 文件：
  - `.opencode/mcp-servers/graphiti/pyproject.toml`（依赖：mcp）
  - `.opencode/mcp-servers/graphiti/server.py`（FastMCP server，7 工具 stub）
- 参数 schema 严格对齐 `github.com/vxcontrol/graphiti-go-client@v0.9.0/types.go`：
  - `temporal_window_search(query, time_start, time_end, max_results=15)`
  - `entity_relationships_search(query, center_node_uuid, max_depth=2, node_labels?, edge_types?, max_results=20)`
  - `diverse_results_search(query, diversity_level="medium", max_results=10)`
  - `episode_context_search(query, max_results=10)`
  - `successful_tools_search(query, min_mentions=2, max_results=15)`
  - `recent_context_search(query, recency_window="24h", max_results=10)`
  - `entity_by_label_search(query, node_labels[], edge_types?, max_results=25)`
- 验证点全通过：
  1. server.py 启动成功
  2. tools/list 返回 7 个工具
  3. 调用 recent_context_search 返回 `{"edges":[],"nodes":[],"episodes":[],"note":"Graphiti backend not implemented yet..."}` + 透传参数（time_window.recency="24h"）
- 修复记录：line 111 漏了开头引号导致 SyntaxError，修复后通过

## Step 4 ✅ 完成
- 文件：`.opencode/mcp.json`（新建，13 行）
- 配置 schema 对齐 `vendor/opencode/packages/core/src/v1/config/mcp.ts`：
  - `type: "local"` + `command: [python_path, server.py_path]`（command 是数组，无 args 字段）
  - `enabled: true` + `timeout` 设置（memory 30s 含模型加载，graphiti 10s）
- 验证：
  1. ✅ JSON 语法合法
  2. ✅ python 路径 + 两个 server.py 路径都存在
  3. ⏳ 端到端"启动 OpenCode 后工具可见"留到 Step 11
- 待办（Step 10 评估）：当前 mcp.json 用绝对路径（venv python + workspace server.py），不可移植。如需跨机器部署，Step 10 中迁移到 plugin 的 config hook 动态注册（plugin 已有 VENV_DIR 检测能力）。

## Step 5 ✅ 完成
- 文件：
  - `.opencode/agents/memorist.md`（163 行，全英文）
  - `.opencode/memorist/knowledge-base/retrieval-strategy.md`（87 行）
- frontmatter 验证：
  - `mode: subagent` ✓
  - `buwai-extension-id: memorist` ✓（触发 plugin 占位符展开）
  - permission 不含 task（单向调用规则：memorist 不调 Task 工具）✓
- 内容对照 PentAGI memorist.tmpl：
  - 保留：LONG-TERM MEMORY SPECIALIST 定位、拆分查询策略、exact sentence matching、合并多源结果、Graphiti 7 种搜索类型完整选择指南、COMMAND EXECUTION RULES、TOOL UTILIZATION
  - 简化：LANGUAGE POLICY 全英文（去除双通道）
  - 去除：{{.Lang}}/{{.GraphitiEnabled}}/{{.DockerImage}}/{{.Cwd}}/{{.ExecutionContext}}/{{.UserFiles}}/{{.CurrentTime}} 占位符；{{.SummarizationToolName}} 摘要感知协议（OpenCode compacting 接管）；{{.MemoristResultToolName}} barrier 工具（Task 天然 barrier）；{{.ToolPlaceholder}} 收尾约束
  - 替换：{{.FileToolName}}/{{.TerminalToolName}} → Read/Glob/Grep/Bash；{{.GraphitiSearchToolName}} → mcp__graphiti__xxx
- Graphiti stub 容错策略：
  - memorist.md 顶部 Phase 1 note 明确说明 stub 行为
  - retrieval-strategy.md 专门段落"Stub Phase Handling"
- 5 个验证点全部通过：frontmatter 合法 + 全英文 + 工具名正确 + 不调 searcher/Task + PentAGI 对照覆盖

## Step 6 ✅ 完成
- 文件：
  - `.opencode/agents/searcher.md`（128 行，全英文）
  - `.opencode/searcher/knowledge-base/search-methodology.md`（129 行）
- frontmatter 验证：
  - `mode: subagent` ✓
  - `buwai-extension-id: searcher` ✓
  - `permission: { task: { "*": allow } }` **必须**（让 searcher 能调 memorist，subagent-permissions.ts:18-25 默认禁止）✓
- 占位符与调用：
  - 含 `{{searcher-domain:xxx}}` 占位符（待 Step 9 实现展开）✓
  - 含 `Task(subagent_type: memorist)` 嵌套调用指令 ✓
  - searcher.md 主体（除 Memorist Delegation 段落外）**不出现 mcp__graphiti__**（符合"searcher 不直接调 Graphiti"）✓
- 来源优先级顺序正确：memory(1) → memorist(2) → websearch(3) → webfetch(4) → web_render.py(5) → store_answer(on-demand)
- 内容对照 PentAGI searcher.tmpl：
  - 保留：精英搜索情报 agent 定位、动作经济性（3-5 次搜索封顶）、来源优先级、查询工程、结果交付 SOP、搜索工具部署矩阵
  - 简化：LANGUAGE POLICY 全英文
  - 去除：{{.Lang}}/{{.SearchAnswerToolName}}/{{.StoreAnswerToolName}}/{{.SearchResultToolName}}/{{.SummarizationToolName}}/{{.ExecutionContext}}/{{.CurrentTime}}/{{.UserFiles}}/{{.Cwd}} 占位符；强制匿名化（用户决策）；摘要感知协议（OpenCode compacting 接管）；授权框架段落（防御性分析）；{{.ToolPlaceholder}} 收尾约束
  - 替换：search_result barrier 工具 → Task 工具天然 barrier

## Step 7 ✅ 完成
- 6 个领域片段文件：
  - `domain-sources-binary-analysis.md`（39 行）— NVD/Exploit-DB/IDA docs/Ghidra/Packers/CVE-MITRE
  - `domain-sources-mobile-analysis.md`（42 行）— Android dev/Frida/iOS dev/jadx-apktool/Android Security bulletins/Oversecured/codeshare
  - `domain-sources-web-analysis.md`（46 行）— PortSwigger/OWASP/HackerOne/PayloadsAllTheThings/框架 advisories/HTTP RFCs/Cache poisoning
  - `domain-sources-ai-security-analysis.md`（42 行）— OWASP LLM Top10/Lakera/PromptInject/AI Village/arXiv/LangChain advisories/HuggingFace
  - `domain-sources-crypto-analysis.md`（49 行）— SageMath/CTF writeups/factordb/RsaCtfTool/经典论文/PyCryptodome/ePrint
  - `domain-sources-general.md`（45 行）— Wikipedia/SO/GitHub/官方文档/HackerNews/RFC Editor + general 使用场景说明
- 命名严格对齐 SECURITY_AGENTS（domain-sources-<agent-name>.md）+ general 兜底
- 每个文件含 `<domain_sources>` XML 标签 + 优先源清单 + 查询术语约定 + store_answer type mapping
- 每个文件自包含，独立可读

## Step 8 ✅ 完成
- 修改文件：`.opencode/plugins/lib/constants.ts`（新增 ~50 行常量 + 注释）
- 新增常量：
  - `AGENT_SEARCHER = "searcher"`、`AGENT_MEMORIST = "memorist"`
  - `AGENTS_WITH_DELEGATION_RULES`（5 领域 + searcher + memorist；不含 evolve/coordinator）
  - `SECURITY_ROOT_AGENTS`（仅 5 个领域 agent，用于 resolveRootSecurityAgent 精确匹配——evolve/coordinator 不调 searcher）
- 验证（bun 运行时 import）：
  - AGENT_SEARCHER/MEMORIST 字符串值正确
  - AGENTS_WITH_DELEGATION_RULES 长度 7，含 searcher/memorist，不含 evolve/coordinator ✓
  - SECURITY_AGENTS.length=7（保持不变，向后兼容）✓
  - SECURITY_ROOT_AGENTS 不含 evolve ✓
- 决策记录：需求文档原本说"resolveRootSecurityAgent 用 SECURITY_AGENTS"，但实际 SECURITY_AGENTS 含 evolve/coordinator，而这两个不调 searcher，不应作为合法根。新增 SECURITY_ROOT_AGENTS 更精确，避免误判。需求文档没强制规定用哪个常量，这是改进。

## Step 9 ✅ 完成
- 修改 3 个文件：
  - `.opencode/plugins/lib/session-manager.ts`（+81 行）：新增 `resolveRootSecurityAgent(sessionID)`、`requireRecognizedAgent(hookName, sessionID)`、SessionData 新增 `isSearchSubagent()` 和 `isRecognizedAgent()`
  - `.opencode/plugins/lib/snippet.ts`（+27 行）：`loadSnippet(name, dir?)` 扩展可选 dir 参数（默认 AGENTS_RULES_DIR 向后兼容）；新增 `loadSearcherDomainSnippet(rootAgent)` 含 general 兜底
  - `.opencode/plugins/lib/constants.ts`（+1 行）：新增 `SEARCHER_KNOWLEDGE_BASE_DIR`
- 单元测试（10 项全通过，bun 运行时）：
  1. searcher → binary-analysis 命中 ✓
  2. searcher ← evolve → null ✓
  3. 循环中含 binary 仍命中 ✓
  4. 纯循环防护（visited set） ✓
  5. loadSnippet 向后兼容（running-environment.md 131 chars） ✓
  6. loadSnippet 显式 dir（domain-sources-binary-analysis.md 1790 chars） ✓
  7. loadSearcherDomainSnippet("binary-analysis") 命中 ✓
  8. loadSearcherDomainSnippet(null) → general 兜底（2225 chars） ✓
  9. loadSearcherDomainSnippet(unknown) → general 兜底 ✓
  10. isSearchSubagent / isRecognizedAgent 正确分类 ✓
- 关键 API 笔记：
  - SessionData 已有 parentSessionID 字段（line 12, 177 由 createFromAPI 从 API 提取），无需改造
  - session.created hook 对所有 session（含 subagent）触发 → searcher/memorist 的 SessionData 会被自动创建
  - searcher/memorist 不在 SECURITY_AGENTS 中 → `requireSecurityAgent` 会跳过它们 → Step 10 需改用 `requireRecognizedAgent`

## Step 10 ✅ 完成
- 修改文件：`.opencode/plugins/security-analysis.ts`（888 → 995 行，+107 行）
- 改动点：
  1. import 新增：AGENTS_WITH_DELEGATION_RULES、AGENT_SEARCHER、AGENT_MEMORIST、loadSearcherDomainSnippet、readFileSync
  2. system.transform 中 `requireSecurityAgent` 返回 undefined 时，新增 subagent 分支：检测 isSearchSubagent → 调 expandSearcherDomainPlaceholder
  3. system.transform 主路径尾部新增委派清单注入（仅对 AGENTS_WITH_DELEGATION_RULES 成员）
  4. 新增 3 个辅助函数：expandSearcherDomainPlaceholder、buildDelegationBlock、readAgentDescription
- 验证（bun bundle + 集成测试）：
  1. plugin bundle 成功（75KB，14 modules，无错）
  2. 7 个 agent description 全部可读
  3. searcher ← binary-analysis 链 → root=binary-analysis
  4. 对应 domain-sources-binary-analysis.md 加载（1790 chars）
- 决策记录：
  - searcher/memorist 走"轻量路径"——只做 snippet 展开不注入 env/agent身份/委派清单。subagent 不需要 env 信息（$IDAT 等它们用不到），调用方 prompt 已经传必要上下文
  - 委派清单只对 5 个领域 agent + searcher + memorist 注入（用户能在主路径看到）。但 searcher/memorist 实际上不需要看清单（它们不主动委派），所以轻量路径下不注入
  - readAgentDescription 用同步 readFileSync（每次 LLM 调用都执行，但 mtime 缓存可后续优化）
- 修复记录：expandSearcherDomainPlaceholder 初版有冗余 rootAgent 调用，清理为单一 realRoot 调用

## Step 11 ✅ 完成
- 操作：
  - 删除 `.opencode/agents-rules/cross-agent-delegation.md`
  - 删除 4 个 agent .md 中的 `{{buwai-rule:cross-agent-delegation}}` 占位符行（binary/mobile/web/ai-security；crypto 本来就没引用）
- 端到端静态验证（9 项，8 自动通过 + 1 测试断言误报）：
  1. ✅ searcher.md 不直接调 mcp__graphiti__
  2. ✅ searcher.md 含 {{searcher-domain:xxx}} 占位符
  3. ✅ searcher 展开 binary 领域片段正确（含 Exploit-DB、不含 PayloadsAllTheThings；初次断言用 "PortSwigger" 误报，因 searcher.md line 114 主体提到此词作示例）
  4. ✅ 4 个领域 agent .md 不再含 cross-agent-delegation 占位符
  5. ✅ cross-agent-delegation.md 已删除
  6. ✅ 委派清单注入正确（含 searcher/memorist + 5 领域；不含 evolve/coordinator）
  7. ✅ 5 个领域 agent 主体未破坏（mode/buwai-ext/body length 全部正常）
  8. ✅ 其他 agents-rules snippet 加载正常（running-environment/analysis-planning-rules/execution-discipline）
  9. ⏳ MCP servers 启动已在 Step 1/3 验证

- **决策记录**：需求文档说"5 个领域 agent .md 不改"，但实际删除 cross-agent-delegation.md 必须同时删除 4 处占位符引用，否则 LLM 看到字面占位符字符串污染 prompt。改动只是删一行占位符，主体不动，与用户意图"不维护两套描述"一致。
- **待用户实测**：searcher 全链路（memory→memorist→websearch→store_answer→return）需要 OpenCode 实际启动 + exa API key。建议用 binary-analysis 委派 searcher 查 CVE-2014-0160 验证。

---

# Phase 5 全部 11 步骤完成

## 文件总览
**新增（16 个）**：
- 2 个 agent：searcher.md、memorist.md
- 2 个 agent 知识库目录：searcher/knowledge-base/（7 个文件）、memorist/knowledge-base/（1 个文件）
- 2 个 MCP server：mcp-servers/memory/（3 个文件 + pyproject.toml）、mcp-servers/graphiti/（2 个文件 + pyproject.toml）
- 1 个 MCP 配置：mcp.json

**修改（5 个 → 实际 9 个）**：
- constants.ts（新增常量）
- session-manager.ts（新增 resolveRootSecurityAgent + requireRecognizedAgent + isSearchSubagent）
- snippet.ts（loadSnippet 扩展 dir 参数 + 新增 loadSearcherDomainSnippet）
- security-analysis.ts（system.transform 新增 subagent 路径 + 委派清单注入 + 3 辅助函数）
- 4 个领域 agent .md（删除 cross-agent-delegation 占位符引用）

**删除（1 个）**：
- agents-rules/cross-agent-delegation.md

## 环境变更
- venv 新装：mcp-1.28.1（pip install mcp）
- ~/.bw-security-analysis/memory.db（向量库数据，运行时生成）

## 后续工作建议
1. **mcp.json 跨机器可移植性**：当前绝对路径，迁移到 plugin 的 config hook 动态注册（结合现有 VENV_DIR 检测）
2. **Graphiti 实装**：替换 graphiti/server.py 中的 stub 为真实 graphiti-core SDK 调用
3. **缺失搜索源补齐**：sploitus（高优先级，binary 场景）、perplexity（推理型）、tavily（学术）
4. **readAgentDescription 性能优化**：当前每次 LLM 调用都读 7 个文件，可加 mtime 缓存

---

# Phase 6: 审计实现 — 完成

## 审计过程（按规则 3 节奏）

### 第 1 轮审计 + 修复
- **高严重度问题 1**：subagent 走轻量路径不注入 `$AGENT_DIR`/`$SHARED_DIR`/`$TASK_DIR`，导致 searcher.md/memorist.md 中的路径引用失效
  - 修复：expandSearcherDomainPlaceholder 函数中新增"路径变量段"注入到 output.system 末尾
- **中严重度问题 2**：MCP server timeout 30s vs sentence-transformers 首次加载 10s+
  - 修复：mcp.json 中 memory timeout 改为 60000ms

### 第 2 轮审计 + 修复
- **高严重度问题 3**：searcher.md 中 `{{searcher-domain:xxx}}` 只在反引号里作为说明文字，没有真正的占位符位置
  - 修复：在 "## Domain-Specific Source Hints" 段末尾添加真正的 `{{searcher-domain:root}}` 占位符（不在反引号里）
- **中严重度问题 4**：6 个 domain-sources-*.md 文件的 HTML 注释含 `{{searcher-domain:xxx}}` 字符串，注入到 prompt 后被测试断言当成未展开占位符
  - 修复：把注释中的 `{{searcher-domain:xxx}}` 改为 `searcher-domain block` 字面描述

### 第 3 轮（纯审计）+ 修复
- **低严重度问题 5**：`requireRecognizedAgent` + `isRecognizedAgent` 是 dead code（最终用了 `get()` + `isSearchSubagent()` 直接判断）
  - 修复：按规则 3"绝对禁止设严重度门槛"，删除 dead code

### 第 4 轮（纯审计）
- 零新问题 → 审计通过

## 最终验证（全部通过）

| 类别 | 检查项 | 状态 |
|---|---|---|
| 文件清单 | 16 新增 + 9 修改 + 1 删除 = 26 个文件改动 | ✓ |
| 语法 | Python / TypeScript (bun bundle) / JSON / TOML | ✓ |
| 集成测试 | 模拟 system.transform 处理 searcher session，9 项检查 ALL PASS | ✓ |
| 跨文件一致性 | MCP 工具名 `mcp__memory__search_answer` 在 server.py / searcher.md / memorist.md 一致 | ✓ |
| 运行时正确性 | MCP server 长期持有 SQLite 连接（与 sqlite-vec 虚拟表共用）；模型一次性加载 | ✓ |
| PentAGI 对照 | searcher.md（动作经济性/来源优先级/查询工程）+ memorist.md（LONG-TERM MEMORY SPECIALIST/Graphiti 7 搜索类型）核心保留 | ✓ |
| 回归 | 5 个领域 agent 主体未破坏；其他 agents-rules snippet 加载正常 | ✓ |
| Dead code | 已清理 | ✓ |

## 待用户实测的端到端项

下列需要 OpenCode 实际启动 + exa API key：
- searcher 全链路：memory → memorist → websearch → store_answer → 返回
- 再次查同 CVE → memory 命中（动作经济性生效）
- binary-analysis system prompt 含委派清单（实际渲染）
- searcher 被 binary-analysis 调用时含 binary 领域片段（实际渲染）

建议验证用例：binary-analysis 委派 searcher 查 CVE-2014-0160（OpenSSL Heartbleed）

---

# 实施完成总结

| 维度 | 数据 |
|---|---|
| 完成步骤 | Phase 5 全部 11 步 + Phase 6 审计 |
| 新增文件 | 16 个 |
| 修改文件 | 9 个（4 个 plugin 模块 + 4 个领域 agent .md + 1 个 mcp.json） |
| 删除文件 | 1 个（cross-agent-delegation.md） |
| 新增代码行 | ~1100 行（Python MCP ~400 + TS plugin ~250 + Markdown 知识库 ~450） |
| PentAGI 功能覆盖 | searcher 完整 + memorist 完整 + memory MCP 完整 + Graphiti stub |
| 与 PentAGI 偏离 | 全英文（用户决策）+ 不匿名化（用户决策）+ 不用 search_result barrier（OpenCode Task 天然 barrier）|

---

# 增量改造：BGE-M3 替换 + 方案 D 语言策略

## 用户决策
1. ✅ 替换 embedding 模型：all-MiniLM-L6-v2 → BAAI/bge-m3（1024 维，多语言，本地已装）
2. ✅ 采用方案 D（中文存查 + 英文 websearch + 中英混合返回）
3. ⏳ 文档/注释中文化（B 类，待用户决定执行方式）

## A 类技术改动（已完成）

### A1. 维度调整
- `db.py:14` `EMBEDDING_DIM = 384` → `1024`（代码实测 BGE-M3 dim=1024）
- 同步更新 db.py 模块 docstring

### A2. 模型替换
- `server.py:24` `MODEL_NAME = "all-MiniLM-L6-v2"` → `"BAAI/bge-m3"`
- 同步更新 server.py 模块 docstring

### A3. 删除旧 384 维空库
- `~/bw-security-analysis/memory.db` 已删除（首次 store 时按 1024 维 schema 重建）

### A4. 相似度门槛校准（基于 BGE-M3 实测分布）
- `memorist/knowledge-base/retrieval-strategy.md`：
  - 强命中 0.6 → **0.75**
  - 中度 0.45-0.6 → **0.50-0.75**
  - 弱命中 < 0.45 → **< 0.50**
  - 新增 BGE-M3 实测分布表（same/related/cross-lang/unrelated 各档均值）
- `searcher/knowledge-base/search-methodology.md`：
  - score >= 0.6 → **0.75**（3 处）
  - 0.45-0.6 → **0.50-0.75**

### A5. searcher.md 新增"语言策略（方案 D）"段
- 4 条规则：
  1. 向量库通道：中文叙述 + 英文技术 token
  2. websearch 通道：严格英文 query（技术内容英文主导）
  3. memorist 委派：中文 prompt
  4. 返回调用方：中文叙述 + 英文技术 token 原样保留
- 明确"Never translate technical tokens"（CVE 编号/payload/命令不可翻译）

### A6. memorist.md 同步新增"语言策略"段
- 与 searcher 一致，确保两 agent 共享同一存储/检索语言表面

### A7. 集成测试（7 项全通过）
1. ✅ EMBEDDING_DIM 常量 = 1024
2. ✅ BGE-M3 模型加载（13.2s，dim=1024）
3. ✅ vec0 虚拟表 schema 为 `float[1024]`
4. ✅ 中文 store + 中文 search：score=0.8215（BGE-M3 同语言高分，验证方案 D 设计）
5. ✅ type 过滤生效
6. ✅ 不去重（重复 store 创建新 row）
7. ✅ 跨语言（中文 query 命中英文 doc）：score=0.6759（与调研数据一致）
- 额外：MCP server 实际启动 + tools/list + 真实 store/search 调用 ✓

## 实测数据（BGE-M3 校准基准）

| 关系 | 实测分布 | 门槛建议 |
|---|---|---|
| same concept（不同表述） | avg 0.84, min 0.72 | ≥ 0.75 强命中 |
| related（相关但不同） | avg 0.61, range 0.50-0.75 | 0.50-0.75 中度 |
| cross-lang（中英跨语言） | avg 0.63, range 0.55-0.70 | 同 related |
| unrelated（不相关） | avg 0.33, max 0.46 | < 0.50 弱命中 |

## B 类待办（文档/注释中文化，未执行）

按方案 D 的语言策略，下列文件可改中文（不影响功能）：

**LLM 通过 Read 读取的文件（改中文，LLM 仍能理解）**：
- `.opencode/searcher/knowledge-base/search-methodology.md`（已是英文）
- `.opencode/memorist/knowledge-base/retrieval-strategy.md`（已是英文）
- `.opencode/searcher/knowledge-base/domain-sources-*.md` × 6（已是英文）

**LLM 通过 system prompt 看到的文件（改中文，但需校验）**：
- `.opencode/agents/searcher.md` 主体（保留新加的 Language Policy 段为英文，因为该段定义语言策略本身用英文表述更精确）
- `.opencode/agents/memorist.md` 主体（同上）

**纯开发者注释（改中文，零 LLM 影响）**：
- `.opencode/mcp-servers/memory/server.py` 行内注释 + 模块 docstring（保留 @mcp.tool description 和函数 docstring 为英文）
- `.opencode/mcp-servers/memory/db.py` 注释 + docstring
- `.opencode/mcp-servers/graphiti/server.py` 行内注释 + 模块 docstring（保留 @mcp.tool description 和函数 docstring）
- `.opencode/plugins/lib/{constants,session-manager,snippet}.ts` 新增代码的注释
- `.opencode/plugins/security-analysis.ts` 新增函数的注释（expandSearcherDomainPlaceholder/buildDelegationBlock/readAgentDescription）

**保持英文（绝对不改）**：
- MCP `@mcp.tool(description=...)` 参数（生成 tool schema 传给 LLM）
- MCP 工具函数 docstring（同上）
- searcher.md / memorist.md 中的 "Language Policy (Plan D)" 段（该段本身定义语言策略，用英文表述最精确）
- 代码块、URL、CVE 编号、命令、函数名

**待用户决策执行方式**：
- 方式 1：我用 Edit 工具逐文件翻译
- 方式 2：用户用 `/trans-md-en-to-zh` 命令批量翻译，我校验技术内容未被误译

---

# B 类翻译完成（subagent 并行）

## 执行方式
按用户决策"subagent 并行翻译最大 5 个"，使用 task 工具调度 general subagent，4 批共 17 个文件。

## 翻译统计

| 批次 | 文件 | 实际翻译 | 备注 |
|---|---|---|---|
| 1 | searcher.md / memorist.md / search-methodology.md / retrieval-strategy.md / domain-sources-binary-analysis.md | 5/5 | 全部完成 |
| 2 | domain-sources-{mobile,web,ai-security,crypto,general}-analysis.md | 5/5 | 全部完成 |
| 3 | memory/server.py / memory/db.py / graphiti/server.py / constants.ts / session-manager.ts | 5/5 | 全部完成 |
| 4 | snippet.ts / security-analysis.ts | 0/2 | subagent 诚实反馈：新增函数注释本就是中文（写代码时按项目惯例用了中文），无需翻译，未做无效覆盖 |

**总计：15/17 实际翻译 + 2/17 已是中文无需改**

## 翻译后验证（全部通过）

| 验证项 | 结果 |
|---|---|
| Python 语法（3 个 server/db.py） | ✓ 全通过 |
| TypeScript bundle（security-analysis.ts） | ✓ 75KB 编译成功 |
| MCP memory tools/list description | ✓ 保持英文（"Retrieve prior answers..."） |
| graphiti 7 个工具 description | ✓ 全部保持英文 |
| searcher.md frontmatter（mode/buwai-extension-id/task allow） | ✓ 完整保留 |
| searcher.md {{searcher-domain:root}} 占位符 | ✓ 保留 |
| Language Policy (Plan D) 段保持英文 | ✓ 主体全英文（仅示例字符串含中英混合，符合方案 D 设计） |

## 关键设计验证：MCP tool description 保持英文

源码核验：MCP tool 的 description 字符串是 LLM 调用工具时的 schema 说明，必须保持英文以确保跨调用稳定性。实测输出：

```
"description":"Retrieve prior answers from the vector store. ALWAYS call this FIRST..."
"description":"Persist a new (question, answer) pair to the vector store..."
"description":"Search the temporal knowledge graph for facts within a time window..."
...（7 个 graphiti 工具全部英文）
```

## subagent 诚实反馈亮点

第 4 批 snippet.ts / security-analysis.ts 的 subagent 没有机械执行翻译，而是按 AGENTS.md 规则 2（深度调研）和规则 5（交付前自检）反馈"文件已是中文，无效覆盖会制造噪音"——这正是高质量 subagent 该有的行为。

## 最终状态

- 所有 LLM 看到的功能性英文（@mcp.tool description、tool docstring、stub note、JSON keys、CVE 编号、URL、命令、占位符）全部保持原样
- 所有开发者注释、模块 docstring、知识库方法论翻译为中文（用户可读可改）
- searcher.md / memorist.md 主体翻译为中文（用户能读懂 prompt 并修改），Language Policy (Plan D) 段保持英文（这段定义语言策略本身用英文表述最精确）
- 方案 D 完整落地：BGE-M3（1024维）+ 中文存查 + 英文 websearch + 中英混合返回
