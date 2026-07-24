# memory doc_type 按 flow_id 隔离 + 白名单过滤（对齐 PentAGI）

## §1 背景与目标

### 来源痛点

调研 PentAGI 源码发现我们的 memory（执行记忆）与 PentAGI 存在两个差距：

| # | 差距 | PentAGI | 我们当前 | 影响 |
|---|------|---------|---------|------|
| 1 | **memory 缺 flow_id 隔离** | `filters["flow_id"] = m.flowID`（按任务隔离） | 全局共享（无 flow_id） | 不同任务的工具结果混在一起，搜索时互相污染 |
| 2 | **memory 缺白名单过滤** | `allowedStoringInMemoryTools` 白名单（只存有信息价值的工具） | 所有工具都存 | read/write/edit/mcp__* 等无知识价值的操作也被存入 |

### PentAGI 源码依据

**flow_id 隔离**（memory.go:62-68）：
```go
filters := map[string]any{
    "flow_id":  strconv.FormatInt(m.flowID, 10),
    "doc_type": memoryVectorStoreDefaultType,
}
```

**白名单**（registry.go:149-163）：
```go
var allowedStoringInMemoryTools = []string{
    TerminalToolName,    // terminal 命令执行
    FileToolName,        // 文件读取
    SearchToolName,      // searcher 委派结果
    GoogleToolName,      // 搜索引擎
    // ... 其他搜索引擎
    CoderToolName,       // coder 委派结果
    PentesterToolName,   // pentester 委派结果
    AdviceToolName,      // adviser 委派结果
}
```

### 我们的工具白名单（对齐映射）

| PentAGI 工具 | 我们的工具 | 存？ | 理由 |
|-------------|----------|------|------|
| Terminal | `bash` | ✅ | 命令输出有技术价值（nmap/frida/idat） |
| File | `read` | ✅ | 文件内容可能有价值（IDA 输出/配置/源码） |
| Search/Coder/Pentester/Advice | `task` | ✅ | 子 agent 返回的精炼结果 |
| Google/DuckDuckGo/Sploitus | `websearch` / `webfetch` | ✅ | 外部知识 |
| — | `write` / `edit` | ❌ | 写操作不是知识 |
| — | `glob` / `grep` | ❌ | 搜索操作不是知识 |
| search_guide/store_guide | `mcp__knowledge__*` | ❌ | 向量库操作本身（循环存储） |
| graphiti_search | `mcp__events__*` | ❌ | 事件库操作本身（循环存储） |

### 改造目标

1. memory 存储 + 搜索按 flow_id 隔离
2. fireAndForgetMemory 加白名单过滤
3. 不改 answer/guide/code（已对齐 PentAGI，全局共享不变）

---

## §2 技术方案

### 2.1 db.py — answers 表加 flow_id 列

```python
# 迁移：加 flow_id 列
MIGRATE_COLUMNS = [
    ("guide_type", "TEXT NOT NULL DEFAULT ''"),
    ("code_lang", "TEXT NOT NULL DEFAULT ''"),
    ("flow_id", "TEXT NOT NULL DEFAULT ''"),  # ← 新增
]

# store() 加 flow_id 参数
def store(self, question, answer, type, doc_type="answer", guide_type="", code_lang="", flow_id=""):
    # flow_id 写入 answers 表

# search() 加 flow_id 参数
def search(self, questions, type=None, doc_type="answer", guide_type="", code_lang="", top_k=5, flow_id=None):
    # 仅 doc_type="memory" 时按 flow_id 过滤
    if doc_type == "memory" and flow_id is not None:
        conditions.append("flow_id = ?")
        params.append(flow_id)
```

**关键设计**：
- flow_id 默认空字符串（兼容已有数据）
- answer/guide/code 的 flow_id 始终为空（全局共享）
- memory 的 flow_id 存当前任务的 flow_id（按任务隔离）
- search 时仅 doc_type=memory 且 flow_id 非 None 时才过滤

### 2.2 security-analysis.ts — fireAndForgetMemory 加白名单 + flow_id

```typescript
// 白名单
const MEMORY_ALLOWED_TOOLS = new Set([
  "bash", "read", "websearch", "webfetch", "task",
]);

function fireAndForgetMemory(
  toolName: string,
  args: unknown,
  output: string,
  flowId: string,  // ← 新增
): void {
  // 白名单检查
  if (!MEMORY_ALLOWED_TOOLS.has(toolName)) {
    return;  // 不在白名单 → 不存
  }
  // 传 flow_id 给 daemon
  const entry = JSON.stringify({
    question, answer: text, type: toolName,
    flow_id: flowId,  // ← 新增
  }) + "\n";
  // ...
}
```

tool.execute.after hook 调用时传 session.flowId：
```typescript
fireAndForgetMemory(toolName, input.args, output.output || "", session.flowId);
```

### 2.3 memory_writer_daemon.py — 接收 + 存储 flow_id

```python
# 从 stdin 读取的 JSON 加 flow_id 字段
entry = json.loads(line)
db.store(
    question=entry.get("question", ""),
    answer=entry.get("answer", ""),
    type=entry.get("type", ""),
    doc_type="memory",
    flow_id=entry.get("flow_id", ""),  # ← 新增
)
```

### 2.4 knowledge/server.py — search_in_memory 加 flow_id 参数

