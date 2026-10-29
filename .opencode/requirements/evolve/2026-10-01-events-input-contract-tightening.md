# 事件库输入契约语义收紧（events input contract tightening）

- 日期：2026-10-01
- 类型：契约收紧（routes/events.py + mcp-servers/events/server.py）
- 状态：已实施、验证通过并**已生效**（15:10 重启后 live 自检：控制台 9/9、MCP 2/2、全链路读取 ✓）；待提交

## §1 背景与目标

**来源**：对 `routes/events.py` 七个输入模型的逐字段语义审查（含 venv 实测探针验证当前行为）。

**现状问题**（实测确认）：

| 问题 | 实测证据 | 后果 |
|---|---|---|
| 必填字符串字段允许空串/纯空白 | `group_id=""`、`query=""`、`name/body/source=""` 均通过校验 | 空分区写入（数据"消失"于检索视野）、删除静默删不中、无意义检索 |
| `diversity_level` 无枚举约束 | `"extreme"` 通过；service `.get(..., 0.5)` 静默降级为 medium | 调用方以为 high 生效，实际 medium（静默错误） |
| `max_results` 仅 time-search 有界 | `max_results=-5`、`1e9` 通过 | 负值直达 graphiti limit；超大值制造重查询 |
| 列表元素未校验非空白 | `node_labels=[""]` 通过（与空列表事故同类：非法 Cypher） | 非法过滤条件 → 空 error 结果 |
| 时间字段无格式校验 | 非法格式在 service 层 `fromisoformat` 抛错 → 软 error 降级 | 契约违反应走 422 快速拒绝，而非运行时软失败 |
| `timestamp` 无正数校验 | `0`/负数/NaN 可通过 | 非法时间戳污染事件时间线 |
| 非标准 JSON 数值字面量未受限 | `timestamp: NaN/Infinity` 可通过（Python json.loads 默认接受） | 非法时间戳入库；加约束后暴露校验错误路径缺陷（§2.5） |

**目标（按字段真实语义收紧，而非机械加约束）**：
1. 语义上"必须有内容"的字段：非空且非纯空白；
2. 语义上是"封闭取值"的字段：enum 约束；
3. 语义上是"数量/范围"的字段：统一边界；
4. 语义上是"可选时间点"的字段：空=不限；非空必须可解析 ISO 8601；
5. HTTP（强制执行点，422）与 MCP（agent 入口）契约对齐。

**明确不做**（语义上无据，避免过度收紧）：
- 不枚举 `node_labels`/`edge_types` 的**取值**（类型集单一来源不在本文件，硬编码会漂移；MCP 描述已给可选值指引）；
- 不设 `query`/`body` 长度上限（无自然语义上界；plugin 写入侧已有截断）；
- 不强制时间字段带时区（service 现状即接受 naive；时区语义为独立未测项，见 §4 边界）；
- 不 strip 任何字段值（拒绝空白，但不改动合法值的原始字节）；
- 不动 `/api/memory/*` 路由（另有自己的契约语义：空 question → `queued:false`，非本需求范围）。

## §2 技术方案

### 2.1 校验原语（events.py 模块级，唯一来源）

```python
NonBlankStr = Annotated[str, Field(min_length=1), AfterValidator(_reject_blank)]
# _reject_blank: v.strip() == "" → ValueError("不能为空白字符串")；值不做变换

IsoTimeOrEmpty = Annotated[str, AfterValidator(_validate_iso_or_empty)]
# 空串放行（=不限边界）；非空走 datetime.fromisoformat(v.replace("Z","+00:00"))
# ——与 services/event_store.py search_time 完全同一解析路径，保证判定一致

MaxResults = Annotated[int, Field(ge=1, le=100)]
# 五个端点共用一份边界定义（1..100）；默认值各自语义（15/20/10/10/25）由字段赋值给出
```

### 2.2 逐字段语义与目标契约

