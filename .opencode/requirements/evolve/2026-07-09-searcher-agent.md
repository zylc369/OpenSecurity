# 需求：新增 searcher agent + memorist agent + 记忆层 MCP

> **来源**：PentAGI（`~/Documents/Codes/pentagi`）的 searcher + memorist 实现
> **本期是 PentAGI 进化的第一个 agent，是标杆。功能与 PentAGI 一致，技术选型适配 opencode 生态。**

## §1 背景与目标

**PentAGI 是什么**：一款面向渗透分析的成熟 AI 系统，自建了一套 agent 框架（相当于自建了一套 opencode/claude-code）。其 searcher（情报检索）+ memorist（长期记忆）+ 向量库 + Graphiti 架构经多轮实战验证。

**OpenSecurity 的定位**：直接基于 opencode，复用 PentAGI 的**功能设计**，技术选型适配 opencode 生态（用 MCP 替代 PentAGI 内置工具、用 OpenCode Task 工具替代 PentAGI 自建 barrier 机制）。

**PentAGI 关键源码（已逐段核验）**：
- `backend/pkg/templates/prompts/searcher.tmpl` — searcher system prompt
- `backend/pkg/templates/prompts/memorist.tmpl` — memorist system prompt
- `backend/pkg/tools/tools.go:1460-1614 GetSearcherExecutor` — searcher 工具集
- `backend/pkg/tools/search.go` — 向量库工具实现（search_answer/store_answer）
- `backend/pkg/tools/graphiti_search.go:18-24` — Graphiti 7 查询方法签名
- `backend/pkg/providers/performers.go:693 performSearcher` — searcher 调用链
- `backend/pkg/providers/handlers.go:448 GetMemoristHandler` — memorist 嵌套调用

**OpenSecurity 现状痛点**：
1. 5 个领域 agent 各自为政检索，无统一纪律
2. 无跨任务记忆——同一 CVE/漏洞模式/工具用法每次重查
3. `agents-rules/` 有 analysis-planning/probe-first-strategy 等共享规则，但"如何查资料"无对应规则
4. `cross-agent-delegation.md` 只列了 crypto 委派，未覆盖情报检索场景

**预期收益（四维度量）**：
- 上下文：searcher 起手必查记忆，避免重复 webfetch（同任务内预计减少 30-50% webfetch 调用）
- 轮次：复杂查询 1 次委派 searcher，省父 agent 3-5 次工具调用
- 速度：跨任务记忆累积，长期看缩短 50%+ 重复检索时间
- 准确度：检索纪律统一（来源优先级、动作经济性），减少低质量来源干扰

---

## §2 技术方案

### 2.1 架构总览

```
父 agent (binary/mobile/web/ai-security/crypto)
   │ Task(subagent_type: searcher, prompt: "<英文查询>")
   ↓
searcher (subagent, 全英文链路)
   │ 工具循环（按 priority 顺序）:
   ├── mcp__memory__search_answer      (起手必查向量库, priority 1)
   ├── Task(subagent_type: memorist)   (深度历史检索, priority 2; memorist 内部调 Graphiti)
   ├── websearch                       (exa.ai 通用搜索, priority 3)
   ├── webfetch                        (直接读已知 URL, priority 4)
   ├── bash: web_render.py             (JS 渲染页面, priority 5)
   ├── mcp__memory__store_answer       (增量沉淀, 按需)
   └── 返回总结文本                     (OpenCode Task 工具天然 barrier)
   ⚠️ searcher 不直接调 Graphiti——Graphiti 由 memorist 内部调用（与 PentAGI tools.go:1460 GetSearcherExecutor 一致，graphiti 不在 searcher 工具集）
                ↓
        父 agent 收到英文总结 → 继续推理

memorist (subagent, searcher 委派, 全英文链路)
   │ 工具循环:
   ├── mcp__memory__search_answer      (向量库, 事实记忆, priority 1)
   ├── mcp__graphiti__xxx_search       (情景记忆, stub 返回空, priority 2; 二期补)
   ├── Read/Glob/Grep                  (替代 PentAGI file, 读 $TASK_DIR, priority 3)
   ├── Bash                            (替代 PentAGI terminal, 找历史脚本/日志, priority 4)
   └── 返回历史上下文总结               (Task 天然 barrier)
   ⚠️ memorist 不调 searcher（避免循环委派）
```

### 2.2 PentAGI → OpenSecurity 功能对照

