# Knowledge MCP 工具简化：7 工具 → 3 工具，去 type 分类

## §1 背景与目标

### 1.1 来源

本轮进化讨论中发现 knowledge MCP 的工具设计存在 8 个具体混乱点（详见 §1.2），核心问题是 PentAGI 遗留的多 doc_type + 多 type 分层设计在我们语境下全面失配。

### 1.2 问题清单

| # | 问题 | 代码位置 |
|---|------|---------|
| 1 | answer type="guide" vs doc_type="guide" 撞名 | server.py:99 vs server.py:141 |
| 2 | answer type="code" vs doc_type="code" 撞名 | server.py:99 vs server.py:181 |
| 3 | answer 和 guide 的 type 枚举完全不重叠（语义却有重叠） | server.py:99 vs server.py:141 |
| 4 | store_code 有 dead parameter `description`（接收但从不入库） | server.py:199-214 |
| 5 | guide_type 列利用率极低（仅 doc_type=guide 使用） | db.py:48 |
| 6 | type 硬过滤反而伤召回（标签错配=永久丢失） | db.py:198-200 |
| 7 | db.search 三套过滤逻辑（type/guide_type/code_lang）参数膨胀 | db.py:149-157 |
| 8 | knowledge 与 code 二分边界模糊（文字/代码比例连续渐变） | 设计层 |

### 1.3 根因

PentAGI 设计假设"人工管理清晰分类"，但我们完全靠 LLM 主观判断 type。type 标签不稳定 → 硬过滤引入假阴性（该召回的被丢弃）→ 召回率反而下降。

BGE-M3 的语义搜索 + question 自然语言表述已携带类型信号，不需要额外 type 标签。

### 1.4 目标

将 7 工具简化为 3 工具：

| 现状（7 工具） | 目标（3 工具） |
|---------------|---------------|
| search_answer / store_answer | search_knowledge / store_knowledge |
| search_guide / store_guide | （合并到 knowledge） |
| search_code / store_code | （合并到 knowledge，lang 改可选） |
| search_in_memory | search_in_memory（不变） |

**收益**：
- 工具数 -57%（7→3）
- LLM store 决策从 2 步（选 doc_type + 选 type）→ 0 步
- 消除所有 type 撞名和主观判断
- 消除 type 硬过滤导致的假阴性
- 信息零损失（question + content + lang 可选 保留所有信号）

### 1.5 检索质量论证

三合一不会降低检索质量，反而可能提升：

1. **消除假阴性**：type 标签错配导致的永久丢失彻底消失
2. **BGE-M3 足够**：中小规模下语义排序精度不亚于 type 过滤
3. **question 携带类型语义**："RSA 弱参数的攻击方法" 自然匹配漏洞类 content
4. **跨类型结果有益**：搜"SQL 注入"返回原理+工具+代码是 feature
5. **长期兜底**：大规模时引入 reranker（软排序）比 type 硬过滤更优雅

---

## §2 技术方案

### 2.1 新工具签名

```python
# Tool 1: 搜索知识（合并 answer + guide + code）
@mcp.tool(description="从向量库检索已有知识。必须首先调用，避免重复研究。返回最多 5 条语义相似的结果。")
async def search_knowledge(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句。")],
    lang: Annotated[str, Field(description="可选：按编程语言过滤（如 python、bash）。不传则搜全部。")] = "",
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:

# Tool 2: 存储知识（合并 answer + guide + code）
@mcp.tool(description="存储新知识到向量库供未来检索。仅在发现知识库中不存在的新知识时调用。存储前自动匿名化。")
async def store_knowledge(
    question: Annotated[str, Field(description='关联问句。用"未来谁会查这条知识、他会怎么问"的角度表述（中文）。')],
    content: Annotated[str, Field(description="知识正文（中文叙述）。英文技术标识符原样保留。代码片段需附带文字说明。存储前自动匿名化。")],
    lang: Annotated[str, Field(description="可选：内容主要语言的编程语言标记（如 python、bash）。纯文字知识不传。")] = "",
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:

# Tool 3: 搜索执行记忆（不变）
@mcp.tool(description="从向量库检索执行记忆（doc_type=memory）。用于回顾当前任务中执行过哪些工具、得到了什么结果。按 flow_id 隔离，只返回当前任务的记录。")
async def search_in_memory(
    questions: Annotated[list[str], Field(description="1-5 个中文语义查询问句，关于之前的工具执行和结果。")],
    flow_id: Annotated[str | None, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。")] = None,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
```

### 2.2 数据库层改动

**Schema 不变**（向后兼容），但新数据的写入规则改变：

