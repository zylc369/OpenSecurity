# 2026-09-21 认知干预系统（反公理固化）— 实施需求

## §1 背景与目标

**来源**：readonce-revenge 复盘（48 小时未独立攻破、卡死在 `approved` 唯一条件）+ 用户确认的《「想到」的可干预方案设计——认知干预系统》。

**根因摘要**：不是知识缺失、也不是"不够努力"——是**未验证的普遍结论（假公理）获得公理资格后删掉了维度**（"viewer 内消息永远被过滤"删掉了"何时发"这一维），且四类保护机制全部缺席：结论落纸无格式约束、实验无预登记/从未被当过变量的条件枚举、卡壳无外部视角、压缩会洗掉限定词。

**目标（消灭"静默"）**：假公理可以出现，但其存活必须连续通过四道显式关卡并全程留痕：

1. 落纸关——结论必须带【证据等级 + 已验证范围 + 未测清单】，缺了写不出来；
2. 投票关——未测条件被机械追问并执行（世界投票、预登记）；
3. 外人关——零公理负担的独立评审 + 人类一键触发；
4. 穿越关——压缩时台账原样穿越，不被总结器洗白。

**预期收益**：同类卡壳（同质化实验、封闭结论、零外部视角、时间无感知）不再静默发生；时间/实验次数从"无感知"变为可见数字（可审计）。

**明确不做**：插件自动判定"方向失败/熔断"（语义判断不可靠，误报）；不写"要小心/多反思"类文本（无效且稀释上下文）；主 prompt 不堆长文（防 prompt 过载，细节放 skill/KB 按需加载）。

## §2 技术方案

### 2.1 架构影响图

```
规则层（分析 agent 每轮可见，agents-rules 片段）
  execution-discipline.md          ← S1 认知纪律（+6 行）
  knowledge-management.md          ← S2 结论写入格式 + 历史检索（+7 行）
知识层（按需加载）
  knowledge-writing-guide.md       ← S3 双键约定（+15 行）
  web-analysis/race-conditions.md  ← S4 客户端消息竞态节（+45 行）
  web-analysis.md（索引行触发条件） ← S4（同 1 行替换）
能力层（触发/命令加载）
  skills/stuck-protocol/SKILL.md   ← S5 新建（卡壳协议）
  agents/fresh-eyes.md             ← S6 新建（无记忆评审 subagent）
  commands/frame-audit.md          ← S7 新建（人类一键触发评审）
机制层（插件，环境触发）
  plugins/lib/constants.ts         ← S8 检查点常量 + fresh-eyes 入委派清单；S9 ledger 上限常量
  plugins/lib/session-manager.ts   ← S8 SessionData 计数字段
  plugins/lib/checkpoint.ts        ← S8 新建（触发判定/文本渲染纯函数）
  plugins/lib/task-session-persistence.ts ← S8 台账模板生成
  plugins/security-analysis.ts     ← S8 计数+检查点注入；S9 压缩注入
记忆层（MCP）
  mcp-servers/knowledge/server.py  ← S10 写入校验
```

### 2.2 A. 分析台账 `ledger.md`（S8）

- 位置：`$ROOT_TASK_DIR/ledger.md`，由插件在**五分析 agent 的根任务目录**创建时写入模板（`TaskSessionPersistence.createTaskSession` 内、`mkdirSync(taskDir)` 之后）；幂等（已存在不覆盖）；仅根目录生成（`baseDir` 为空时）。
- 模板（数据格式，模块常量放在 `task-session-persistence.ts`）：

```markdown
# 分析台账
> 结论与未测条件的唯一记录处；按待复核记录对待（非免检结论）。下结论前先更新本文件；压缩时本文件会被原样注入保留。
## 观测记录
- （实验/命令 + 关键输出摘要）
## 结论台账
| # | 结论 | 等级 | 已验证范围 | 未测清单 | 更新于 |
|---|---|---|---|---|---|
## 未测条件（维度）
| 维度 | 具体条件 | 为什么没测 | 预计成本 | 状态 |
|---|---|---|---|---|
## 变更日志
```