| PentAGI 元素 | PentAGI 实现 | OpenSecurity 实现 | 状态 |
|---|---|---|---|
| searcher agent system prompt | `searcher.tmpl` + `GetSearcherExecutor` | `.opencode/agents/searcher.md` | 完整移植 |
| memorist agent system prompt | `memorist.tmpl` + `GetMemoristHandler` | `.opencode/agents/memorist.md` | 完整移植 |
| `search_answer` 向量库查询 | `search.go:case Retrieve` + langchain vecstore | `mcp__memory__search_answer` (Python MCP) | 完整 |
| `store_answer` 向量库写入 | `search.go:case StoreAnswerToolName` + vecstore | `mcp__memory__store_answer` | 完整 |
| Graphiti 知识图谱 | `graphiti_search.go` + Neo4j | `mcp__graphiti__xxx` (Python MCP **stub**) | **stub，二期补** |
| memorist `file` 工具 | 容器内文件读取 | OpenCode 内置 Read/Glob/Grep | 替代（零成本） |
| memorist `terminal` 工具 | 容器内命令执行 | OpenCode 内置 Bash | 替代（零成本） |
| `search_result` barrier 工具 | `registry.go:205` + `barriers` 注册 | OpenCode Task 工具天然 barrier | 替代 |
| `{{.ExecutionContext}}` 占位符 | handler 注入 Flow/Task/SubTask | 调用方 prompt 自然传递（Task 工具的 prompt 参数） | 替代 |
| 摘要感知协议 | `SummarizationToolName` + `SummarizedContentPrefix` | OpenCode compacting 机制 + plugin 处理 | 由 plugin 处理 |
| 双语言通道（任务语言 + 英文技术） | `{{.Lang}}` 控制日志 + 英语强制技术字段 | **全英文链路**（用户决策） | 简化 |
| 强制匿名化（IP/域名/凭据替换占位符） | `replacer.ReplaceString` (vxcontrol/anonymizer) | **不做**（用户决策，召回精度优先） | 移除 |
| 多搜索引擎（8 种） | google/ddg/tavily/perplexity/traversaal/searxng/sploitus/browser | 首版 3 种（详见 §2.3） | 精简 |

### 2.3 搜索引擎精简对照表

PentAGI searcher 注册 8 个外部源（`tools.go:1502-1592` 条件 `IsAvailable()`）。OpenSecurity 首版精简为 3 个，**缺失能力列入下表便于后续按需补齐**。

| PentAGI 源 | 用途 | OpenSecurity 首版 | 后续补齐优先级 |
|---|---|---|---|
| `google` | 通用搜索 | `websearch` (exa.ai) 替代 | - |
| `duckduckgo` | 隐私搜索 | `websearch` 替代 | 低 |
| `browser`（静态+动态） | 直接读 URL + 浏览器渲染 | `webfetch`（静态） + `bash: web_render.py`（JS 渲染）拆分替代 | - |
| `tavily` | 学术/技术深度搜索 | 缺失 | 中（复杂技术问题） |
| `perplexity` | 推理型综合搜索 | 缺失 | 中（推理型问题） |
| `traversaal` | 结构化答案搜索 | 缺失 | 低 |
| `searxng` | 自建元搜索（隐私） | 缺失 | 低 |
| `sploitus` | 漏洞利用专用搜索（exploit-db 索引） | 缺失 | **高**（binary 场景价值最高，无替代） |

**首版 OpenSecurity 工具集（3 个）**：
- `websearch` (provider=exa) → 通用搜索（替代 google/duckduckgo 的快速信息收集）
- `webfetch` → 直接读已知 URL（CVE 详情页、官方文档、技术博客）
- `bash: python $SHARED_DIR/scripts/web_render.py` → JS 渲染页面（替代 browser 动态部分）

**待补齐清单（后续进化参考）**：
1. **sploitus** —— 漏洞利用专用源，binary-analysis 查 CVE exploit 时价值最高
2. **perplexity** —— 推理型搜索，复杂技术问题（如"对比 LLL vs BKZ 在 NTRU 上的复杂度"）
3. **tavily** —— 学术深度搜索，crypto 查攻击论文
4. **searxng** —— 自建元搜索，无外部 API key 时用
5. **traversaal** —— 结构化答案，常见问题快速命中

### 2.4 文件清单

**新增（16 个）**：

