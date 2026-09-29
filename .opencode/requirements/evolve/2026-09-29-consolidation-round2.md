# 2026-09-29 收口第二轮（归属验证落位校正 + §6 去重）— 实施需求

> 来源：用户复核两处落位/重复问题——① "共享基础设施与跨题资产"为 web 专属概念，此前计划落共享片段（4 个 agent 白付上下文）；② `retrospective-methodology.md` §6.1/§6.2 与 `commands/analysis-attribution.md` 实质重复（方案 A 只做了"声明单源"，未做"内容去重"）
> 关联：修订 `2026-09-29-single-source-consolidation.md`（→ v2）；修订 `2026-09-29-analysis-attribution-v2.md`（→ v4，蓝图同步）；修订 `2026-09-29-evidence-guards-and-bot-host-matrix.md`（→ v6，蓝图同步）
> 状态：已实施（2026-09-29；Phase 3/6 审计通过；as-built 见 `progress-2026-09-29-consolidation-round2.md`）
> 修订 v2（2026-09-29，收尾修正）：N8 由"指针"改为"整句删除"——evolve prompt 只写工具策略，复测/取证描述清零（路由 = retrospective-methodology §6 导航 → 命令）；行数 449→448

## §1 背景与目标

**来源痛点**：

1. **归属验证落位错误（两轮）**：先落 `ssrf-advanced.md`（过窄：只在 SSRF 场景加载）→ 再拟落共享片段（过宽：仅 web 适用却让 5 个 agent 常驻）。正确层级 = **web 专属常驻**（`agents/web-analysis.md` 核心原则，与 1-6 条同款先例）。
2. **§6 与命令重复**：§6.1（三源表 + 判据段）与 §6.2（检索复测）和命令的取证步骤/输出约定同句级重复；§6.3/§6.4 为 evolve 侧专用（不重复，保留）。

**目标**：

- ① 归属验证内容单点落位 `agents/web-analysis.md` 核心原则第 7 条；共享片段 `evidence-discipline.md` 删除该条（回退 2 条）；`ssrf-advanced.md` §7 整节删除、头部与 web 索引行去词。
- ② §6 去重：命令先吸收 §6.2 独有要点（命中→归因分类；禁止直查代答）并删除 L13 的 §6 反向引用；§6 改导航段、§6.3/§6.4 顺延为 §6.1/§6.2；evolve prompt 两处 §6.2 引用改指命令。

**预期收益（四维）**：准确度（消双源、消指针环）；速度（无影响）；上下文（4 个非 web agent 各 -1 行；web ±0；§6 净缩 ~13 行；evolve prompt 行数不变）；轮次无变化。

## §2 技术方案

### 2.1 架构影响图（6 个运营文件 + 记录）

```
agents-rules/evidence-discipline.md          ← 删归属验证条（-1 行；5 agent 各 -1）
agents/web-analysis.md                        ← 核心原则 +第 7 条（+1）；ssrf 索引行去词（行内）
web-analysis/knowledge-base/ssrf-advanced.md  ← §7 整节删除（-8 行）；头部去词（行内）
commands/analysis-attribution.md              ← L13 去 §6 反向引用；步骤 2 复测 bullet 吸收独有要点
security-analysis-evolve/knowledge-base/retrospective-methodology.md ← §6.1/6.2 删、导航段、6.3/6.4 顺延
agents/security-analysis-evolve.md            ← L18 / L63 两处 §6.2 引用改指命令（行内，行数不变）
records: consolidation(v2) / attribution-v2(v4+蓝图) / evidence-guards(v6+蓝图) / 3×progress + 本需求 progress
```

### 2.2 目标态文本（逐字落地）

**N1（`agents/web-analysis.md` 核心原则第 7 条，紧接现有第 6 条）**：

```
7. **线索归属先于投入** — 高价值线索（凭据/密钥/token/内部数据）先做归属验证，再决定是否继续投入：① 它在当前目标有没有一个能用的入口？② 目标要拿的结果是否需要这类线索？③ 它是否更像同一环境里其它任务的东西？①、②都答"不" → 标注"来源存疑（疑似其它任务资产）"、降低优先级、停止为它增加尝试并记入台账；典型诱饵：与目标功能无交集的库/配置条目、为其它任务配置的代理/缓存/凭据服务；止损后把预算转回目标本身。
```

**N2（`agents-rules/evidence-discipline.md` 终态全文，2 条）**：

```
- 分析结果必须区分"观测"（来自原始材料与工具输出）和"推测"（AI 推理，标注置信度）
- 禁止编造结论或目标值（如 flag）。置信度不足时，输出当前分析状态、已确认的观测、待验证的假设（标注置信度），继续自主探索，不要停下来向用户提问
```

**N3（`ssrf-advanced.md`）**：删除 §7 整节（"## 7. 共享基础设施与跨题资产"至"止损后去向"条）；头部行去词：

```
> 云元数据全目录、URL 解析器差异、gopher/dict 注入、DNS 重绑定、PDF 生成器 SSRF、内网服务利用。
```

**N4（`agents/web-analysis.md` ssrf 索引行）**：

```
| `ssrf-advanced.md` | SSRF 进阶（IP 变体表/黑名单边界验证/gopher 协议/云元数据/302 升级/Dict·FTP·LDAP 利用） |
```

