# events MCP server 实施文档

> 目标：将 events/server.py 从 stub 替换为真实 Graphiti 后端，1:1 复刻 PentAGI 的 Graphiti 集成。
> 参照源码：PentAGI（`~/Documents/Codes/pentagi`）+ graphiti-core Python SDK 0.29.2

## §1 背景与目标

### 当前状态
- `events/server.py`：7 个 search 方法全部返回空（stub）
- 写入：无（没有任何数据写入事件库）

### 目标
- 读取：7 个 search 方法调用 graphiti-core SDK 返回真实数据
- 写入：通过 plugin hooks 自动存储 LLM 响应 + 工具执行记录

### PentAGI 参照源码
| 功能 | PentAGI 源码路径 | 行号 |
|---|---|---|
| LLM 响应写入 | `providers/performer.go` `storeAgentResponseToGraphiti` | 952-1031 |
| 工具执行写入 | `providers/performer.go` `storeToolExecutionToGraphiti` | 1033-1139 |
| 底层写入 | `providers/performer.go` `storeToGraphiti` | 920-950 |
| 7 个搜索 handler | `tools/graphiti_search.go` `handleXxxSearch` | 156-424 |
| 7 个结果格式化 | `tools/graphiti_search.go` `FormatGraphitiXxxResults` | 426-785 |
| agent_response 模板 | `templates/graphiti/agent_response.tmpl` | 1-4 |
| tool_execution 模板 | `templates/graphiti/tool_execution.tmpl` | 1-9 |
| Graphiti 客户端 | `pkg/graphiti/client.go` | 全文件 |
| 默认参数 | `tools/graphiti_search.go` line 27-54 | 27-54 |

---

## §2 基础设施

### 2.1 Neo4j 部署

```bash
docker run -d \
  --name neo4j-events \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  -v neo4j-data:/data \
  neo4j:5
```

- Bolt 协议端口：7687（graphiti-core 用此端口连接）
- Web 界面：7474（调试用）

### 2.2 环境变量

写到 `.opencode/.ai_env`（现有文件，追加）：

```ini
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your_password
OPENAI_API_KEY=sk-xxx（Graphiti 实体提取需要 OpenAI）
```

### 2.3 graphiti-core 已安装

```
graphiti-core==0.29.2
依赖：neo4j, numpy, openai, posthog, pydantic, python-dotenv, tenacity
```

---

## §3 读取路径（7 个 search 方法实现）

### 3.1 graphiti-core 初始化

```python
from graphiti_core import Graphiti
from graphiti_core.driver.neo4j_driver import Neo4jDriver
import os

driver = Neo4jDriver(
    uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
    user=os.environ.get("NEO4J_USER", "neo4j"),
    password=os.environ.get("NEO4J_PASSWORD", ""),
)
graphiti = Graphiti(driver=driver)
```

初始化时调用 `await graphiti.build_indices_and_constraints()` 建索引（仅首次）。

### 3.2 7 个方法的映射

#### 1. temporal_window_search

**PentAGI**：`graphiti_search.go:156-201`
- 入参：query, time_start(ISO 8601), time_end(ISO 8601), max_results=15
- 调用：`graphitiClient.TemporalWindowSearch(req)`
- 格式化：`FormatGraphitiTemporalResults`（line 426-497）

**graphiti-core**：
```python
from graphiti_core.search.search_config import SearchConfig, EdgeSearchConfig, NodeSearchConfig
from graphiti_core.search.search_config import EdgeSearchMethod, NodeSearchMethod
from graphiti_core.search.search_filters import SearchFilters, DateFilter, ComparisonOperator
from datetime import datetime

results = await graphiti.search_(
    query=query,
    config=SearchConfig(
        limit=max_results,
        edge_config=EdgeSearchConfig(
            search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
        ),
    ),
    search_filter=SearchFilters(
        created_at=[[
            DateFilter(date=time_start, comparison_operator=ComparisonOperator.greater_than_equal),
            DateFilter(date=time_end, comparison_operator=ComparisonOperator.less_than_equal),
        ]],
    ),
)
```

