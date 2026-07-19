# Knowledge MCP 对齐 PentAGI 向量库能力

## §1 背景与目标

### 来源痛点

Knowledge MCP 与 PentAGI 的向量库实现存在 7 项差异，导致检索质量低、功能缺失：

| # | 差异 | 根因 |
|---|------|------|
| 1 | embed question 而非 content | db.py 实现时误将 question 作为 embedding 目标 |
| 2 | 无 score 阈值过滤 | 未实现 PentAGI 的 0.2 阈值 |
| 3 | memory 无自动写入 | 缺失 executor 自动写入工具执行结果的路径 |
| 4 | 缺 guide 类别 | 未实现 search_guide/store_guide |
| 5 | 缺 code 类别 | 未实现 search_code/store_code |
| 6 | 缺匿名化 | 未实现 PentAGI 的 replacer 服务端清洗 |
| 7 | docstring 过时 | 384 维注释未更新为 1024 |

### 预期收益

| 维度 | 改进前 | 改进后 |
|------|--------|--------|
| 检索召回率 | 低（embed question，query 措辞不同就搜不到） | 高（embed content，按内容语义匹配） |
| 搜索噪音 | 高（无阈值过滤，0.1 分的结果也返回） | 低（0.2 阈值过滤） |
| 知识类别 | 2 种（answer/memory） | 4 种（answer/memory/guide/code） |
| 安全 | 无（敏感信息直接入库） | 有（IP/凭证/域名匿名化） |
| 执行记忆 | 只有 Graphiti | Graphiti + 向量库（对齐 PentAGI） |

---

## §2 技术方案

### 2.1 修改 db.py

#### 改动 1：embed content 而非 question

```python
def store(self, question, answer, type, doc_type="answer"):
    # 改动前：embedding = self._embed(question)
    embedding = self._embed(answer)  # ← embed content
```

PentAGI 的 store_answer 用 `documentloaders.NewText(anonymizedAnswer).Load()` → embed 的是 answer 文本。question 存在元数据里不 embed。

#### 改动 2：加 score 阈值过滤

```python
SCORE_THRESHOLD = 0.2  # 对齐 PentAGI

def search(self, ...):
    ...
    for row_id, distance in rows:
        score = 1.0 - float(distance)
        if score < SCORE_THRESHOLD:  # ← 新增过滤
            continue
        ...
```

#### 改动 3：加 guide_type/code_lang 列

已有数据库需要迁移（SQLite 不支持 `ADD COLUMN IF NOT EXISTS`）：

```python
def _migrate_schema(self):
    """检查并添加缺失的列（向后兼容）。"""
    columns = {row[1] for row in self._conn.execute("PRAGMA table_info(answers)").fetchall()}
    if "guide_type" not in columns:
        self._conn.execute("ALTER TABLE answers ADD COLUMN guide_type TEXT DEFAULT ''")
    if "code_lang" not in columns:
        self._conn.execute("ALTER TABLE answers ADD COLUMN code_lang TEXT DEFAULT ''")
    self._conn.commit()
```

`store()` 方法签名加可选参数（向后兼容）：
```python
def store(self, question, answer, type, doc_type="answer", guide_type="", code_lang=""):
```

search 方法加 guide_type/code_lang 过滤参数。

#### 改动 4：修 docstring

384 维 → 1024 维。

### 2.2 修改 server.py

#### 新增工具：search_guide / store_guide

```python
@mcp.tool(description="Search guides by type (install/configure/use/pentest/development/other)")
def search_guide(questions: list[str], type: str, message: str = "") -> str:
    ...

@mcp.tool(description="Store a guide for future retrieval")
def store_guide(guide: str, question: str, type: str, message: str = "") -> str:
    ...
```

guide_type 枚举：install, configure, use, pentest, development, other

#### 新增工具：search_code / store_code

```python
@mcp.tool(description="Search code samples by programming language")
def search_code(questions: list[str], lang: str, message: str = "") -> str:
    ...

@mcp.tool(description="Store a code sample for future retrieval")
def store_code(code: str, question: str, lang: str, explanation: str, description: str, message: str = "") -> str:
    ...
```