| # | 文件 | 说明 |
|---|---|---|
| 1 | `.opencode/agents/searcher.md` | searcher agent prompt（`mode: subagent`，全英文） |
| 2 | `.opencode/agents/memorist.md` | memorist agent prompt（`mode: subagent`，全英文） |
| 3 | `.opencode/searcher/knowledge-base/search-methodology.md` | 动作经济性/来源优先级/查询工程 SOP |
| 4 | `.opencode/searcher/knowledge-base/domain-sources-binary-analysis.md` | binary 领域情报源优先级片段 |
| 5 | `.opencode/searcher/knowledge-base/domain-sources-mobile-analysis.md` | mobile 领域片段 |
| 6 | `.opencode/searcher/knowledge-base/domain-sources-web-analysis.md` | web 领域片段 |
| 7 | `.opencode/searcher/knowledge-base/domain-sources-ai-security-analysis.md` | ai-security 领域片段 |
| 8 | `.opencode/searcher/knowledge-base/domain-sources-crypto-analysis.md` | crypto 领域片段 |
| 9 | `.opencode/searcher/knowledge-base/domain-sources-general.md` | 通用兜底片段（找不到根 agent 时） |
| 10 | `.opencode/memorist/knowledge-base/retrieval-strategy.md` | memorist 检索策略（拆分查询/合并结果） |
| 11 | `.opencode/mcp-servers/memory/pyproject.toml` | memory MCP server 配置 |
| 12 | `.opencode/mcp-servers/memory/server.py` | MCP server 入口（search_answer + store_answer） |
| 13 | `.opencode/mcp-servers/memory/db.py` | SQLite + sqlite-vec + embedding 逻辑 |
| 14 | `.opencode/mcp-servers/graphiti/pyproject.toml` | graphiti MCP 配置 |
| 15 | `.opencode/mcp-servers/graphiti/server.py` | Graphiti MCP stub（7 方法签名齐全，全返回空） |
| 16 | `.opencode/mcp.json` | MCP 配置（注册 memory + graphiti 两个 server） |

**修改（5 个）**：

| # | 文件 | 改动 |
|---|---|---|
| 17 | `.opencode/plugins/lib/constants.ts` | 新增 `AGENTS_WITH_DELEGATION_RULES` 常量（含 searcher/memorist 及 5 个领域 agent） |
| 18 | `.opencode/plugins/lib/session-manager.ts` | 新增 `resolveRootSecurityAgent(sessionID)` 方法（递归找父链上的 SECURITY_AGENTS） |
| 19 | `.opencode/plugins/lib/snippet.ts` | 新增 `{{searcher-domain:xxx}}` 占位符展开（按根 agent 加载领域片段） |
| 20 | `.opencode/plugins/security-analysis.ts` | `system.transform` 中新增：(a) searcher-domain 占位符展开；(b) 注入"可委派 agent 清单"到所有 `AGENTS_WITH_DELEGATION_RULES` 成员 |
| 21 | `.opencode/agents-rules/cross-agent-delegation.md` | **删除**（替换为 plugin 自动注入委派清单，避免维护两套 description） |

### 2.5 典型数据流示例

binary-analysis 在逆向时遇到未知 OpenSSL 函数，需要查 CVE：

```
1. binary-analysis → Task(subagent_type: searcher, prompt: "Identify CVE for OpenSSL 1.0.1 heartbeat function, provide PoC if available")
2. searcher 起手 → mcp__memory__search_answer(["OpenSSL 1.0.1 heartbeat CVE"]) → 0 hits
3. searcher → Task(subagent_type: memorist, prompt: "Any past analysis on OpenSSL 1.0.1 vulnerabilities?")
   memorist 调 mcp__graphiti__recent_context_search (stub 返回空) + mcp__memory__search_answer (空) + grep $TASK_DIR (无相关) → 返回 "no relevant history"
4. searcher → websearch("OpenSSL 1.0.1 heartbeat CVE-2014-0160 PoC") → 命中多篇
5. searcher → webfetch("https://nvd.nist.gov/vuln/detail/CVE-2014-0160") → 拿到详情
6. searcher → mcp__memory__store_answer(question="OpenSSL Heartbleed CVE-2014-0160", answer="<英文详细>") ← 沉淀
7. searcher 返回英文总结（含 CVE 编号、影响版本、PoC 链接、利用条件）→ binary-analysis 继续推理
```

---

## §3 实现规范