**返回格式**（对齐 PentAGI FormatGraphitiTemporalResults，line 426-497）：
```python
{
    "edges": [{"name": e.name, "fact": e.fact, "created_at": e.created_at.isoformat(), "uuid": e.uuid}],
    "edge_scores": results.edge_reranker_scores,
    "nodes": [{"name": n.name, "uuid": n.uuid, "labels": n.labels, "summary": n.summary}],
    "node_scores": results.node_reranker_scores,
    "episodes": [{"source": ep.source, "content": ep.content, "created_at": ep.created_at.isoformat()}],
    "episode_scores": results.episode_reranker_scores,
    "time_window": {"start": time_start, "end": time_end},
}
```

#### 2. entity_relationships_search

**PentAGI**：`graphiti_search.go:204-254`
- 入参：query, center_node_uuid, max_depth=2(max 3), node_labels?, edge_types?, max_results=20
- 调用：`graphitiClient.EntityRelationshipsSearch(req)`
- 格式化：`FormatGraphitiEntityRelationshipResults`（line 500-552）

**graphiti-core**：
```python
results = await graphiti.search_(
    query=query,
    center_node_uuid=center_node_uuid,
    config=SearchConfig(
        limit=max_results,
        edge_config=EdgeSearchConfig(
            search_methods=[EdgeSearchMethod.breadth_first_search],
            bfs_max_depth=min(max_depth, 3),
        ),
    ),
    search_filter=SearchFilters(
        node_labels=node_labels,
        edge_types=edge_types,
    ),
)
```

#### 3. diverse_results_search

**PentAGI**：`graphiti_search.go:257-290`
- 入参：query, diversity_level(low/medium/high), max_results=10
- 调用：`graphitiClient.DiverseResultsSearch(req)`
- 格式化：`FormatGraphitiDiverseResults`（line 553-602）

**graphiti-core**：diversity_level 映射到 mmr_lambda：
- low → mmr_lambda=0.3（偏相关性）
- medium → mmr_lambda=0.5（平衡）
- high → mmr_lambda=0.7（偏多样性）

```python
from graphiti_core.search.search_config import EdgeReranker

mmr_lambda = {"low": 0.3, "medium": 0.5, "high": 0.7}.get(diversity_level, 0.5)

results = await graphiti.search_(
    query=query,
    config=SearchConfig(
        limit=max_results,
        edge_config=EdgeSearchConfig(
            search_methods=[EdgeSearchMethod.bm25, EdgeSearchMethod.cosine_similarity],
            reranker=EdgeReranker.cross_encoder,  # graphiti-core 用 cross_encoder 做重排
            mmr_lambda=mmr_lambda,
        ),
    ),
)
```

> **注意**：PentAGI 调用的是 Graphiti 服务端的 diverse search API，服务端内部用 MMR。graphiti-core SDK 没有直接的 "diverse" 方法，但 `mmr_lambda` 参数控制多样性程度——功能等价。

#### 4. episode_context_search

**PentAGI**：`graphiti_search.go:293-317`
- 入参：query, max_results=10
- 调用：`graphitiClient.EpisodeContextSearch(req)`
- 格式化：`FormatGraphitiEpisodeContextResults`（line 603-644）

**graphiti-core**：
```python
from graphiti_core.search.search_config import EpisodeSearchConfig, EpisodeSearchMethod

results = await graphiti.search_(
    query=query,
    config=SearchConfig(
        limit=max_results,
        episode_config=EpisodeSearchConfig(
            search_methods=[EpisodeSearchMethod.bm25],
        ),
    ),
)
```

或用 `retrieve_episodes`（更直接但无语义排序）：
```python
from datetime import datetime, timedelta

episodes = await graphiti.retrieve_episodes(
    reference_time=datetime.now(),
    last_n=max_results,
)
```

#### 5. successful_tools_search

**PentAGI**：`graphiti_search.go:320-350`
- 入参：query, min_mentions=2, max_results=15
- 调用：`graphitiClient.SuccessfulToolsSearch(req)`
- 格式化：`FormatGraphitiSuccessfulToolsResults`（line 645-685）

