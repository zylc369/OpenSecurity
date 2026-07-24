# Events MCP 工具简化：8→6，合并过于相似的工具

## §1 背景与目标

### 1.1 来源

knowledge MCP 简化（7→3）后发现 events MCP 存在类似问题：工具按"用户意图"拆分（PentAGI 理念），导致同一底层能力暴露为多个工具，LLM 面对通用查询时不知道选哪个。

### 1.2 问题清单

| # | 问题 | 代码位置 |
|---|------|---------|
| 1 | recent_context_search 和 temporal_window_search 底层区别极小（只是时间过滤方向不同） | server.py:487 vs server.py:280 |
| 2 | successful_tools_search 是 entity_by_label_search 的特化（固定 node_labels=["Tool"] + min_mentions 过滤） | server.py:438 vs server.py:519 |
| 3 | LLM 面对通用查询时不知道选 recent 还是 temporal（都是时间维度） | 设计层 |
| 4 | LLM 搜工具时不知道选 successful_tools 还是 entity_by_label（两者都能搜工具） | 设计层 |

### 1.3 根因

PentAGI 设计理念"工具名=意图"假设 LLM 通过工具名比通过参数更能表达意图。实际效果相反——LLM 先要选工具，选择本身是认知负担。

**验证**：knowledge MCP 简化（7→3）已证明——合并后 LLM 决策从 2 步降到 0 步，消除所有选择混淆。

### 1.4 目标

将 8 工具简化为 6 工具：

| 现状（8 工具） | 目标（6 工具） |
|---------------|---------------|
| recent_context_search + temporal_window_search | **time_search**（时间参数决定模式） |
| successful_tools_search + entity_by_label_search | **entity_search**（node_labels + min_mentions 参数化） |
| episode_context_search | 不变 |
| diverse_results_search | 不变 |
| entity_relationships_search | 不变 |
| delete_session_events | 不变 |

**收益**：
- 工具数 -25%（8→6）
- 消除 recent vs temporal 的选择困难（参数决定模式）
- 消除 successful_tools vs entity_by_label 的选择困难（参数化合并）
- 5 个搜索对应 5 种本质不同的搜索策略，不再有重叠

---

## §2 技术方案

### 2.1 新工具签名

#### time_search（合并 recent + temporal）

```python
@mcp.tool(
    description="按时间搜索事件图谱。不传时间=搜全部；只传 time_start=最近N天起；传 time_start+time_end=指定区间。",
)
async def time_search(
    query: Annotated[str, Field(description="中文自然语言查询，描述要查找的事件。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。限定搜索范围到当前任务。")],
    time_start: Annotated[str, Field(description="可选：起始时间，ISO 8601 格式（如 2026-01-01T00:00:00Z）。不传则不限起始。")] = "",
    time_end: Annotated[str, Field(description="可选：结束时间，ISO 8601 格式。不传则不限结束。")] = "",
    max_results: Annotated[int, Field(description="最大返回结果数。", ge=1, le=100)] = 15,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
```

行为矩阵：
| time_start | time_end | 行为 | 等价旧工具 |
|-----------|---------|------|-----------|
| "" | "" | 无时间过滤 | （无，搜全部） |
| "2026-07-01T00:00:00Z" | "" | >= start | recent_context |
| "" | "2026-07-25T00:00:00Z" | <= end | （反向 recent） |
| "2026-07-01T00:00:00Z" | "2026-07-25T00:00:00Z" | start ≤ t ≤ end | temporal_window |

搜索配置统一为：edge=bm25+cosine, node=bm25+cosine（取 temporal_window 的完整配置）。

#### entity_search（合并 entity_by_label + successful_tools）

```python
@mcp.tool(
    description="按实体标签搜索实体。知道实体类型（如 CVE、Host、Tool）时使用。可选按提及次数过滤。",
)
async def entity_search(
    query: Annotated[str, Field(description="中文自然语言查询。")],
    group_id: Annotated[str, Field(description="当前任务的 Flow ID，从 $OPENSECURITY_FLOW_ID 获取。")],
    node_labels: Annotated[list[str], Field(description="实体类型过滤（如 ['Tool', 'CVE', 'Host', 'Service']）。必填。")],
    min_mentions: Annotated[int, Field(description="可选：实体被提及的最少次数。不传或传0则不过滤。搜成功工具时传2。", ge=0)] = 0,
    edge_types: Annotated[list[str] | None, Field(description="可选：按关系类型过滤。")] = None,
    max_results: Annotated[int, Field(description="最大返回结果数。")] = 25,
    message: Annotated[str, Field(description="操作日志，1-2 句中文描述你正在做什么")] = "",
) -> str:
```

行为：
- `min_mentions=0`（默认）→ 不过滤（原 entity_by_label 行为）
- `min_mentions=2` → 过滤 mention_count >= 2（原 successful_tools 行为）

### 2.2 删除的工具

- `recent_context_search`（合并到 time_search）
- `temporal_window_search`（合并到 time_search）
- `successful_tools_search`（合并到 entity_search）
- `entity_by_label_search`（合并到 entity_search）

### 2.3 保留不变的 4 个工具

- `episode_context_search` — 搜 episode 层（事件片段原文），与 node/edge 搜索本质不同
- `diverse_results_search` — MMR + cross-encoder reranker，算法独特
- `entity_relationships_search` — BFS 图遍历，需要 center_node_uuid
- `delete_session_events` — 删除操作

---

## §3 实现规范

### 3.1 改动范围表