### 3.1 改动范围

见 §2.4，共 **16 个新增 + 5 个修改 = 21 个文件**。

### 3.2 编码规则

- **MCP server 用 Python**：记忆库 embedding 生态 + Graphiti 官方 SDK 都是 Python
- **MCP SDK 选型**：官方 `mcp` 包（Python SDK，stdio 传输）
- **向量库**：SQLite + sqlite-vec 扩展（轻量、无外部服务依赖）
- **Embedding 模型**：本地 sentence-transformers，首版 `all-MiniLM-L6-v2`（英文优化、~80MB，首次启动自动下载到 `~/.cache/huggingface`；如需离线部署，预下载模型并设置 `TRANSFORMERS_OFFLINE=1`）
- **agent prompt 全英文**：searcher.md / memorist.md 内容全英文（与 PentAGI 一致）
- **占位符复用现有机制**：`{{buwai-rule:xxx}}` → `agents-rules/<xxx>.md`，已有 snippet 加载器（`snippet.ts:47 loadSnippet`）
- **新增占位符**：`{{searcher-domain:xxx}}` → `searcher/knowledge-base/domain-sources-<xxx>.md`，按根 agent 替换；与 `{{buwai-rule:xxx}}` 命名空间隔离，不冲突
- **MCP 工具调用格式**：opencode 把 MCP 工具暴露为 `mcp__<server>__<tool>`（双下划线分隔，与 OpenAI function calling 命名一致）。agent prompt 中写完整名 `mcp__memory__search_answer`、`mcp__graphiti__temporal_window_search` 等
- **subagent 权限**：**仅 searcher** 的 frontmatter 必须显式声明 `permission: { task: { "*": allow } }`——根据 `subagent-permissions.ts:18-25`，subagent 默认禁止调 task，不显式 allow 则 searcher 调不动 memorist。**memorist 不需要** task allow（单向调用规则：memorist 不调任何 Task 工具）
- **MCP 工具对 subagent 可见性**：MCP server 全局注册后，所有 agent（含 subagent）都能调用，无需在 agent frontmatter 声明 MCP 权限
- **单向调用规则**：`searcher → memorist` 单向；memorist 不调 searcher（避免循环）
- **依赖方向**：MCP server 独立进程，不依赖 plugin 代码；agent prompt 通过 MCP 工具名调用
- **不修改**：`.opencode/agents/binary-analysis.md` 等 5 个领域 agent .md 文件（plugin 注入覆盖）
- **常量关系澄清**：`AGENTS_WITH_DELEGATION_RULES` ≠ `SECURITY_AGENTS` 的超集。前者 = `[5 个领域 agent] + [searcher, memorist]`，**不含** security-analysis-evolve（不参与分析任务，是开发工具）、security-coordinator（用户已决策保留但不参与本期注入）。`SECURITY_AGENTS` 保持现状不动。
- **websearch provider 配置**：opencode 内置 websearch 工具的 provider 由环境变量 `OPENCODE_WEBSEARCH_PROVIDER=exa` 控制（见 `vendor/opencode/packages/opencode/src/tool/websearch.ts:31-37`）；exa API key 需在 `.opencode/.ai_env` 或 shell 环境配置。Phase 5 实施前需确认 exa API key 可用，否则 searcher 调 websearch 会失败。

### 3.3 实施步骤拆分

> 11 个步骤，每步 ≤ 200 行（不含注释空行），含验证点和依赖关系。
> Phase 5 严格按此顺序执行，禁止合并/跳步。

#### Step 1. 创建 memory MCP server 骨架
- **文件**：`.opencode/mcp-servers/memory/pyproject.toml`、`.opencode/mcp-servers/memory/server.py`、`.opencode/mcp-servers/memory/db.py`
- **预估行数**：~80 行（pyproject 20 + server.py 30 + db.py 30）
- **依赖清单**（pyproject.toml）：`mcp>=1.0`（官方 MCP SDK）、`sentence-transformers>=2.7`（embedding）、`sqlite-vec>=0.1`（向量扩展）
- **验证点**：
  1. `cd .opencode/mcp-servers/memory && python server.py` 启动后 stdio 等待，无错误
  2. MCP `tools/list` 能返回 `search_answer` 和 `store_answer` 两个工具定义
  3. 首次启动 sentence-transformers 模型自动下载完成（或 `~/.cache/huggingface` 已有缓存）