**graphiti-core**：按 node_labels=["Tool"] 过滤 + 客户端 min_mentions 过滤：
```python
results = await graphiti.search_(
    query=query,
    config=SearchConfig(
        limit=max_results * 2,  # 多取，客户端过滤 min_mentions
        node_config=NodeSearchConfig(
            search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
        ),
    ),
    search_filter=SearchFilters(
        node_labels=["Tool"],
    ),
)
# 客户端过滤 min_mentions（graphiti-core 无此参数）
tools = [n for n in results.nodes if n.attributes.get("mention_count", 0) >= min_mentions][:max_results]
```

> **注意**：min_mentions 过滤是 PentAGI 特有的后处理逻辑——Graphiti 服务端支持按 mention_count 过滤，graphiti-core SDK 需要客户端过滤。写入时需要在 Tool 节点的 attributes 中记录 mention_count。

#### 6. recent_context_search

**PentAGI**：`graphiti_search.go:353-386`
- 入参：query, recency_window(1h/6h/24h/7d/30d/90d), max_results=10
- 调用：`graphitiClient.RecentContextSearch(req)`
- 格式化：`FormatGraphitiRecentContextResults`（line 686-740）

**graphiti-core**：recency_window 转换为 datetime + DateFilter：
```python
from datetime import datetime, timedelta

window_map = {"1h": 1, "6h": 6, "24h": 24, "7d": 24*7, "30d": 24*30, "90d": 24*90}
hours = window_map.get(recency_window, 24)
since = datetime.now() - timedelta(hours=hours)

results = await graphiti.search_(
    query=query,
    config=SearchConfig(limit=max_results),
    search_filter=SearchFilters(
        created_at=[[DateFilter(date=since, comparison_operator=ComparisonOperator.greater_than_equal)]],
    ),
)
```

#### 7. entity_by_label_search

**PentAGI**：`graphiti_search.go:389-424`
- 入参：query, node_labels[](必填), edge_types?, max_results=25
- 调用：`graphitiClient.EntityByLabelSearch(req)`
- 格式化：`FormatGraphitiEntityByLabelResults`（line 741-785）

**graphiti-core**：
```python
results = await graphiti.search_(
    query=query,
    config=SearchConfig(
        limit=max_results,
        node_config=NodeSearchConfig(
            search_methods=[NodeSearchMethod.bm25, NodeSearchMethod.cosine_similarity],
        ),
    ),
    search_filter=SearchFilters(
        node_labels=node_labels,
        edge_types=edge_types,
    ),
)
```

### 3.3 统一返回格式

所有 7 个方法返回 `SearchResults` 对象，统一序列化为 JSON：
```python
def format_results(results, query: str) -> str:
    return json.dumps({
        "query": query,
        "edges": [{"name": e.name, "fact": e.fact, "uuid": e.uuid,
                    "created_at": e.created_at.isoformat()} for e in results.edges],
        "edge_scores": results.edge_reranker_scores,
        "nodes": [{"name": n.name, "uuid": n.uuid, "labels": list(n.labels),
                    "summary": n.summary} for n in results.nodes],
        "node_scores": results.node_reranker_scores,
        "episodes": [{"source": ep.source, "content": ep.content[:500],
                      "created_at": ep.created_at.isoformat()} for ep in results.episodes],
        "episode_scores": results.episode_reranker_scores,
    }, ensure_ascii=False)
```

---

## §4 写入路径（自动存储）

### 4.1 PentAGI 写入机制

PentAGI 的写入在 `performAgentChain` 主循环中自动触发（`performer.go`）：

**LLM 响应写入**（performer.go:170）：
- 每次 LLM 返回后调用 `storeAgentResponseToGraphiti`
- 使用 `agent_response.tmpl` 模板格式化：
  ```
  Agent: {{.AgentType}}
  Response: {{.Response}}
  Context: Task {{.TaskID}}, Subtask {{.SubtaskID}}
  ```