| 模型 | 字段 | 现状 | 目标 | 语义依据 |
|---|---|---|---|---|
| EventEntryIn | name / body / source | `str` | `NonBlankStr` | 事件标签 / 内容本体 / 来源溯源，空值无意义且 body 空仍触发 LLM 抽取 |
| EventEntryIn | group_id | `str` | `NonBlankStr` | 分区键；空 = 写入无人能检索到的分区 |
| EventEntryIn | timestamp | `float\|None=None` | `Field(default=None, gt=0, allow_inf_nan=False)` | ms epoch **有限正数**（`+inf` 可穿透 `gt=0`，须显式禁）；None=服务端兜底（保持） |
| EventDeleteIn | group_id | `str` | `NonBlankStr` | 破坏性操作的分区键 |
| TimeSearchIn | query / group_id | `str` | `NonBlankStr` | 查询语义本体 / 分区 |
| TimeSearchIn | time_start / time_end | `str=""` | `IsoTimeOrEmpty` | 空=不限；非空必须是时间点 |
| TimeSearchIn | max_results | 已有 `ge=1, le=100` | 不变 | 已有，作为其余端点的基准 |
| EntityRelationsIn | query / group_id / center_node_uuid | `str` | `NonBlankStr` | BFS 原点为空 → origin 非法 → 恒空结果 |
| EntityRelationsIn | node_labels / edge_types | `list[str]\|None=None` | `list[NonBlankStr]\|None` + `Field(min_length=1)` | 可选过滤器：不传=None；传了就必须是含非空白元素的有效过滤器 |
| EntityRelationsIn | max_depth | `ge=1, le=3` | 不变 | 已有 |
| EntityRelationsIn | max_results | `int=20` 无界 | `Field(default=20, ge=1, le=100)` | 数量语义 |
| DiverseIn | query / group_id | `str` | `NonBlankStr` | 同上 |
| DiverseIn | diversity_level | `str="medium"` | `Literal["low","medium","high"]="medium"` | 封闭取值；消除静默降级 |
| DiverseIn | max_results | `int=10` 无界 | `Field(default=10, ge=1, le=100)` | 数量语义 |
| EpisodeContextIn | query / group_id | `str` | `NonBlankStr` | 同上 |
| EpisodeContextIn | max_results | `int=10` 无界 | `Field(default=10, ge=1, le=100)` | 数量语义 |
| EntitySearchIn | query / group_id | `str` | `NonBlankStr` | 同上 |
| EntitySearchIn | node_labels | `list[str]` + `min_length=1` | `list[NonBlankStr]` + `min_length=1` | 容器约束保留；补元素级（`[""]` 是空列表事故的同类） |
| EntitySearchIn | min_mentions | `ge=0` | 不变 | 已有；无自然上界 |
| EntitySearchIn | edge_types | `list[str]\|None=None` | `list[NonBlankStr]\|None` + `Field(min_length=1)` | 同过滤器语义 |
| EntitySearchIn | max_results | `int=25` 无界 | `Field(default=25, ge=1, le=100)` | 数量语义 |

### 2.3 MCP 层对齐（mcp-servers/events/server.py）

| 工具 | 改动 | 理由 |
|---|---|---|
| entity_relationships_search / diverse_results_search / episode_context_search / entity_search | `max_results` 加 `ge=1, le=100` | 与 HTTP 契约一致（time_search 已如此） |
| entity_search | `node_labels` 加 `min_length=1` | 与 HTTP「必填+非空」契约一致（agent 侧提前报错，而非 422 回传） |
| entity_relationships_search / entity_search | `node_labels` / `edge_types` 加 `min_length=1` | 传了空列表 = 无意义过滤器；与 HTTP 语义一致 |

MCP 层不重复弱校验：query/group_id/center_node_uuid 的空白拒绝、列表元素非空白、时间格式，由 HTTP 层（唯一强制执行点）负责。

边界数值（1..100）在两个进程边界各声明一次（MCP 薄壳不 import 后端代码，跨进程部署）；HTTP 为唯一强制执行点，MCP 侧约束仅用于 agent 侧提前反馈。

### 2.4 边界不变式（保住既有设计）

- **422（契约违规） vs 200+error（运行时降级）**：路由的 try/except 降级语义不变——模型校验失败在进路由前 422；service 运行时异常仍返回降级空结构。
- 恢复端点的 write 语义不变：合法请求仍入队即返 202。
- `timestamp=None` 服务端兜底、`time_start/end=""` 不限边界：两个既有默认语义保持。

### 2.5 校验错误响应加固（覆盖审计发现的独立缺陷）

**现象**：客户端发送 `timestamp: NaN/Infinity`（Python `json.loads` 接受这些非标准字面量）时，pydantic 正确拒绝（收紧前的行为是静默接受），但 FastAPI **默认 422 处理器**回显 `input` 原值 → starlette `json.dumps(allow_nan=False)` 抛 ValueError——**校验错误处理器自身崩溃**（客户端收到 500 而非 422）。

**修复**（`control/backend/server.py`）：
- `_json_safe` 递归净化：非有限浮点（NaN/±inf）→ 字符串；dict/list/tuple 递归；
- 自定义 `RequestValidationError` 处理器返回 `{"detail": _json_safe(jsonable_encoder(exc.errors()))}`，状态码 422；
- 错误结构与 FastAPI 默认完全一致（type/loc/msg/input 全保留）。

**影响面**：全应用级（任何端点的校验错误回显路径），非仅 events。

## §3 实现规范

### 改动范围表

| 文件 | 改动 | 预估行数 |
|---|---|---|
| `control/backend/routes/events.py` | 校验原语 + 7 个模型逐字段收紧 + 文档注释 | ~70 |
| `mcp-servers/events/server.py` | 5 处参数约束 | ~12 |
| `control/backend/tests/test_control.py` | 新增输入契约测试（子进程隔离 + TestClient + 模型级穷举矩阵） | ~200 |
| `control/backend/server.py` | §2.5 校验错误响应加固（_json_safe + 422 处理器） | ~30 |