#### store 工具加匿名化

store_answer/store_guide/store_code 在存储前调 `anonymize()` 清洗文本。

### 2.3 新建 anonymizer.py

PentAGI 用 `vxcontrol/cloud/anonymizer`（300+ 正则模式）。我们用 Python 正则实现核心子集：

```python
PATTERNS = [
    # IP 地址
    (r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '<IP>'),
    # 邮箱
    (r'[\w.-]+@[\w.-]+\.\w+', '<EMAIL>'),
    # API key（常见格式）
    (r'sk-[a-zA-Z0-9]{20,}', '<API_KEY>'),
    (r'AKIA[A-Z0-9]{16}', '<AWS_KEY>'),
    # 密码/凭证
    (r'(?:password|passwd|pwd|secret|token)\s*[=:]\s*\S+', '<CREDENTIAL>'),
    # 域名（收紧：只匹配独立域名，不匹配 URL/路径内的）
    (r'(?<![\w/.])(?:[\w-]+\.)+(com|net|org|io|cn|ru)(?![\w/])', '<DOMAIN>'),
]

def anonymize(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text
```

不实现 PentAGI 的 300+ 模式全集——核心安全模式（IP/email/key/credential）足够。

### 2.4 修改 security-analysis.ts — memory 自动写入

PentAGI 的 executor 在工具执行后自动把结果写入向量库（doc_type=memory）。我们在 `tool.execute.after` hook 里加同样的逻辑：

```typescript
// security-analysis.ts tool.execute.after hook
if (toolName !== "task") {
    // 已有：写 events MCP（Graphiti）
    fireAndForgetEvent(...);

    // 新增：写 knowledge MCP（向量库 memory）
    fireAndForgetMemory(toolName, args, output, session.flowId);
}
```

memory 写入不含匿名化（对齐 PentAGI 的 executor.go storeToolResult）。

**写入方式**：通过 subprocess 调 Python 脚本写 SQLite（和 fireAndForgetEvent 模式一致）。不通过 MCP API——MCP server 是独立的 stdio 进程，plugin 无法直接调用其内部函数。

**文本分块**（对齐 PentAGI 的 textsplitter）：
- PentAGI 用 RecursiveCharacterTextSplitter（chunk_size=2000, overlap=100）
- 我们简化：按 2000 字符分块，不重叠（避免引入 langchain 依赖）
- 每个分块单独 embed + store，`part_size` 记录分块大小，`total_size` 记录原文总大小

PentAGI 自动写入 memory 的工具列表（对齐）：
- terminal, file, search engines, coder, pentester, advice, sploitus, maintenance

我们的对应列表：
- bash（=terminal）, read/write/edit（=file）, webfetch, websearch（=search engines）, task 子 agent 响应（=coder/pentester/advice）

---

## §3 实现规范

### 3.1 实施步骤拆分

#### 步骤 1：db.py — embed content + score 阈值 + docstring
- 文件：改 `.opencode/mcp-servers/knowledge/db.py`
- 改动：`store()` 改 embed answer；`search()` 加 `SCORE_THRESHOLD = 0.2` 过滤；修 docstring
- 预估行数：~15 行
- 验证点：`python -c "import db; ..."` 语法通过 + store 后 search 验证 embed 目标
- 依赖：无

#### 步骤 2：db.py — 加 guide_type/code_lang 列
- 文件：改 `.opencode/mcp-servers/knowledge/db.py`
- 改动：SCHEMA_SQL 加两列；`store()` 加可选参数；`search()` 加过滤参数
- 预估行数：~20 行
- 验证点：语法通过 + store guide/code 后能按 type/lang 过滤搜索
- 依赖：步骤 1

#### 步骤 3：anonymizer.py — 匿名化模块
- 文件：新建 `.opencode/mcp-servers/knowledge/anonymizer.py`
- 预估行数：~40 行
- 验证点：`python -c "from anonymizer import anonymize; print(anonymize('IP: 192.168.1.1'))"` 输出 `<IP>`
- 依赖：无