- 调用 `storeToGraphiti` → `graphitiClient.AddMessages`

**工具执行写入**（performer.go:198）：
- 每次工具执行后调用 `storeToolExecutionToGraphiti`
- **排除 AgentToolType**（line 197：`if toolTypeMapping[funcName] != tools.AgentToolType`）
- 使用 `tool_execution.tmpl` 模板格式化：
  ```
  Tool: {{.ToolName}}
  Description: {{.Description}}
  Barrier Function: {{.IsBarrier}}
  Arguments: {{.Arguments}}
  Invoked by: {{.AgentType}} Agent
  Status: {{.Status}}
  Result: {{.Result}}
  Context: Task {{.TaskID}}, Subtask {{.SubtaskID}}
  ```
- 调用 `storeToGraphiti` → `graphitiClient.AddMessages`

### 4.2 OpenSecurity 对应

**写入触发**：通过 OpenCode plugin hooks

| 数据 | PentAGI 触发 | OpenCode hook | hook 签名 |
|---|---|---|---|
| LLM 响应 | performer.go:170 每次 LLM 返回 | `experimental.text.complete` | `input: {sessionID, messageID, partID}` `output: {text}` |
| 工具执行 | performer.go:198 每次工具执行后 | `tool.execute.after` | `input: {tool, sessionID, callID, args}` `output: {title, output, metadata}` |

**写入方法**：调用 graphiti-core 的 `add_episode`

```python
await graphiti.add_episode(
    name=f"<描述性标题>",              # 如 "binary-analysis agent response" / "websearch execution"
    episode_body=f"<格式化内容>",       # agent_response 或 tool_execution 模板格式的内容
    source_description=f"<来源描述>",   # 如 "PentAGI binary-analysis agent execution in flow xxx"
    reference_time=datetime.now(),
    source=EpisodeType.message,
    group_id=session_id,              # 用 session ID 做分组（对应 PentAGI 的 groupID）
)
```

### 4.3 写入模板（对齐 PentAGI）

**LLM 响应模板**（对齐 agent_response.tmpl）：
```
Agent: {agent_name}
Response: {text}
Context: Session {session_id}
```

**工具执行模板**（对齐 tool_execution.tmpl）：
```
Tool: {tool_name}
Arguments: {args_json}
Invoked by: {agent_name} Agent
Status: {status}
Result: {output}
Context: Session {session_id}
```

### 4.4 写入过滤规则（对齐 PentAGI）

PentAGI 排除 AgentToolType 工具不存 Graphiti（performer.go:197）。

OpenSecurity 对应规则：
- **所有工具执行都存**——OpenSecurity 没有 AgentToolType 概念（Task 工具是 OpenCode 内置的，不在 plugin 可观测范围）
- **排除 Task 工具**——`tool.execute.after` 对 Task 工具是否触发需要实测确认。如果不触发则天然排除；如果触发则在 hook 中判断 `tool === "task"` 跳过

---

## §5 events/server.py 改造

### 5.1 文件结构

```python
"""事件库 MCP server（Graphiti 后端）。
存储过往 LLM 响应和工具执行记录。7 个搜索方法通过 graphiti-core 查询 Neo4j。
"""
import os
import json
import asyncio
from datetime import datetime, timedelta
from typing import Any

from mcp.server.fastmcp import FastMCP
from graphiti_core import Graphiti
from graphiti_core.driver.neo4j_driver import Neo4jDriver
from graphiti_core.nodes import EpisodeType
from graphiti_core.search.search_config import (
    SearchConfig, EdgeSearchConfig, NodeSearchConfig,
    EpisodeSearchConfig, EdgeSearchMethod, NodeSearchMethod,
    EpisodeSearchMethod, EdgeReranker,
)
from graphiti_core.search.search_filters import (
    SearchFilters, DateFilter, ComparisonOperator,
)

# 初始化 Graphiti 连接
_driver = Neo4jDriver(
    uri=os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
    user=os.environ.get("NEO4J_USER", "neo4j"),
    password=os.environ.get("NEO4J_PASSWORD", ""),
)
_graphiti = Graphiti(driver=_driver)
_graphiti_ready = False  # 延迟初始化标志

async def _ensure_ready():
    """首次调用时建索引（幂等）。"""
    global _graphiti_ready
    if not _graphiti_ready:
        await _graphiti.build_indices_and_constraints()
        _graphiti_ready = True

mcp = FastMCP("events")
```