### §3.1 实施步骤

1. **events.py 语义收紧**
   - 文件：`control/backend/routes/events.py`
   - 内容：新增 `NonBlankStr` / `IsoTimeOrEmpty` / `MaxResults` 原语（含 docstring）；按 §2.2 表逐字段修改；更新模块 docstring 输入契约说明
   - 预估行数：~70（新增 + 修改，不含注释）
   - 验证点：`python -c "compile(...)"` 通过；用 venv 校验探针跑完整矩阵（见步骤 3 的用例表，期望：非法→ValidationError/422，合法→通过）
   - 依赖：无
2. **MCP 层对齐**
   - 文件：`mcp-servers/events/server.py`
   - 内容：按 §2.3 表修改参数约束
   - 预估行数：~12
   - 验证点：`python -c "import server"` 冒烟（沙箱 PYTHONPATH）+ 工具 schema 断言（max_results 含 ge/le、node_labels 含 min_length）——用 FastMCP 工具列表内省
   - 依赖：步骤 1（契约基准）
3. **契约测试**
   - 文件：`control/backend/tests/test_control.py`（新增独立测试 + 子进程内省函数，风格对齐 `_knowledge_events_routes_inner`）
   - 内容：TestClient + Fake 服务，断言矩阵（覆盖审计后增强）：
     - 422（34 组 payload）：缺失必填（entry name/body/source/group_id、delete、time query、rel center、entity node_labels）；空/空白 query、group_id、name、body、source、center_node_uuid；非法时间格式与纯空白；`diversity_level="extreme"/"High"`；`max_results=0/101/-5/1e9`；`node_labels=[]`/`[""]`；`edge_types=[]`/`[""]`；`timestamp=0/-1`
     - 422（3 条 raw）：`NaN` / `Infinity` / `-Infinity` 字面量（§2.5 回归锚点）
     - 422 形状：`detail` 结构（type/loc/msg/input）与默认一致
     - PASS（13 条）：合法写入 202；`timestamp` 缺省/1；最小合法 payload（rel/diverse/entity）；`time_start=""`/合法 ISO（含 naive）；`diversity_level="high"`；`node_labels=["Tool"]`
     - 模型级穷举矩阵（118 条，独立用例）：7 模型 × 字段 × {缺失/空/空白/类型/数值边界/NaN·±inf/枚举大小写}
   - 预估行数：~200
   - 验证点：`python tests/test_control.py` 全绿（含既有用例）
   - 依赖：步骤 1
4. **回归与静态检查**
   - 依赖：步骤 1 / 2 / 3
   - `pyright`（backend 目录，0 error）；`test_control.py` 全量；`test_config_manager.py`、`test_remote_routes.py` 抽查（同套件邻接）
   - 证据落 progress
5. **校验错误响应加固（覆盖审计发现，后补）**
   - 文件：`control/backend/server.py`
   - 内容：§2.5（`_json_safe` + 自定义 `RequestValidationError` 处理器）
   - 预估行数：~30
   - 验证点：NaN/±Infinity raw 请求干净 422（非 500）；422 形状不变；pyright 0；全量套件绿
   - 依赖：步骤 1 / 3（契约与测试先暴露缺陷）

## §4 验收标准

**功能验收**
- §3.1 步骤 3 的 422/PASS 矩阵逐条通过（含模型级 110 条穷举）
- `timestamp` 为 NaN/±Infinity 时返回干净 422（非 500），422 结构与 FastAPI 默认一致（§2.5）
- 既有搜索正常路径（time-search 200、空结构）不回归
- plugin 写入路径零改动即可满足新契约（实测其 payload：name/body/source/flowId/Date.now() 全部合法）
- MCP 工具 schema 含新约束（内省断言）

**回归验收**
- `python tests/test_control.py` 全绿；`pyright` 0 error
- e2e 既有锚点语义不变（node_labels 缺失/空列表 422 保持）

**架构验收**
- 无新依赖；校验原语单一来源在 events.py，MCP 层不复制弱校验
- 422（契约）与 200+error（运行时降级）边界不混
- 未触碰 agent prompt（Phase 4.5 瘦身检查不适用）

**边界/未测项（诚实声明）**
- 时间字段 naive（无时区）值仍被接受（service 现状如此）；其与库内 aware `created_at` 的比较行为未测——如需强制时区，属独立需求
- `node_labels` 取值（8 类型）未做枚举约束，理由见 §1

## §5 与现有需求文档的关系

- 延续 `2026-08-17-plugin-writers-to-console.md`（写端点契约）与 e2e 中 node_labels 422 锚点的"无效输入显式拒绝"原则，把该原则**系统化到全部七个输入模型**；
- 不冲突：`2026-09-26-backend-oop-refactor.md` 的模型分层不变；本次仅加约束；
- 与 `2026-09-30-config-surface-categories.md` 无关。