| 列 | 现状 | 改后 |
|----|------|------|
| `doc_type` | answer/guide/code/memory | **knowledge/memory**（新数据只写这两种） |
| `type` | 各种枚举值 | 弃用：INSERT 时写 doc_type 的值（如 `'knowledge'`），不再有独立语义 |
| `guide_type` | install/configure/... | 弃用：INSERT 时写空字符串 `''` |
| `code_lang` | python/bash/... | 列名不变（仍叫 `code_lang`），Python 参数名改叫 `lang` |
| `flow_id` | memory 用 | 不变 |

**db.search 签名简化**：

```python
# 改前
def search(self, questions, type=None, doc_type="answer", guide_type="", code_lang="", top_k=5, flow_id=None)

# 改后
def search(self, questions, doc_type="knowledge", lang="", top_k=5, flow_id=None)
```

**db.store 签名简化**：

```python
# 改前
def store(self, question, answer, type, doc_type="answer", guide_type="", code_lang="", flow_id=None)

# 改后：type 列在 INSERT 时写 doc_type 的值；guide_type 列写空字符串；code_lang 列写 lang 值
def store(self, question, content, doc_type="knowledge", lang="", flow_id=None)
```

**旧 doc_type 兼容策略**：

当前 knowledge.db 是空的（clean_databases.py 清理过），不存在旧数据兼容问题。新数据统一写 `doc_type='knowledge'`，search_knowledge 只搜 `doc_type='knowledge'`。

如果未来有人在旧版本上存了数据再升级（doc_type='answer'/'guide'/'code'），这些旧数据不会被 search_knowledge 搜到——这是已知限制，可接受（建议升级前跑 clean_databases.py）。

### 2.3 删除的内容

- `VALID_ANSWER_TYPES` 常量（server.py:35）
- `VALID_GUIDE_TYPES` 常量（server.py:36）
- 所有 type 参数和枚举
- store_code 的 dead parameter `description`
- db.py 中 type/guide_type 的过滤逻辑

### 2.4 向后兼容

当前 knowledge.db 是空的（clean_databases.py 清理过），**零迁移成本**。

旧列（type, guide_type, code_lang）保留不删，避免 schema 变更风险。新数据按 §2.2 规则写入弃用列。

**clean_databases.py 不需要改**：它只做 `DELETE FROM answers` + `DELETE FROM answer_vectors`，不涉及工具名或 doc_type 逻辑。

---

## §3 实现规范

### 3.1 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `mcp-servers/knowledge/db.py` | 简化 search/store 签名 + docstring | ~50 行改 |
| `mcp-servers/knowledge/memory_writer_daemon.py` | db.store 调用签名同步 | ~5 行改 |
| `mcp-servers/knowledge/server.py` | 重写工具定义（7→3） | ~150 行改 |
| `test/knowledge/test_knowledge_mcp.py` | 测试适配新 API | ~150 行改 |
| `test/knowledge/test_complex_scenarios.py` | 测试适配新 API（合并 answer/guide/code 测试） | ~100 行改 |
| `test/knowledge/test_lazy_loading.py` | 工具名 + 参数适配 | ~20 行改 |
| `test/knowledge/test_unit_await_behavior.py` | 工具名 + 参数适配 | ~10 行改 |
| `agents-rules/knowledge-management.md` | 更新查/存指引 | ~30 行改 |
| `agents/searcher.md` | 去掉 answer/guide/code 决策树 | ~40 行改 |
| `agents/security-coordinator.md` | 1 处引用更新 | ~1 行改 |
| `docs/项目介绍/知识与记忆体系.md` | 架构图/职责表更新 | ~50 行改 |

**不改的文件**：
- `tools/clean_databases.py`：只做 DELETE，不涉及工具名
- `plugins/security-analysis.ts`：白名单按工具名过滤（MEMORY_ALLOWED_TOOLS），不涉及 knowledge 工具名
- `mcp-servers/knowledge/anonymizer.py`：匿名化逻辑不变

### 3.2 §3.1 实施步骤拆分

#### Step 1. db.py 签名简化 + docstring

- **文件**: `mcp-servers/knowledge/db.py`
- **预估行数**: ~50 行改
- **改动**:
  - 模块 docstring（1-25 行）：4 种 doc_type → 2 种（knowledge/memory）；删除 answer/guide/code 分别描述
  - `store()` 签名：去 `type`/`guide_type` 参数，`answer` 改名 `content`，`code_lang` 改名 `lang`，`doc_type` 默认值改 `"knowledge"`
  - `store()` 内部 INSERT：type 列写 doc_type 值，guide_type 列写 `''`，code_lang 列写 lang 值
  - `search()` 签名：去 `type`/`guide_type` 参数，`code_lang` 改名 `lang`，`doc_type` 默认值改 `"knowledge"`
  - search 内过滤逻辑：删除 type/guide_type 条件分支，保留 lang→code_lang 条件