### 5.2 异步处理

graphiti-core 全部是 async API。MCP FastMCP 的 `@mcp.tool()` 支持 async 函数：

```python
@mcp.tool(description="...")
async def temporal_window_search(query: str, time_start: str, time_end: str, max_results: int = 15) -> str:
    await _ensure_ready()
    # ... graphiti-core 调用 ...
    return json.dumps(result)
```

### 5.3 降级策略

Neo4j 不可用时，catch 异常返回空结果（与 stub 行为一致）：

```python
async def temporal_window_search(...):
    try:
        await _ensure_ready()
        results = await _graphiti.search_(...)
        return format_results(results, query)
    except Exception as e:
        return json.dumps({
            "edges": [], "nodes": [], "episodes": [],
            "error": f"Events backend unavailable: {e}",
        })
```

### 5.4 pyproject.toml 依赖更新

```toml
dependencies = [
    "mcp>=1.0",
    "graphiti-core>=0.29",
]
```

---

## §6 plugin 改造（写入路径）

### 6.1 新增两个 hook

在 `security-analysis.ts` 的 return 对象中新增：

```ts
"experimental.text.complete": async (input, output) => {
  // LLM 响应完成 → 写入事件库
  try {
    const session = ctx.sessionManager.get(input.sessionID);
    if (!session) return;
    const agentName = session.agentName;
    const body = `Agent: ${agentName}\nResponse: ${output.text}\nContext: Session ${input.sessionID}`;
    // 异步写入（不等待）
    void writeEvent(body, agentName + " agent response", input.sessionID);
  } catch (e) {
    debugLog(`text.complete 写入事件库失败: ${e}`);
  }
},

"tool.execute.after": async (input, output) => {
  // 工具执行完成 → 写入事件库
  try {
    if (input.tool === "task") return;  // 排除 Task 工具（对应 PentAGI 排除 AgentToolType）
    const session = ctx.sessionManager.get(input.sessionID);
    const agentName = session?.agentName ?? "unknown";
    const body = `Tool: ${input.tool}\nArguments: ${JSON.stringify(input.args)}\nInvoked by: ${agentName} Agent\nStatus: success\nResult: ${output.output}\nContext: Session ${input.sessionID}`;
    // 异步写入（不等待）
    void writeEvent(body, input.tool + " execution", input.sessionID);
  } catch (e) {
    debugLog(`tool.execute.after 写入事件库失败: ${e}`);
  }
},
```

### 6.2 writeEvent 函数

写入事件库有两种方式：

**方案 A**：plugin 通过 HTTP API 调 events MCP server 的写入接口
- 需要 events server 新增一个 `store_event` 工具
- plugin 通过 `client` 调用 MCP 工具

**方案 B**：plugin 直接调 graphiti-core（需要 plugin 支持 Python 互操作）
- 不现实——plugin 是 TypeScript，graphiti-core 是 Python

**方案 C（推荐）**：events MCP server 新增 `store_event` 工具，plugin 通过 OpenCode 的 MCP 工具调用机制触发
- events/server.py 新增：
  ```python
  @mcp.tool(description="Store an event to the events backend")
  async def store_event(name: str, episode_body: str, source_description: str, group_id: str) -> str:
      await _ensure_ready()
      await _graphiti.add_episode(
          name=name,
          episode_body=episode_body,
          source_description=source_description,
          reference_time=datetime.now(),
          source=EpisodeType.message,
          group_id=group_id,
      )
      return json.dumps({"stored": True})
  ```
- plugin hook 中调用：
  ```ts
  void client.mcp.call("events", "store_event", {
    name: "...",
    episode_body: "...",
    source_description: "...",
    group_id: sessionID,
  }).catch(e => debugLog(`写入事件库失败: ${e}`));
  ```