```python
async def search_in_memory(
    questions: list[str],
    flow_id: str = "",  # ← 新增
    message: str = "",
) -> str:
    await _ensure_ready()
    results = _state["db"].search(
        questions, type=None, doc_type="memory",
        top_k=DEFAULT_TOP_K,
        flow_id=flow_id if flow_id else None,  # ← 传 flow_id
    )
```

### 2.5 searcher.md — search_in_memory 参数说明加 flow_id

```markdown
- `mcp__knowledge__search_in_memory.flow_id`：当前任务的 Flow ID（从 system prompt 的 $OPENSECURITY_FLOW_ID 获取）。
  memory 按任务隔离——只搜索当前任务的工具执行记录。
```

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 行数估计 |
|------|---------|---------|
| `knowledge/db.py` | 加 flow_id 列 + store/search 参数 | ~15 行 |
| `security-analysis.ts` | 白名单 + flow_id 传参 | ~15 行 |
| `knowledge/memory_writer_daemon.py` | 接收 flow_id | ~3 行 |
| `knowledge/server.py` | search_in_memory 加 flow_id | ~5 行 |
| `searcher.md` | 参数说明 | ~3 行 |

### §3.1 实施步骤拆分

#### 步骤 1：db.py 加 flow_id 列 + store/search 支持

- 文件：`knowledge/db.py`
- 改动：
  - MIGRATE_COLUMNS 加 flow_id
  - store() 加 flow_id 参数 + INSERT 含 flow_id
  - search() 加 flow_id 参数 + 仅 doc_type=memory 时 WHERE flow_id=?
- 预估行数：~15 行
- 验证点：
  - 语法通过
  - 已有数据库迁移成功（ALTER TABLE ADD COLUMN flow_id）
  - store 后 search 能按 flow_id 过滤
- 依赖：无

#### 步骤 2：memory_writer_daemon.py 接收 flow_id

- 文件：`knowledge/memory_writer_daemon.py`
- 改动：从 JSON 读 flow_id + 传给 db.store
- 预估行数：~3 行
- 验证点：语法通过
- 依赖：步骤 1

#### 步骤 3：security-analysis.ts 白名单 + flow_id

- 文件：`security-analysis.ts`
- 改动：
  - 加 MEMORY_ALLOWED_TOOLS 白名单 Set
  - fireAndForgetMemory 加 flow_id 参数 + 白名单检查
  - tool.execute.after 调用时传 session.flowId
- 预估行数：~15 行
- 验证点：
  - node --check 通过
  - 白名单工具集含 bash/read/websearch/webfetch/task
- 依赖：步骤 2

#### 步骤 4：knowledge/server.py search_in_memory 加 flow_id

- 文件：`knowledge/server.py`
- 改动：search_in_memory 加 flow_id 参数 + 传给 db.search
- 预估行数：~5 行
- 验证点：语法通过
- 依赖：步骤 1

#### 步骤 5：searcher.md 参数说明

- 文件：`searcher.md`
- 改动：search_in_memory 的参数说明加 flow_id
- 预估行数：~3 行
- 验证点：grep flow_id 有匹配
- 依赖：步骤 4

#### 步骤 6：测试

- 文件：新建 `test/knowledge/test_memory_flowid.py`
- 测试内容：
  1. 存 memory 带 flow_id=A → search flow_id=A 能搜到
  2. 存 memory 带 flow_id=A → search flow_id=B 搜不到
  3. 存 answer（无 flow_id）→ search answer 不受 flow_id 影响
  4. 白名单验证：bash 结果被存、edit 结果不被存
- 预估行数：~60 行
- 验证点：4 个测试用例全通过
- 依赖：步骤 1-5

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | answers 表有 flow_id 列 | PRAGMA table_info 检查 |
| F2 | memory 存储时写入 flow_id | 存后查 flow_id 字段非空 |
| F3 | memory search 按 flow_id 过滤 | 存 flow_id=A → search flow_id=B 返回空 |
| F4 | answer/guide/code 不受 flow_id 影响 | 存 answer → search answer 无 flow_id 参数正常返回 |
| F5 | 白名单过滤：bash 被存 | fireAndForgetMemory("bash", ...) → 存入 |
| F6 | 白名单过滤：edit 不被存 | fireAndForgetMemory("edit", ...) → 不存入 |
| F7 | search_in_memory 有 flow_id 参数 | grep server.py 有 flow_id |

### 回归验收

| # | 验收项 |
|---|--------|
| R1 | answer/guide/code 的 store/search 不受影响 |
| R2 | 已有数据库迁移成功（不丢数据） |
| R3 | security-analysis-evolve 的 edit/write/glob/grep 不被存入 memory（不在白名单）；bash/read 虽在白名单但按 flow_id 隔离不污染安全分析任务 |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | memory 按 flow_id 隔离（对齐 PentAGI memory.go:62） |
| A2 | 白名单过滤（对齐 PentAGI registry.go:149） |
| A3 | answer/guide/code 全局共享不变 |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-19-knowledge-mcp-align-pentagi.md` | **直接前置**——knowledge MCP 已对齐 PentAGI 4 类别 + 匿名化 + score 阈值，本需求补齐 memory 的 flow_id 隔离 + 白名单 |
| `2026-07-20-knowledge-management-loop.md` | 独立——知识管理闭环（prompt 引导），本需求是基础设施层改动 |