#### 步骤 4：server.py — search_guide/store_guide
- 文件：改 `.opencode/mcp-servers/knowledge/server.py`
- 改动：加两个 MCP 工具 + store 前调 anonymize
- 预估行数：~40 行
- 验证点：语法通过 + 工具签名含 guide_type 参数
- 依赖：步骤 2 + 3

#### 步骤 5：server.py — search_code/store_code
- 文件：改 `.opencode/mcp-servers/knowledge/server.py`
- 改动：加两个 MCP 工具 + store 前调 anonymize
- 预估行数：~40 行
- 验证点：语法通过 + 工具签名含 lang 参数
- 依赖：步骤 2 + 3

#### 步骤 6：server.py — store_answer 加匿名化
- 文件：改 `.opencode/mcp-servers/knowledge/server.py`
- 改动：store_answer 调用前 anonymize(question) + anonymize(answer)
- 预估行数：~5 行
- 验证点：存入的文本不含原始 IP/凭证
- 依赖：步骤 3

#### 步骤 7：security-analysis.ts — memory 自动写入
- 文件：改 `.opencode/plugins/security-analysis.ts`
- 改动：tool.execute.after hook 里加 memory 写入。通过 subprocess spawn Python 脚本写 SQLite（和 fireAndForgetEvent 模式一致）。文本按 2000 字符分块，每块单独 embed + store。
- 预估行数：~40 行（含分块逻辑 + subprocess 调用）
- 验证点：工具执行后 knowledge DB 有 doc_type=memory 记录
- 依赖：步骤 1（db.py store 支持 doc_type=memory + guide_type/code_lang 可选参数）

#### 步骤 8：agent prompt 更新
- 文件：改 `.opencode/agents/searcher.md` + `.opencode/agents/memorist.md`
- searcher.md 改动：加 search_guide/store_guide/search_code/store_code 的使用指引和决策树位置；更新工具参数说明
- memorist.md 改动：更新 search_in_memory 描述（memory 自动写入后有真实数据，不再是 stub）
- 预估行数：~40 行
- 验证点：prompt 含新工具名 + 决策树引用新工具
- 依赖：步骤 4+5（工具存在）

#### 步骤 9：test 更新
- 文件：改/新建 `test/knowledge/` 下测试
- 预估行数：~60 行
- 验证点：新工具可调用 + embed 目标正确 + 匿名化生效 + memory 自动写入
- 依赖：全部步骤

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | embed content 而非 question | store 后 search 用不同措辞的 query 能搜到（因 content 匹配） |
| F2 | score < 0.2 的结果被过滤 | store 1 条，search 不相关 query，返回空 |
| F3 | guide 工具可用 | store_guide + search_guide 端到端 |
| F4 | code 工具可用 | store_code + search_code 端到端 |
| F5 | 匿名化生效 | store 含 IP 的文本，搜索结果里 IP 被替换为 `<IP>` |
| F6 | memory 自动写入 | 执行 bash 工具后，knowledge DB 有 doc_type=memory 记录 |
| F7 | memory 可搜索 | search_in_memory 能搜到自动写入的 memory |
| F8 | agent prompt 含新工具指引 | searcher.md 含 search_guide/store_guide/search_code/store_code 使用说明 |
| F9 | memorist prompt 更新 | memorist.md 不再说 search_in_memory "可能返回空" |

### 回归验收

| # | 验收项 |
|---|--------|
| R1 | 原有 search_answer/store_answer 正常工作 |
| R2 | 原有 search_in_memory 正常工作 |
| R3 | events MCP 不受影响 |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | db.py schema 变更向后兼容（ALTER TABLE 加列，不破坏旧数据） |
| A2 | 匿名化只在 agent 发起的 store 时执行，memory 自动写入不匿名化 |
| A3 | guide_type 枚举与 PentAGI 一致（install/configure/use/pentest/development/other） |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-18-events-mcp-model-replacement.md` | 独立——events MCP 的 LLM 改造已完成 |
| `2026-07-09-searcher-agent.md` | 相关——searcher agent 使用 knowledge MCP，改进后检索质量提升 |