- **依赖**：无
- **范围**：仅骨架，函数体可先 `pass` 或返回固定值；db.py 先建空 SQLite schema

#### Step 2. 实现 memory MCP 的 search_answer + store_answer
- **文件**：`.opencode/mcp-servers/memory/server.py`、`.opencode/mcp-servers/memory/db.py`
- **预估行数**：~180 行（db.py embedding 写入 + 余弦相似度查询 ~100 行；server.py 工具实现 ~80 行）
- **验证点**：
  1. `store_answer(question="OpenSSL Heartbleed", answer="CVE-2014-0160...", type="vulnerability")` 返回成功
  2. `search_answer(questions=["OpenSSL heartbeat bug"], type="vulnerability")` 能检索到上一步写入的记录，相似度分数 > 0.5
  3. 不同 type 过滤生效（store type=vulnerability，search type=code 返回空）
  4. **不做代码层去重**——重复 store 相同内容会生成新记录（与 PentAGI `search.go:217-280` 一致），"是否新知识"由 LLM 决策
- **依赖**：Step 1
- **范围**：SQLite + sqlite-vec 存储 + sentence-transformers `all-MiniLM-L6-v2` embedding

#### Step 3. 创建 graphiti MCP stub
- **文件**：`.opencode/mcp-servers/graphiti/pyproject.toml`、`.opencode/mcp-servers/graphiti/server.py`
- **预估行数**：~120 行（pyproject 20 + server.py 7 个方法签名 × ~10 行 + 描述文本）
- **验证点**：
  1. server.py 启动成功
  2. `tools/list` 返回 7 个工具：`temporal_window_search` / `entity_relationships_search` / `diverse_results_search` / `episode_context_search` / `successful_tools_search` / `recent_context_search` / `entity_by_label_search`（命名严格对齐 `graphiti_search.go:18-24`）
  3. 调用任一方法返回空列表 + `note: "Graphiti not implemented yet"` 字段
- **依赖**：无（与 Step 1/2 并行）
- **范围**：所有方法体 stub，签名齐全，返回结构合法

#### Step 4. 注册 MCP server 到 opencode 配置
- **文件**：`.opencode/mcp.json`（新建）
- **预估行数**：~30 行
- **配置示例**：
  ```json
  {
    "mcpServers": {
      "memory": {
        "type": "stdio",
        "command": "python",
        "args": [".opencode/mcp-servers/memory/server.py"],
        "env": {}
      },
      "graphiti": {
        "type": "stdio",
        "command": "python",
        "args": [".opencode/mcp-servers/graphiti/server.py"],
        "env": {}
      }
    }
  }
  ```
  实际 command/args 路径以 `$OPENCODE_ROOT` 为基准；Windows 下 command 可能是 `python.exe`。
- **验证点**：
  1. OpenCode 启动后 `mcp__memory__*` 和 `mcp__graphiti__*` 工具在所有 agent 的工具集中可见
  2. 从 binary-analysis 调用 `mcp__memory__search_answer` 不报"unknown tool"
  3. MCP server 进程列表能看到两个 python 子进程
- **依赖**：Step 2、Step 3
- **范围**：MCP 配置语法（参考 opencode MCP 规范）

#### Step 5. 写 memorist.md（agent prompt）
- **文件**：`.opencode/agents/memorist.md`、`.opencode/memorist/knowledge-base/retrieval-strategy.md`
- **预估行数**：~180 行（memorist.md ~120 行 + retrieval-strategy.md ~60 行）
- **验证点**：
  1. frontmatter 合法（`mode: subagent`、`buwai-extension-id: memorist`）；**permission 不显式声明 task allow**——memorist 不调 Task 工具（单向调用规则），保留默认禁止即可
  2. 加载到 OpenCode 后 agent 列表可见（虽然 subagent 模式不可被用户直接选）
  3. prompt 全英文，调用的工具名正确（`mcp__memory__search_answer` / `mcp__graphiti__xxx` / Read/Bash/Glob/Grep）
  4. **memorist 不调 searcher、不调 Task 工具**（单向调用规则）
  5. 内容对照 PentAGI `memorist.tmpl`：保留 LONG-TERM MEMORY SPECIALIST 定位、拆分查询策略、合并多源结果；去除 `{{.XXX}}` 占位符、去除匿名化、去除 `{{.SummarizationToolName}}` 摘要感知协议（OpenCode compacting 接管）
  6. **Graphiti 容错策略**：memorist.md prompt 必须明确"Graphiti 返回空列表或 note 字段时跳过该源，转向 memory + Read/Bash"——保证 stub 阶段 memorist 能正常工作