**N5（命令 L13）**：

```
**执行权威：本文**（触发、输入解析、取证步骤、输出格式、约束的单一来源）。
```

**N6（命令取证步骤 2 第二条，吸收 §6.2 独有要点）**：

```
   - 直读仅用于存储/索引状态审计；**检索质量复测必须走真实检索路径**——派发 memorist 用目标关键词（英文标识符原样）复测，要求逐字返回 id + question，**禁止直查数据库/按 id 反查代答**（否则测的不是检索本身）；命中 → 原调用属检索时机/关键词问题，未命中 → 查存储与向量索引状态；无权限/不可用时标注"未复测"并列入遗留。
```

**N7（`retrospective-methodology.md` §6 目标态：删除 6.1/6.2 内容，6.3/6.4 顺延）**：

```
## 6. 审计取证方法

### 6.1 prompt / 知识库提交评审清单
（原 §6.3 内容不变）
### 6.2 索引触发条件质量判据
（原 §6.4 内容不变）
```

**N8（evolve prompt 两处，v2 修正：整句删除；理由：evolve prompt 只写工具策略，规程单源在命令、路由走 retrospective §6 导航）**：

```
L17-18 注释：删除「、检索质量复测走真实检索路径（commands/analysis-attribution.md 取证步骤 2）」（合并为单行）
L63 工具策略：删除「、检索质量复测须走真实检索路径（见 $OPENCODE_ROOT/commands/analysis-attribution.md 取证步骤 2）」
```

### 2.3 与现有文档的关系

- 本需求是 `2026-09-29-single-source-consolidation.md` 的**第二轮收口**（其 N3 的"ssrf 指针+补充"被本轮"整体撤除"取代；其 §6 导航声明被本轮"§6 实质去重"补完）。
- 归属验证的最终家：`agents/web-analysis.md` 核心原则 #7（web 专属常驻）——落位判据 = 概念适用范围（web）× 触发可靠性（常驻）。
- 去重后运营面单源：归属验证内容仅 web 原则 #7 一处；归因/复测执行内容仅命令一处；§6 只保留 evolve 侧两类清单。

## §3 实现规范

### 3.1 实施步骤拆分

**步骤 1. 归属验证落位校正（N1-N4 + 记录）**
- 文件：`agents/web-analysis.md`、`agents-rules/evidence-discipline.md`、`web-analysis/knowledge-base/ssrf-advanced.md`、`2026-09-29-evidence-guards-…md`（v6：T2/T4 蓝本改"已撤"说明）、`2026-09-29-single-source-consolidation.md`（v2）、2×progress
- 预估行数：运营面 +1/-9 左右；记录若干
- 验证点：① N1-N4 逐字对照；② 断言：运营面"归属验证/来源存疑"仅 `agents/web-analysis.md` 一处；三问文本在 agents-rules/ 与各 KB 零命中；③ 证据防线批次检查口径更新（T2/T4 改"已撤"断言）；④ 展开行数复算（web 431；其余 4 agent 各 -1）
- 依赖：无

**步骤 2. §6 去重（N5-N8 + 记录）**
- 文件：`commands/analysis-attribution.md`、`retrospective-methodology.md`、`agents/security-analysis-evolve.md`、`2026-09-29-analysis-attribution-v2.md`（v4 + 蓝图 L13/步骤 2 同步）、2×progress
- 预估行数：§6 净缩 ~13 行；命令行内；evolve prompt 行内
- 验证点：① N5-N8 逐字对照；② 命令蓝图 diff 复跑全 True；③ 断言："§6.2"运营引用零命中（历史文档除外）；§6 内"三源/判据/复测规则"零残留（仅导航句）；④ 六.3/六.4 顺延后编号连续
- 依赖：无

**步骤 3. 收尾核查**
- 文件：全部被改文件 + 本需求 progress
- 验证点：① 三组蓝本与落盘一致性（命令蓝图 diff、N1/N7 文本断言）；② 不可见字节扫描（全部被改文件）；③ 展开行数终值记录（web 431 / ai 417 / binary 450 / mobile 408 / crypto 321；binary 450 仍属 450-600 建议区，沿用既有提取建议）；④ progress 全部写入；⑤ 引用单向性检查（§6→命令 有；命令→§6 无）
- 依赖：步骤 1-2

## §4 验收标准

**功能验收**：N1-N8 逐字落盘；归属验证内容运营面单源（web 原则 #7）；归因/复测执行内容单源（命令）；§6 仅余两类清单（编号连续）。
**回归验收**：命令蓝图 diff 全 True；命令行数 77 不变或 ±1；web-analysis.md +1 行（431 展开）；其余 4 agent 各 -1 行；无"先读它再动手"类旧引用残留；evolve prompt 行数记录（收尾修正后 448）。
**架构验收**：改动落位合规（agents/、agents-rules/、commands/、evolve KB、web KB）；引用单向（§6→命令）；未引入 docs/ 或绝对路径引用。

## §5 与现有需求文档的关系

- 修订 `2026-09-29-single-source-consolidation.md`（→ v2）、`2026-09-29-analysis-attribution-v2.md`（→ v4）、`2026-09-29-evidence-guards-and-bot-host-matrix.md`（→ v6）。
- 三条修订线均由本需求的"落位校正 + 去重"驱动，审计与实施记录以本需求为准。