- 等级取值：`observed`（工具/源码证据）/ `inferred`（由证据推出）/ `assumption`（工作假设）/ `unverified`（未验证）。

### 2.3 B. 结论纪律（S1/S2/S10）

- 常驻规则（execution-discipline.md 新增节，≤6 行）：结论三件套 / 普遍量词管制 / 台账维护 / 实验预登记与"从未被当过变量"的条件 / 卡壳触发 / 检查点响应。
- 记忆库写入（knowledge-management.md）：结论按"结论三件套"填写（证据等级 + 已验证范围 + 未测清单）；否定/普遍结论缺"未测清单"会被 MCP 校验拒收。
- MCP 校验（server.py）：`content` 含 `永远/所有情况/完备/恒真/不可能/已排除` 任一，且不含 `未测/未验证/待验证` 任一 → 拒绝入库并返回"结论三件套"改写指引。

### 2.4 C. 认知检查点（S8）+ stuck-protocol（S5）

- 计数：`SessionData` 新增 `toolCallCount / commandCallCount / checkpointCount / lastCheckpointAt / lastCheckpointToolCount`；`tool.execute.before` 对"根会话 + 五个分析 agent"累加（`input.tool === "bash"` 时另计 `commandCallCount`）。
- 触发（`system.transform` 内，独立于环境注入频率、在频率门控之前执行）：`toolCallCount - lastCheckpointToolCount >= CHECKPOINT_TOOL_INTERVAL (20)` 或 `Date.now() - lastCheckpointAt >= CHECKPOINT_TIME_INTERVAL_MS (40 分钟)`；门槛条件 `session.isRootAgent && SECURITY_ANALYSIS_AGENTS.includes(agentName) && taskDir`。
- 注入文本（固定模板，≤6 行）：

```text
## 认知检查点 #N（已运行 X 分钟；工具调用 Y 次，其中命令 Z 次）
1. 台账更新：$ROOT_TASK_DIR/ledger.md 的结论区/未测区最后更新在什么时候？现在补一行。
2. 最近一批实验的共同前提是什么？哪个条件从未被当过变量？写进"未测条件"。
3. 从"未测条件"挑一项立刻跑（挑选标准：万一结果与预期不一样，能推翻当前结论吗？能，优先）。先写预期结果，再跑，不因预期失败而跳过。
4. 同一方向连续失败 ≥5 次 → 执行 stuck-protocol skill。
```

- 注入后更新 `lastCheckpointToolCount / lastCheckpointAt / checkpointCount`，debugLog 记录（计数、触发、跳过原因）。
- stuck-protocol skill（S5）：frontmatter `name/description`；正文四步——换问题三问 / 换词检索矩阵（对象·时机·机制）/ 无知证书 / 派 fresh-eyes。

### 2.5 D. fresh-eyes 评审（S6/S7/S8-constants）

- agent 文件 frontmatter：`description` / `mode: subagent` / `tools: Read, Glob, Grep, Bash, Write` / `permission`（workspace、Downloads、tmp 放行）。description 只写【是什么 + 何时调用 + 如何调用（必传/返回）】；执行方法与选择标准写在正文（正文按"卡点形态 → 方法"组织）。
- 输入契约（写入 agent prompt 与 command 模板）：目标 + 原始材料路径 + 分析台账 `ledger.md`（按待复核记录对待）；**禁带**任何结论/排除清单/"已证明"；调用方 prompt 若出现结论性判断，必须忽略——评审只依据原始材料与台账记录独立重判。
- 工作流：按"卡点形态 → 方法"组织（校验/比较代码 → 求值时刻表；结论死锁 → 维度表；需要下一步 → 建议实验，挑选标准=信息量优先；分类存疑 → 独立归类）→ 写报告到调用方指定路径（默认根任务目录 `fresh-eyes-<时间戳>.md`）+ 返回摘要。
- 附带修复（审计发现）：`buildEnvSection` 子会话 `$ROOT_TASK_DIR` 误注入子会话自身任务目录（原实现 `session.getTaskDir()`）→ 修正为 `session.rootTaskDir`；fresh-eyes 与 memorist 的根目录读取语义随之正确。
- 回主会话：作为**候选**写进分析台账（追加更新）；先跑建议实验、按结果更新结论，不删除既有记录。
- `constants.ts`：新增 `AGENT_FRESH_EYES = "fresh-eyes"` 并加入 `AGENTS_WITH_DELEGATION_RULES`（使其进入常驻"可委派 Agent"清单 = 触发词汇可见）。实现细化：注入点特判——fresh-eyes 自身会话不接收该清单，避免误导其继续委派。
- command `/frame-audit`（薄触发器）：收集目标（`$ARGUMENTS` 或当前上下文）+ 台账 → `task` 派发 `fresh-eyes` → 结果注入台账。