- **依赖**：Step 4（memorist 调用的 MCP 工具必须先可用）
- **范围**：移植 + 适配，不改功能集

#### Step 6. 写 searcher.md（agent prompt）
- **文件**：`.opencode/agents/searcher.md`、`.opencode/searcher/knowledge-base/search-methodology.md`
- **预估行数**：~200 行（searcher.md ~140 行 + search-methodology.md ~60 行）
- **验证点**：
  1. frontmatter 合法（`mode: subagent`、`buwai-extension-id: searcher`、`permission: { task: { "*": allow } }` **必须显式 allow**——根据 `subagent-permissions.ts:18-25`，subagent 默认禁止调 task，不显式 allow 则 searcher 调不动 memorist）
  2. prompt 全英文
  3. 含 `{{searcher-domain:xxx}}` 占位符（待 Step 9 实现展开）
  4. 含 `Task(subagent_type: memorist)` 嵌套调用指令（正确写法）
  5. 来源优先级顺序：**memory (1) → memorist (2) → websearch (3) → webfetch (4) → web_render.py (5) → store_answer (按需)**；**searcher 不直接调 Graphiti**（Graphiti 是 memorist 内部调用，与 PentAGI `tools.go:1460` 一致）
  6. 内容对照 PentAGI `searcher.tmpl`：保留"精英搜索情报 agent"定位、动作经济性（3-5 次搜索封顶）、来源优先级、查询工程、结果交付 SOP；去除 `{{.XXX}}` 占位符、去除强制匿名化、去除摘要感知协议（OpenCode compacting 接管）、去除授权框架段落（防御性分析不需进攻授权）、去除 `{{.ToolPlaceholder}}` 收尾约束（OpenCode Task 工具天然 barrier，无需明文约束）
- **依赖**：Step 4、Step 5（searcher 嵌套调 memorist）
- **范围**：移植 + 适配，不改功能集

#### Step 7. 写 searcher 各领域情报源片段
- **文件**：5 个领域文件 + 1 个兜底文件（共 6 个）：
  - `.opencode/searcher/knowledge-base/domain-sources-binary-analysis.md`
  - `.opencode/searcher/knowledge-base/domain-sources-mobile-analysis.md`
  - `.opencode/searcher/knowledge-base/domain-sources-web-analysis.md`
  - `.opencode/searcher/knowledge-base/domain-sources-ai-security-analysis.md`
  - `.opencode/searcher/knowledge-base/domain-sources-crypto-analysis.md`
  - `.opencode/searcher/knowledge-base/domain-sources-general.md`（兜底，**无 -analysis 后缀**）
- **预估行数**：~180 行（每文件 ~30 行，6 个）
- **验证点**：
  1. 每个文件包含 `<domain_sources>` XML 标签结构（与 PentAGI `<search_tools>` 矩阵风格一致）
  2. 每个文件列出该领域的优先情报源（如 binary 列 NVD/CVE/sploitus/IDA Pro 官方文档/Ghidra 等；web 列 PortSwigger/OWASP/CVE-Web 等）
  3. 文件名与 `SECURITY_AGENTS` 常量值严格对齐（domain-sources-binary-analysis.md 对应 AGENT_BINARY_ANALYSIS="binary-analysis"）；兜底文件固定名 `domain-sources-general.md`
  4. 兜底文件包含跨领域源（wikipedia/stackoverflow/官方文档通用）
- **依赖**：Step 6（searcher.md 中占位符已定义）
- **范围**：纯知识库内容，每文件自包含

#### Step 8. plugin 改造：新增 AGENTS_WITH_DELEGATION_RULES 常量
- **文件**：`.opencode/plugins/lib/constants.ts`
- **预估行数**：~15 行
- **验证点**：
  1. 新增常量 `AGENTS_WITH_DELEGATION_RULES`，值为：
     ```ts
     export const AGENTS_WITH_DELEGATION_RULES = [
       AGENT_BINARY_ANALYSIS,
       AGENT_MOBILE_ANALYSIS,
       AGENT_WEB_ANALYSIS,
       AGENT_AI_SECURITY_ANALYSIS,
       AGENT_CRYPTO_ANALYSIS,
       "searcher",
       "memorist",
     ];
     ```
  2. **不含** `security-analysis-evolve`（开发工具，不参与分析）、**不含** `security-coordinator`（用户决策保留但不参与本期注入）
  3. **关系澄清**：`AGENTS_WITH_DELEGATION_RULES` 不是 `SECURITY_AGENTS` 的超集；`SECURITY_AGENTS` 保持现状不动
  4. `node --check .opencode/plugins/lib/constants.ts` 通过