- **验证点**: `python -c "compile(open('db.py').read(), 'db.py', 'exec')"` 语法通过
- **依赖**: 无

#### Step 2. memory_writer_daemon.py 同步 db.store 调用

- **文件**: `mcp-servers/knowledge/memory_writer_daemon.py`
- **预估行数**: ~10 行改
- **改动**:
  - 第 47-53 行 `db.store()` 调用：
    - `answer=answer` → `content=answer`
    - 删除 `type=tool_type` 参数
    - **tool_type 信息保留方案**：把 tool_type 拼进 question 前缀，避免信息丢失。改后：`question = f"[{tool_type}] {question}" if tool_type else question`
    - 这样 tool_type（如 "bash"/"read"）仍可通过语义搜索匹配（搜"bash 执行结果"会命中 `[bash] ...` 前缀）
- **验证点**: `python -c "compile(open('memory_writer_daemon.py').read(), 'memory_writer_daemon.py', 'exec')"` 语法通过
- **依赖**: Step 1

#### Step 3. server.py 合并 answer+guide+code 为 knowledge 工具

- **文件**: `mcp-servers/knowledge/server.py`
- **预估行数**: ~150 行改
- **改动**:
  - 模块 docstring（1-16 行）：7 工具 → 3 工具
  - 删除 `VALID_ANSWER_TYPES` / `VALID_GUIDE_TYPES` 常量（35-36 行）
  - 删除 6 个工具函数：search_answer/store_answer/search_guide/store_guide/search_code/store_code（91-216 行）
  - 新增 2 个工具函数：search_knowledge/store_knowledge（签名见 §2.1）
  - 保留 search_in_memory 不变（222-238 行）
- **验证点**:
  - `python -c "compile(open('server.py').read(), 'server.py', 'exec')"` 语法通过
  - `grep -E "search_answer|store_answer|search_guide|store_guide|search_code|store_code|VALID_ANSWER_TYPES|VALID_GUIDE_TYPES" server.py` 无匹配
- **依赖**: Step 1

#### Step 4. 测试文件适配新 API

- **文件**: `test/knowledge/test_knowledge_mcp.py`
- **预估行数**: ~150 行改
- **改动**:
  - **不改**：TestAnonymizerPatterns + TestAnonymizerEdgeCases（匿名化测试，与工具签名无关）
  - TestDbEmbedContent：`db.store(question, answer, type)` → `db.store(question, content)`；`db.search(type=)` → `db.search()`
  - TestDbDocTypeIsolation：删除 test_answer_search_excludes_guide（doc_type 不再区分 answer/guide）；保留 test_memory_search_excludes_answer（memory 隔离仍有效）
  - TestDbGuideCodeFilters：删除 test_guide_type_filter（guide_type 不再存在）；test_code_lang_filter 改为 lang 过滤测试
  - TestDbMultiQuery：`type=` 参数删除
  - TestDbMigration：`type=` 参数删除；验证旧列仍存在
  - TestServerToolsDirect：store_answer/search_answer/store_guide/search_guide/store_code/search_code → store_knowledge/search_knowledge；删除 description 参数
  - TestServerEnumAlignment：整个 class 删除（枚举不再存在）
  - test_all_7_tools_exist → test_all_3_tools_exist（验证 search_knowledge/store_knowledge/search_in_memory）
- **验证点**: `python -m pytest test/knowledge/test_knowledge_mcp.py -x` 全部通过
- **依赖**: Step 1, 3

#### Step 5. agent prompt 更新

- **文件**: `agents-rules/knowledge-management.md`、`agents/searcher.md`、`agents/security-coordinator.md`
- **预估行数**: ~70 行改
- **改动**:
  - `knowledge-management.md`：查/存指引统一为 search_knowledge/store_knowledge；去掉 search_guide/search_code/store_guide/store_code/store_answer 引用；保留"委派 searcher 查" + "直接调查" + "存"三段结构
  - `searcher.md`：去掉 answer/guide/code 决策树，改为统一的 search_knowledge 流程；store 决策树简化为 store_knowledge（可选 lang）
  - `security-coordinator.md:147`：store_answer → store_knowledge
- **验证点**: `grep -rE "search_answer|store_answer|search_guide|store_guide|search_code|store_code" agents/ agents-rules/` 无匹配
- **依赖**: Step 3