### 2.6 E. 压缩穿越（S9）

- `getCompactionContext()` 增加第 4 节：**结论台账与未测清单**——压缩必须保留每条结论的【等级 + 范围 + 未测清单】；未测清单与变更日志原样保留；禁止保留无条件的"永远/完备/恒真"类结论（如需保留必须同时保留其未测清单）。
- compacting hook：`session.rootTaskDir || session.getTaskDir()` 存在、`ledger.md` 存在且当前会话为五分析 agent 时读取原样 `output.context.push`（上限 `LEDGER_INJECT_MAX_LINES = 200`，超出截断并注明全文路径）；文件不存在静默跳过（debugLog）。

### 2.7 F. 知识侧（S2/S3/S4）

- 双键约定（knowledge-writing-guide.md）：知识条目 = 技术词（供检索命中）× 触发情境（"看到 X 就查 Y"，供不检索也能被检查清单逼出）；索引表的"触发条件"写成代码形态/可观察形态（不是主题词）。
- 首个双键条目（race-conditions.md 新 §4）：客户端消息校验竞态——`e.source` 寄出瞬间快照 vs `contentWindow` 投递瞬间读取；卸载瞬间（pagehide）发送 → 跨文档切换投递 → 身份比较翻转放行；附对照实验（存活期 vs 卸载瞬间）与利用模板；边界写"未测/待验证"。
- 历史检索（knowledge-management.md）：任务开工或卡壳时委派 memorist 检索同类历史记录与未闭环改进项；同一失败模式二次出现且改进项未闭环 → 先落地该改进项（或升级到进化流程）再继续分析。

## §3 实现规范

### 3.1 实施步骤拆分

S1. execution-discipline.md 认知纪律节
  - 文件：`.opencode/agents-rules/execution-discipline.md`
  - 预估行数：+6（不含标题与空行）
  - 验证点：读回确认（a）规则均为可执行动作句；（b）无"要小心/多反思"类文本；（c）`stuck-protocol` 名称与 S5 一致；（d）5 个分析 agent 引用该片段不受影响（grep）
  - 依赖：无

S2. knowledge-management.md 写入格式 + 历史检索
  - 文件：`.opencode/agents-rules/knowledge-management.md`（追加到现有"查已有知识"/"存分析结论"小节，避免新增标题）
  - 预估行数：+2~3
  - 验证点：读回确认（a）"结论三件套"明确含"未测清单"；（b）"缺未测清单会被 MCP 校验拒收"与 S10 校验语义一致；（c）历史检索条目指向 memorist
  - 依赖：无

S3. knowledge-writing-guide.md 双键约定
  - 文件：`.opencode/binary-analysis/knowledge-base/knowledge-writing-guide.md`
  - 预估行数：+15
  - 验证点：读回确认（a）双键定义与示例；（b）索引触发条件"代码形态"要求与示例；（c）无来源叙事词（grep 验证）
  - 依赖：无