> **注意**：需确认 OpenCode SDK 的 `client.mcp.call()` 方法是否存在。从 SDK 源码看，MCP 工具调用通过 `client.mcp.tools()` 获取工具列表，然后通过标准 tool 调用机制执行。实际调用方式可能需要进一步研究 SDK。

---

## §7 验收标准

### 7.1 功能验收

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | Neo4j 连接成功 | `await graphiti.build_indices_and_constraints()` 不报错 |
| 2 | `add_episode` 写入成功 | 调用后 Neo4j Web 界面能看到节点 |
| 3 | `search` 返回真实数据 | 写入后 search 能命中 |
| 4 | 7 个 search 方法各自工作 | 逐个调用，返回非空（有数据时） |
| 5 | LLM 响应自动写入 | agent 对话后 Neo4j 中有 agent_response episode |
| 6 | 工具执行自动写入 | agent 调工具后 Neo4j 中有 tool_execution episode |
| 7 | Task 工具不写入 | 确认 Neo4j 中没有 task 工具的 episode |

### 7.2 回归验收

| # | 验收项 | 验证方式 |
|---|---|---|
| 1 | Neo4j 不可用时降级 | 停止 Neo4j → 调 search → 返回空 + error 字段 |
| 2 | 现有 knowledge MCP 不受影响 | knowledge MCP 正常工作 |
| 3 | agent 基本功能不受影响 | agent 对话/工具调用正常 |
| 4 | 写入不阻塞主流程 | 写入失败不影响 agent 继续 |

### 7.3 性能验收

| # | 验收项 | 标准 |
|---|---|---|
| 1 | 写入延迟 | 不阻塞 agent 工具循环（异步写入） |
| 2 | 搜索延迟 | 单次 search < 5 秒 |
| 3 | Neo4j 内存 | 常规使用不超过 2GB |

---

## §8 风险与注意事项

### 8.1 外部依赖

| 依赖 | 风险 | 缓解 |
|---|---|---|
| Neo4j | 需要额外运行 Docker 容器 | 降级策略：不可用时返回空 |
| OpenAI API key | Graphiti 实体提取需要 OpenAI | 环境变量配置 + 无 key 时降级 |
| graphiti-core async | MCP server 需要 async 适配 | FastMCP 支持 async 工具函数 |

### 8.2 与 PentAGI 的差异

| 差异点 | PentAGI | OpenSecurity | 影响 |
|---|---|---|---|
| 架构 | Go client → Graphiti REST API → Neo4j | graphiti-core → 直接 → Neo4j | 无（最终数据相同） |
| 写入触发 | performer.go 主循环 | plugin hooks（experimental.text.complete + tool.execute.after） | 无（等价触发点） |
| group_id | flow_id（PentAGI 流程 ID） | session_id（OpenCode 会话 ID） | 无（都是分组标识） |
| 工具排除 | AgentToolType 排除 | `tool === "task"` 排除 | 无（等价排除） |
| 写入模板 | Go template 渲染 | Python f-string | 无（内容相同） |
| LLM 响应拆分 | 每次完整 LLM 返回一条 | `experimental.text.complete` 每个 text part 一条 | **可能拆分**：LLM 一次返回多个 text part 时，PentAGI 存 1 条，OpenSecurity 可能存多条。需在 plugin 中合并同 messageID 的多个 part |

### 8.3 待确认项

| # | 待确认 | 确认方式 |
|---|---|---|
| 1 | `experimental.text.complete` 对 Task 工具执行是否触发 | 实测 |
| 2 | OpenCode SDK `client.mcp.call()` 调用 MCP 工具的确切方式 | 读 SDK 源码 |
| 3 | graphiti-core 的 `search_()` 对空库的行为 | 实测 |
| 4 | graphiti-core 的 `build_indices_and_constraints()` 幂等性 | 实测（多次调用不报错） |
| 5 | LLM 多 text part 合并策略 | 实测 `experimental.text.complete` 触发次数 |