#### Step 6. 文档更新

- **文件**: `docs/项目介绍/知识与记忆体系.md`
- **预估行数**: ~50 行改
- **改动**:
  - §1 知识与记忆体系全景：工具列表从 7 个改为 3 个
  - §1.5 谁读、何时读：knowledge 统一描述
  - §3.1 数据流图：工具调用路径更新
  - §3.3 Agent 职责分工表：合并列
- **验证点**: `grep -E "search_answer|store_answer|search_guide|store_guide|search_code|store_code" docs/项目介绍/知识与记忆体系.md` 无匹配
- **依赖**: Step 5

#### Step 7. 端到端验证

- **文件**: 无（验证步骤）
- **预估行数**: 0
- **验证点**:
  - `cd /Users/aserlili/Documents/Codes/OpenSecurity2 && opencode serve` 启动成功
  - 日志确认 knowledge MCP connected
  - MCP tools/list 返回 3 个工具：search_knowledge、store_knowledge、search_in_memory
  - LLM 调用 store_knowledge + search_knowledge 端到端成功
  - LLM 调用 search_in_memory 端到端成功
  - 验证后清理 .id0/.id1/.nam/.til 临时文件（如有）
- **依赖**: Step 1-6

---

## §4 验收标准

### 4.1 功能验收

| ID | 验收项 | 验证方式 |
|----|--------|---------|
| F1 | search_knowledge 工具存在 | MCP tools/list 包含 search_knowledge |
| F2 | store_knowledge 工具存在 | MCP tools/list 包含 store_knowledge |
| F3 | search_in_memory 工具存在且不变 | MCP tools/list 包含 search_in_memory |
| F4 | 旧工具不存在 | MCP tools/list 不含 search_answer/store_answer/search_guide/store_guide/search_code/store_code |
| F5 | store_knowledge + search_knowledge 端到端 | store 后 search 能命中 |
| F6 | store_knowledge(lang=python) + search_knowledge(lang=python) | 按 lang 过滤生效 |
| F7 | search_knowledge(lang="") 不过滤 | 返回所有语言的知识 |
| F8 | store_knowledge 自动匿名化 | 存入含 IP 内容后，DB 中无原始 IP |
| F9 | search_in_memory 按 flow_id 隔离 | 不同 flow_id 互不可见 |
| F10 | 单元测试全部通过 | `python -m pytest test/knowledge/test_knowledge_mcp.py -x` 退出码 0 |

### 4.2 回归验收

| ID | 验收项 | 验证方式 |
|----|--------|---------|
| R1 | BGE-M3 lazy 加载仍正常 | 首次调用 < 模型加载时间，第二次调用 < 0.5s |
| R2 | memory 自动写入仍正常（plugin fireAndForgetMemory） | bash 执行后 search_in_memory 能命中 |
| R3 | plugin message 消费仍正常 | tool.execute.after 从 message 参数写 timeline |
| R4 | database schema 向后兼容 | 旧列（type/guide_type/code_lang）仍存在 |
| R5 | clean_databases.py 仍正常 | 清理脚本无报错 |

### 4.3 架构验收

| ID | 验收项 |
|----|--------|
| A1 | 工具数从 7 减少到 3 |
| A2 | 无 type 参数暴露给 LLM |
| A3 | 无 type 撞名（guide/code） |
| A4 | lang 为可选参数 |
| A5 | db.search 参数从 7 个减少到 5 个 |
| A6 | 无 dead parameter（description 删除） |

---

## §5 与现有需求文档的关系

| 现有需求文档 | 关系 |
|-------------|------|
| `2026-07-09-searcher-agent.md` | searcher 仍存在，工具从 search_answer 改为 search_knowledge |
| `2026-07-19-knowledge-mcp-align-pentagi.md` | **部分推翻**：不再对齐 PentAGI 的 answer/guide/code 三分类 |
| `2026-07-19-knowledge-mcp-lazy-loading.md` | **保留**：lazy 加载机制不变 |
| `2026-07-20-knowledge-management-loop.md` | **更新**：查/存指引工具名变更 |
| `2026-07-20-memory-flowid-isolation.md` | **保留**：flow_id 隔离机制不变 |
| `2026-07-21-mcp-desc-cn-message-dedup.md` | **保留**：中文描述 + message 参数不变 |
| `2026-07-21-search-guide-code-guidance.md` | **部分推翻**：search_guide/search_code 不再存在，领域 agent 直接调 search_knowledge |

**注意**：历史需求文档作为决策记录保留不改。本次改动的真相以本文档为准。