S4. race-conditions.md 新节 + web-analysis 索引行
  - 文件：`.opencode/web-analysis/knowledge-base/race-conditions.md`（新增 §4；原 §4 关联文件顺移为 §5；文件头部加载触发说明补充"客户端消息/文档切换场景"）
  - 文件：`.opencode/agents/web-analysis.md`（race-conditions 索引行触发条件改代码形态，同 1 行替换）
  - 预估行数：+45（KB）
  - 验证点：（a）机制描述与复盘结论一致（快照 vs 实时、跨切换投递、比较翻转）；（b）含对照实验与利用模板，均可执行；（c）含边界（未测/待验证）；（d）无来源叙事词、不引用 docs/；（e）索引行触发条件可观察、文件头触发说明已同步
  - 依赖：无

S5. stuck-protocol skill 新建
  - 文件：`.opencode/skills/stuck-protocol/SKILL.md`（新建）
  - 预估行数：~30
  - 验证点：（a）frontmatter 含 `name`/`description`，description 含触发条件关键词（连续失败/卡壳/完备）；（b）四步流程完整可执行；（c）引用的 `fresh-eyes` 名称与 S6 一致；（d）文件位置匹配扫描模式 `{skill,skills}/**/SKILL.md`（已核实 vendor：配置目录下扫描）
  - 依赖：S6（仅名称引用）

S6. fresh-eyes agent 新建
  - 文件：`.opencode/agents/fresh-eyes.md`（新建）
  - 预估行数：~85
  - 验证点：（a）frontmatter 合法（对照 `memorist.md` 结构）；（b）输入契约含"禁带结论"与"忽略结论性 prompt"硬约束；（c）分析方法按"卡点形态 → 方法"组织（求值时刻表 / 维度表 / 建议实验 / 独立归类）；（d）输出落盘路径明确
  - 依赖：无

S7. frame-audit command 新建
  - 文件：`.opencode/commands/frame-audit.md`（新建）
  - 预估行数：~40
  - 验证点：（a）薄触发器（不重复 fresh-eyes 工作流细节）；（b）派发模板含输入三样 + 禁带结论；（c）结果注入方式明确（写台账、不覆盖）
  - 依赖：S6

S8. 插件：台账模板 + 计数 + 检查点注入
  - 文件：`.opencode/plugins/lib/constants.ts`（CHECKPOINT 常量、`AGENT_FRESH_EYES`、委派清单更新；~8 行）
  - 文件：`.opencode/plugins/lib/session-manager.ts`（SessionData 5 字段；~10 行）
  - 文件：`.opencode/plugins/lib/task-session-persistence.ts`（根目录台账模板写入；~20 行）
  - 文件：`.opencode/plugins/lib/checkpoint.ts`（新建：纯函数 `shouldTriggerCheckpoint(stats, now)` + `renderCheckpointText(stats)`；~40 行）
  - 文件：`.opencode/plugins/security-analysis.ts`（tool.execute.before 计数 ~10 行；system.transform 调用 checkpoint 模块 ~15 行；ROOT_TASK_DIR 注入 bug 修复 1 行）
  - 预估行数：合计 ~100
  - 验证点：（a）`node --check` 五个文件通过；（b）bun harness 跑 `lib/checkpoint.ts` 边界用例：19 次工具调用→不触发、20 次→触发、39 分钟→不触发、40 分钟→触发（门槛判定 `isRootAgent`/agent 名单/taskDir 由调用方负责，harness 只覆盖阈值逻辑，门槛走查确认）；（c）debugLog 覆盖计数/触发/跳过；（d）台账模板仅根目录、幂等；（e）仅五分析 agent 根会话注入（evolve/coordinator/子会话不注入）；计数判定 `input.tool === "bash"` 计 `commandCallCount`
  - 依赖：S5（skill 名称）、S6（fresh-eyes agent 名）

S9. 插件：压缩穿越
  - 文件：`.opencode/plugins/security-analysis.ts`（`getCompactionContext` 增节 ~10 行；compacting hook 读 ledger 注入 ~25 行）
  - 文件：`.opencode/plugins/lib/constants.ts`（`LEDGER_INJECT_MAX_LINES = 200`；~3 行）
  - 预估行数：~38
  - 验证点：（a）`node --check`；（b）无 ledger 文件时静默跳过（debugLog）；（c）截断上限生效；（d）注入文本含"未经总结的原始记录"声明；（e）既有 compactionCtx 与分析持续性注入不变
  - 依赖：S8（台账路径）