| 文件 | 改动类型 | 预估行数 |
|------|---------|---------|
| `mcp-servers/events/server.py` | 合并 4 工具→2 工具 | ~100 行改 |
| `agents/memorist.md` | 决策表+查询工程更新 | ~30 行改 |
| `docs/项目介绍/知识与记忆体系.md` | 工具列表更新 | ~20 行改 |
| `test/mcp_events/test_server_coverage.py` | 测试适配 | ~60 行改 |
| `test/mcp_events/test_mcp_search.py` | 测试适配 | ~40 行改 |
| `test/mcp_events/test_docker_lifecycle.py` | 测试适配 | ~15 行改 |
| `test/mcp_events/test_unit_await_behavior.py` | 测试适配 | ~40 行改 |
| `test/mcp_events/measure_events_phases.py` | 测试适配 | ~10 行改 |

**不改的文件**：
- `plugins/security-analysis.ts`：无旧工具名引用
- `test/mcp_events/test_lazy_loading.py`：无旧工具名引用

### 3.2 实施步骤拆分

#### Step 1. server.py 合并 recent+temporal 为 time_search

- **文件**: `mcp-servers/events/server.py`
- **预估行数**: ~60 行改
- **改动**:
  - 删除 `recent_context_search`（487-513 行）
  - 删除 `temporal_window_search`（280-320 行）
  - 新增 `time_search`（统一搜索配置 + 时间参数可选逻辑）
  - 更新模块 docstring
- **验证点**: `python -c "compile(open('server.py').read(), 'server.py', 'exec')"` 语法通过
- **依赖**: 无

#### Step 2. server.py 合并 successful_tools+entity_by_label 为 entity_search

- **文件**: `mcp-servers/events/server.py`
- **预估行数**: ~50 行改
- **改动**:
  - 删除 `successful_tools_search`（438-481 行）
  - 删除 `entity_by_label_search`（519-552 行）
  - 新增 `entity_search`（node_labels 必填 + min_mentions 可选后过滤）
- **验证点**: `python -c "compile(open('server.py').read(), 'server.py', 'exec')"` 语法通过
- **依赖**: Step 1

#### Step 3. memorist.md 决策表更新

- **文件**: `agents/memorist.md`
- **预估行数**: ~30 行改
- **改动**:
  - 决策表：7 行→5 行（删除 recent/temporal/successful_tools/entity_by_label 行，新增 time_search/entity_search 行）
  - 查询工程：更新示例中的工具名引用
- **验证点**: `grep "recent_context\|temporal_window\|successful_tools\|entity_by_label" memorist.md` 无匹配
- **依赖**: Step 2

#### Step 4. 文档更新

- **文件**: `docs/项目介绍/知识与记忆体系.md`
- **预估行数**: ~20 行改
- **改动**:
  - events 工具列表：8→6
  - 数据流图中的工具调用路径更新
- **验证点**: `grep "recent_context\|temporal_window\|successful_tools\|entity_by_label" 知识与记忆体系.md` 无匹配
- **依赖**: Step 3

#### Step 5. 测试文件适配

- **文件**: `test/mcp_events/test_server_coverage.py`、`test_mcp_search.py`、`test_docker_lifecycle.py`、`test_unit_await_behavior.py`、`measure_events_phases.py`
- **预估行数**: ~165 行改
- **改动**:
  - `entity_by_label_search` → `entity_search`（所有测试文件）
  - `successful_tools_search` → `entity_search(node_labels=["Tool"], min_mentions=2)`
  - `recent_context_search` → `time_search`（去 recency_window）
  - `temporal_window_search` → `time_search`（time_start/time_end 不变）
- **验证点**: `grep -rn "recent_context\|temporal_window\|successful_tools\|entity_by_label" test/mcp_events/` 无匹配
- **依赖**: Step 1-2

---

## §4 验收标准

### 4.1 功能验收

| ID | 验收项 | 验证方式 |
|----|--------|---------|
| F1 | time_search 工具存在 | MCP tools/list 包含 time_search |
| F2 | entity_search 工具存在 | MCP tools/list 包含 entity_search |
| F3 | 旧工具不存在 | tools/list 不含 recent_context_search/temporal_window_search/successful_tools_search/entity_by_label_search |
| F4 | time_search 不传时间=搜全部 | time_start="" + time_end="" 返回结果 |
| F5 | time_search 只传起始=单向过滤 | time_start=X 返回 >= X 的结果 |
| F6 | time_search 传起止=双向过滤 | time_start=X + time_end=Y 返回 X≤t≤Y 的结果 |
| F7 | entity_search min_mentions=0 不过滤 | 返回所有标签匹配的实体 |
| F8 | entity_search min_mentions=2 过滤 | 只返回 mention_count >= 2 的实体 |

### 4.2 回归验收

| ID | 验收项 |
|----|--------|
| R1 | episode_context_search 不变 |
| R2 | diverse_results_search 不变 |
| R3 | entity_relationships_search 不变 |
| R4 | delete_session_events 不变 |
| R5 | Docker lifecycle 不变 |

### 4.3 架构验收

| ID | 验收项 |
|----|--------|
| A1 | 工具数从 8 减少到 6 |
| A2 | 搜索工具数从 7 减少到 5 |
| A3 | 5 个搜索对应 5 种本质不同的搜索策略 |
| A4 | 无工具选择重叠（recent vs temporal / successful_tools vs entity_by_label 消除） |

---

## §5 与现有需求文档的关系

| 现有需求文档 | 关系 |
|-------------|------|
| `2026-07-19-events-mcp-lazy-loading.md` | **保留**：lazy 加载机制不变 |
| `2026-07-21-mcp-desc-cn-message-dedup.md` | **保留**：中文描述 + message 参数不变 |
| `2026-07-25-knowledge-mcp-simplify.md` | **同类**：knowledge MCP 也做了工具简化（7→3） |