- **依赖**：无
- **范围**：仅常量定义

#### Step 9. plugin 改造：递归找根 agent + 加载领域片段
- **文件**：`.opencode/plugins/lib/session-manager.ts`、`.opencode/plugins/lib/snippet.ts`
- **预估行数**：~80 行（session-manager 加 `resolveRootSecurityAgent` ~30 行；snippet 加 `loadSnippetFrom(dir, name)` 通用函数或新增 `loadSearcherDomainSnippet` ~20 行；其他辅助 ~30 行）
- **实现要点**：
  - `resolveRootSecurityAgent(sessionID)`：递归遍历 parentID 链，第一个 agentName 在 `SECURITY_AGENTS` 列表里的就是根；找不到返回 null
  - snippet 加载建议**扩展现有 `loadSnippet(name)` 为 `loadSnippet(name, dir?)`**，dir 参数可选、默认 `AGENTS_RULES_DIR`，保持向后兼容（现有 `{{buwai-rule:xxx}}` 调用不变）
- **验证点**：
  1. 单元测试位置：`.opencode/plugins/lib/__tests__/session-manager.test.ts`（按现有 plugin 测试惯例，使用 bun:test）
  2. 构造 mock session 链 A→B→searcher（A、B 都在 SECURITY_AGENTS），`resolveRootSecurityAgent` 返回 A 的 agentName
  3. 走到根 session 不是 SECURITY_AGENTS 时返回 null
  4. searcher session 的根是 binary-analysis 时，`loadSnippet("binary-analysis", searcherKnowledgeBaseDir)` 返回 `domain-sources-binary-analysis.md` 内容
  5. 找不到对应文件时返回 `domain-sources-general.md` 兜底内容
  6. **现有 `loadSnippet(name)` 调用仍正常工作**（向后兼容验证）
- **依赖**：Step 7（领域片段文件已存在）、Step 8（常量已定义）

#### Step 10. plugin 改造：system.transform 注入领域片段 + 委派清单
- **文件**：`.opencode/plugins/security-analysis.ts`
- **预估行数**：~120 行
- **执行流程**（system.transform hook 内）：
  1. 检测当前 agent 是否为 `searcher` → 是则调 `resolveRootSecurityAgent(sessionID)` 找根 agent
  2. 根据根 agent 加载 `domain-sources-<root>.md`，替换 searcher system prompt 中的 `{{searcher-domain:xxx}}` 占位符
  3. 检测当前 agent 是否在 `AGENTS_WITH_DELEGATION_RULES` 列表内 → 是则收集该列表所有成员的 description，注入"可委派 agent 清单"段到 system prompt
- **委派清单内容**：列出所有 `AGENTS_WITH_DELEGATION_RULES` 成员的 name + description（从各 agent .md frontmatter 自动提取），让调用方知道有哪些 agent 可委派。包含 searcher、memorist、5 个领域 agent。**调用方按需选择**——binary-analysis 通常只调 searcher + crypto-analysis，不直接调 memorist（memorist 由 searcher 嵌套调）
- **验证点**：
  1. searcher session 启动时，system prompt 中 `{{searcher-domain:xxx}}` 被替换为对应领域片段内容（用 `debugLog` 看输出）
  2. binary-analysis（或任意 `AGENTS_WITH_DELEGATION_RULES` 成员）的 system prompt 包含"可委派 agent 清单"段，内容从各 agent .md 的 description frontmatter 自动收集
  3. 修改 `.opencode/agents/searcher.md` 的 description 后，下次启动 binary-analysis 看到的清单自动同步
  4. `node --check .opencode/plugins/security-analysis.ts` 通过
- **依赖**：Step 8、Step 9