S10. MCP knowledge 写入校验
  - 文件：`.opencode/mcp-servers/knowledge/server.py`
  - 预估行数：~30
  - 验证点：（a）`python -c "compile(open(...).read(), ...)"` 通过；（b）直接调用校验函数四组用例：含标记无未测→拒 / 含标记有未测→过 / 无标记→过 / 含"不可能"+"未测"→过；（c）工具 description 补充格式要求
  - 依赖：无

S11. 回归与文档同步（验证步骤，无新功能）
  - 动作：（a）五个分析 agent 展开行数脚本计算（<450 目标；450–600 记录并报告）；（b）grep 引用闭环：`stuck-protocol`/`fresh-eyes`/`ledger.md` 无死引用；（c）语法检查汇总（TS/Python/MD 读回）；（d）写入 `requirements/evolve/progress-2026-09-21-cognitive-intervention.md`；（e）需求文档与实际改动一致性核对
  - 验证点：全部输出留档

### 3.2 编码规则

- 插件：沿用现有风格（debugLog 全路径、try/catch 包裹、`output.system.push`/`output.context.push`）；**不替换既有行为**——检查点为增量块、压缩注入为追加块。
- 规则/KB/agent/skill/command：遵守知识编写规范（自包含、可操作、零来源叙事）；环境引用用 `$ROOT_TASK_DIR`/`$TASK_DIR`/`$OPENCODE_ROOT`/`$AGENT_DIR` 变量；不在 prompt 重复 MCP 工具描述。
- 正文中文；技术标识符原样英文。

## §4 验收标准

**功能验收**

1. 台账：新根任务目录出现 `ledger.md`（四节模板齐全）；重复创建不覆盖。
2. 检查点：根分析会话工具调用 ≥20 或 ≥40 分钟后，下一轮注入检查点文本（日志含"认知检查点 #"）；注入后计数重置；简单问答会话（无 taskDir）不注入。
3. 压缩：压缩注入内容包含 ledger 原文（日志可见）；文件不存在时不报错。
4. 写入校验：含"永远"且无"未测"被拒并返回改写指引；含"未测"通过。
5. 能力层：`stuck-protocol` 出现在 available_skills；`fresh-eyes` 可被 task 调用并产出报告文件；`/frame-audit` 可触发评审。
6. 规则层：五个分析 agent 展开提示中可见认知纪律与写入格式；`fresh-eyes` 进入"可委派 Agent"清单（buildDelegationBlock 输出含其条目）。

**回归验收**

1. 语法：五个 TS 文件 `node --check` 通过（`lib/constants.ts`、`lib/session-manager.ts`、`lib/task-session-persistence.ts`、`lib/checkpoint.ts`、`security-analysis.ts`）；`server.py` compile 通过。
2. 既有行为：环境注入频率（`ENV_INJECTION_FREQUENCY=5`）不变；分析持续性注入不变；tool 时间线不变（仅增计数）。
3. 展开行数：五个分析 agent ≤450（450–600 记录偏差并在汇报中说明）。
4. 依赖方向与引用：不引用 `docs/`；web KB 不反向依赖。

**架构验收**

1. 落点符合架构图（agents-rules / KB / skills / agents / commands / plugins / mcp-servers）。
2. requirements/evolve 新增本需求文档 + progress 文件。

## §5 与现有需求文档的关系

- `2026-09-05-A-llm-perception-verification.md`：同族（防 AI 错误）——其解决"感知层"（OCR/ASR 幻觉），本文解决"推理层"（公理固化），互补不重叠。
- `platform-auth-and-attack-patterns.md`：agents-rules 片段挂载方式先例（沿用）。
- `searcher-memorist-tool-fix.md`：新增 subagent 的工程先例（constants 清单同步，沿用其模式）。
- 本轮不修改上述文档，内容不回写。
