# 执行台账：事件库输入契约语义收紧（2026-10-01）

## 触发

用户对 `routes/events.py` 的提问："部分字段有默认值，哪些不能有默认值必须外部传入" → 逐字段语义审查 + 实测探针（发现 6 类问题：空串放行 / diversity 无枚举 / max_results 无界 / 列表元素未校验 / 时间无格式校验 / timestamp 无正数校验）→ 用户裁定："开启进化，理解并按照真正的语义收紧参数要求"。

## 执行记录（按 §3.1 步骤）

1. **events.py 语义收紧** ✓
   - 新增 `NonBlankStr` / `IsoTimeOrEmpty` / `MaxResults` 三个校验原语（单一来源）；
   - 7 个模型逐字段：必填串→NonBlankStr；timestamp→`gt=0, allow_inf_nan=False`（有限正数）；diversity→`Literal[low|medium|high]`；时间→ISO 或空；5 端点 max_results→`ge=1, le=100`（`MaxResults`）；两个模型的 node_labels/edge_types 容器 + 元素校验。
2. **MCP 层对齐** ✓
   - 4 工具 max_results 加 `ge=1, le=100`；entity_search.node_labels + 两处可选过滤器加 `min_length=1`。
3. **契约测试** ✓
   - `test_control.py` 新增 `_events_input_contract_inner` + `test_events_input_contract`（子进程隔离 + TestClient）+ `test_events_input_contract_model_matrix`（模型级 110 条穷举）。
4. **回归与静态检查** ✓（证据见下）
5. **校验错误响应加固（覆盖审计发现，后补）** ✓
   - `server.py`：`_json_safe`（非有限浮点→字符串）+ 自定义 `RequestValidationError` 处理器；修复 NaN/Infinity input 回显时 422 处理器自身崩溃（500）。

## 验证证据

```
步骤1  compile OK；语义矩阵探针 57/57 全部符合预期（非法→拒 / 合法→放行，含边界 100/101、0、-5、1e9、[""]、纯空白、非法时间）
步骤2  import 冒烟 OK；工具 schema 断言 11/11（max_results minimum/maximum、minItems、diversity enum、max_depth 既有）
步骤3  定向运行 ✓；全量 tests/test_control.py 通过 95 / 失败 0（含新增 2 个契约测试）
       模型级穷举矩阵 118/118；HTTP 契约：34 组 422 payload + 3 条 raw（NaN/±Infinity）+ 1 条 422 形状 + 13 条 PASS
步骤4  pyright backend 0/0/0；pyright mcp-servers 0/0/0
       test_config_manager 9/9；test_remote_routes 5/5
步骤5  NaN/±Infinity raw 请求干净 422（非 500）；422 形状与默认一致；pyright 复跑 0/0/0
```

### 补盲轮（用户质疑测试覆盖 → 覆盖审计）

对"全部正常/边界条件"做字段×类别矩阵审计，发现并闭环：

1. **覆盖缺口**（缺失必填字段未逐模型断言、大小写变体、空白变体、NaN/inf 未覆盖）→
   - HTTP 契约测试 +10 组 422（缺 name/body/source/group_id、缺 query、缺 center、缺 node_labels、diversity "High"、time_start 纯空白、edge_types [""]）+ 3 条 raw + 1 条形状 + 4 条 PASS（最小合法 ×3、timestamp=1）；
   - 新增模型级穷举矩阵 118 条（7 模型 × 字段 × {缺失/空/纯空白/类型/数值边界/NaN·±inf/枚举大小写}；补齐空串/空白类别到全部必填串字段）。
2. **契约空洞**：`timestamp=+inf` 可穿透 `gt=0` → `allow_inf_nan=False`（有限正数）。
3. **应用级缺陷**：NaN/Infinity 被拒后，FastAPI 默认 422 处理器回显 input 时序列化崩溃（500）→ `server.py` 加固（§2.5）。

- 未改动 plugin（其写入 payload 天然满足新契约：name/body/source 非空、group_id=flowId、timestamp=Date.now()）
- e2e 既有锚点（node_labels 缺失/空列表 422）语义不变

## 审计（Phase 3 / Phase 6）

- Phase 3（需求文档）：2 轮修复（§2.3 跨进程重复说明、步骤 4 依赖行）→ 纯审计轮零问题 → 通过
- Phase 6（实现审计）：第 1 轮发现 1 处（需求文档状态行"待实施"过期）→ 修复；第 2 轮发现 1 处（本台账探针计数笔误 56→57）→ 修复；纯审计轮零问题 → 通过
- 补盲轮（测试覆盖审计，2 轮 + 纯审计）：第 1 轮发现 3 处（覆盖缺口 / +inf 穿透 / 422 回显崩溃）→ 修复；第 2 轮发现 1 处（§2.5 插入顺序与一处措辞）→ 修复；纯审计轮零问题 → 通过

## 活体验证（15:10 重启后自检）

- **控制台重启**：15:10:20 自重启调度 → 15:10:22 `execv`（PID 24030 保留）→ 9776 绑定 → bge-m3 ready（2s）；并发二次实例 89779 正确复用自退；重启后无 ERROR/WARNING。
- **控制台契约 live 探针 9/9**：空 query / 缺 node_labels / node_labels=[] / 缺 group_id / 非法枚举 / max_results=9999 / 非法时间格式 → 全部 422；NaN/±Infinity raw → **干净 422**（input 净化为 `"nan"`/`"inf"`——§2.5 生效实样）。
- **MCP 层（重启后新 schema 实样）**：`max_results=9999` → MCP 进程内拒绝（`less_than_equal`）；`node_labels=[]` → MCP 进程内拒绝（`at least 1 item`）。
- **MCP 全链路读取**：`time_search` 合法请求 → `200 + 空结构 + error:null`（0.8s，warm）。
- **配置读回**：`REFLECT_NUDGE_INTERVAL_MIN=30` / `RESUME_ANALYSIS_ENABLED=1` / `PERMISSION_ASK_TIMEOUT_SEC=60`。
- **插件重启**：新进程（`systemTransformCount #1`，计数重置）；本会话任务目录与 flow 映射延续（`20261001_132521_31d6_security-analysis-evolve` / `flow-f9c2008d…`）；evolve 会话工具执行不写事件库（门控日志实样）。
- **未主动验证**：① 续跑完成态粘性——需真实"完成→压缩"周期，无法按需构造（插件已随重启加载；下次真实完成时观察日志 `跳过恢复 — 本轮分析已完成（等待用户新消息）`）；② 写入路径 202——避免在生产图库制造写入（本轮未改写路径逻辑）；③ e2e_real 未重跑（同上）。

## 待办 / 生效条件

- [x] **重启控制台** + **重启 opencode**（2026-10-01 15:10 完成；live 自检全绿）
- [ ] 提交（由用户执行；注意 `MM`/`AM`/`??` 状态需 `git add` 全量）

## 边界 / 同类排查

- 时间字段 naive（无时区）值仍接受；与库内 aware `created_at` 的比较行为未测（独立事项）
- `node_labels` 取值未做枚举（8 类型单一来源不在 events.py，硬编码会漂移）
- `min_mentions` 无上界（阈值语义，无自然上界）
- 数值宽松转换（如 `timestamp: "123"`）未固定断言（pydantic 默认宽松模式；非本次契约范围）
- e2e_real 未重跑（写路径合法 payload 与既有锚点逻辑不变；HTTP 契约已由 TestClient 全栈覆盖）
- 同类排查提醒：`/api/memory/*` 路由有自己的契约语义（空 question → `queued:false`），未纳入本次收紧