#### Step 11. 删除 cross-agent-delegation.md + 端到端验证
- **文件**：删除 `.opencode/agents-rules/cross-agent-delegation.md`
- **预估行数**：0 行（删除）
- **验证点**（端到端）：
  1. 启动 OpenCode，让 binary-analysis 委派 searcher 查一个真实 CVE（如 CVE-2014-0160 OpenSSL Heartbleed，公开资料丰富、无敏感争议）
  2. searcher 起手查 memory（空）→ 调 memorist（stub 历史空）→ websearch → webfetch NVD → store_answer 沉淀 → 返回总结
  3. 再次查同一 CVE → searcher 起手查 memory 命中，跳过 websearch（动作经济性生效）
  4. binary-analysis 的 system prompt 含委派清单
  5. searcher 被 binary-analysis 调用时含 binary 领域情报源片段
  6. **现有 5 个领域 agent 回归**：用 binary-analysis 跑一次典型任务（如对一个简单 ELF 调 `initial_analysis.py` + 查一两个函数），结果与改动前一致
  7. **验证 searcher 工具集**：grep searcher.md 实际生成的工具调用，不应出现 `mcp__graphiti__` 工具**调用**（提及工具名作说明可以，但不能作为 searcher 自己的工具调用）
- **依赖**：Step 1-10 全部完成

---

## §4 验收标准

### 4.1 功能验收

| 验收项 | 验证方式 |
|---|---|
| memory MCP server 启动 | `python .opencode/mcp-servers/memory/server.py` 不报错，stdio 等待 |
| `search_answer` 空库查询 | 返回空列表，无错误 |
| `store_answer` 写入后查询 | 写入 1 条 → `search_answer` 能检索到 |
| graphiti MCP stub | 7 个方法都能调用，全部返回空列表 + 注释说明 |
| searcher agent 加载 | OpenCode 启动无报错，`@searcher` 不可见（mode: subagent） |
| memorist agent 加载 | 同上 |
| searcher 调 memorist | searcher.md 中调 `Task(subagent_type: memorist)` 可正常嵌套 |
| searcher 全链路 | binary-analysis 委派 searcher 查一个真实 CVE，能拿到结果并沉淀 |
| 领域片段注入 | searcher 被 binary-analysis 调用时，system prompt 中能看到 binary 领域的情报源清单 |
| 委派清单注入 | binary-analysis 的 system prompt 中包含"可委派 agent"清单 |
| websearch 可用 | searcher 调 `websearch` 工具能正常返回结果（需 `OPENCODE_WEBSEARCH_PROVIDER=exa` + 有效 exa API key） |

### 4.2 回归验收

| 验收项 | 验证方式 |
|---|---|
| 现有 5 个领域 agent 正常工作 | 跑一次典型分析任务（如 binary-analysis 查一个函数），结果与改动前一致 |
| 现有 agents-rules 片段展开正常 | `{{buwai-rule:xxx}}` 仍正确展开（系统未破坏 snippet 加载） |
| Plugin 加载正常 | OpenCode 启动时无 plugin 错误日志 |
| MCP server 不影响主进程 | server 崩溃时主 agent 仍能工作（MCP 调用失败优雅降级） |

### 4.3 架构验收

| 验收项 | 验证方式 |
|---|---|
| 依赖方向 | MCP server 不 import plugin 代码；plugin 通过 MCP 协议调用 server |
| 文件位置 | 所有文件在 §2.4 清单指定的路径，无散落 |
| 占位符命名 | `{{buwai-rule:xxx}}` 和 `{{searcher-domain:xxx}}` 不冲突 |
| 命名一致性 | `AGENTS_WITH_DELEGATION_RULES` 与 `SECURITY_AGENTS` 不冲突（两者交集为 5 个领域 agent；前者独有 searcher/memorist，后者独有 security-analysis-evolve/security-coordinator） |

---

## §5 与现有需求文档的关系

- **本期是 PentAGI 进化的第一个 agent**（searcher + memorist），是标杆
- 后续 PentAGI 其他 agent（adviser/enricher/reflector/installer/coder/pentester/generator/refiner 等）可参考本期架构：
  - MCP 化的工具沉淀模式
  - plugin 按根 agent 注入领域片段的机制
  - 全英文 agent prompt 的规范
- **不冲突的需求**：
  - `2026-05-22-security-coordinator.md`（用户已决策保留 coordinator，本期不动）
  - `2026-05-03-agent-prompt-snippets.md`（snippet 机制本期复用并扩展，方向一致）
  - `2026-06-13-analysis-persistence.md`（任务持久化机制本期不动，memorist 通过 Read/Bash 读取任务目录复用现有持久化）
