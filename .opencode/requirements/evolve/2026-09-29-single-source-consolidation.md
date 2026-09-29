# 2026-09-29 单源收口（归因执行单源 + 归属验证规则单源）— 实施需求

> 来源：① 用户拍板"方案 A"（归因执行细节单源到命令、§6 索引化）；② 用户指出的经典收口问题：`agents-rules/evidence-discipline.md` 与 `web-analysis/knowledge-base/ssrf-advanced.md` 双写"高价值线索"规则（同日 v2/v4 两次修订均需双文件同步，双维护漂移高危）
> 关联：修订 `2026-09-29-analysis-attribution-v2.md`（→ 其 v3）；修订 `2026-09-29-evidence-guards-and-bot-host-matrix.md`（→ 其 v5）
> 状态：已实施（2026-09-29；Phase 3/6 审计通过；as-built 见 `progress-2026-09-29-single-source-consolidation.md`）
> 修订 v2（2026-09-29，落位校正 + §6 去重）：N3 终态由"指针 + 补充"改为"整体撤除"（归属验证迁至 `agents/web-analysis.md` 核心原则 #7）；§6 实质去重（执行规程单源在命令，§6 改导航）——见 `2026-09-29-consolidation-round2.md`

## §1 背景与目标

**来源痛点**：

1. 归因内容重心已移到命令（v2 增补了取证细节/输出格式），但声明仍是"以 §6 为准，先读再动手"——声明与现实背离；evolve 侧也无发现路径（prompt 零提及）。
2. "高价值线索"三问规则在 evidence-discipline（常驻片段）与 ssrf-advanced §7（方向 KB）两处逐字并存——本轮两次修订均双改，属双维护漂移模式。

**目标**：

- ① 归因：执行细节（触发/输入/取证/输出/约束）单源到 `commands/analysis-attribution.md`；§6 保留判据定义与多场景索引，加单一来源指针（可选读）；
- ② 归属验证：规则文本单源到 `agents-rules/evidence-discipline.md`（各分析 agent 常驻）；`ssrf-advanced.md §7` 改为"指针 + SSRF 场景补充"（保留诱饵形态与止损后去向，不再重写三问）。

**预期收益（四维）**：准确度（消除双源漂移）；速度（归因执行省一次强制 Read；后续修订单点化）；上下文（§6 净 +1 行、ssrf 净 -1 行左右；命令行数不变）；轮次无变化。

## §2 技术方案

### 2.1 改动面

| # | 文件 | 改动 | 行数 |
|---|---|---|---|
| 1 | `commands/analysis-attribution.md` | L13 执行权威声明改写（替换"方法论唯一权威…以 §6 为准"+过时的"骨架"自述） | 1 行替换 |
| 2 | `security-analysis-evolve/knowledge-base/retrospective-methodology.md` | §6 顶部加单一来源指针行 | +2（含空行） |
| 3 | `web-analysis/knowledge-base/ssrf-advanced.md` | §7 首条改"指针+场景补充"、末条改"止损后去向"（去规则重写） | 行内替换（净 ~0） |
| 4 | `requirements/evolve/2026-09-29-analysis-attribution-v2.md` | §2.2 蓝图 L13 同步 + 修订 v3 行 | 行内 + 1 |
| 5 | `requirements/evolve/2026-09-29-evidence-guards-and-bot-host-matrix.md` | T4 蓝图首/末条同步 + 修订 v5 行 | 行内 + 1 |
| 6 | 两个 progress 文档 | 各追加修订记录 | 各 +1 |

### 2.2 关键文本（目标态，逐字落地）

**N1（命令 L13，整行替换）**：

```
**执行权威：本文**（触发、输入解析、取证步骤、输出格式、约束的单一来源；与 §6 冲突时以本文为准）。判据定义与三类审计场景索引见 `$OPENCODE_ROOT/security-analysis-evolve/knowledge-base/retrospective-methodology.md` §6（可选读）。
```

**N2（retrospective-methodology §6 顶部，"三类审计场景的取证路径……"行之后，独立成段）**：

```
机制贡献归因的完整执行规程（触发/输入/取证/输出/口径）单一来源：`$OPENCODE_ROOT/commands/analysis-attribution.md`；本文件保留判据与多场景索引（执行细节以该命令为准）。
```

**N3（ssrf-advanced.md §7：首条与末条替换，"典型诱饵形态"条不动）**：

首条替换为：
```
- **归属验证前置**：高价值线索（凭据/密钥/token/内部数据）先判断归属再决定是否继续投入。判据与动作（三问 + 触发条件）以通用证据纪律为单一来源：`$OPENCODE_ROOT/agents-rules/evidence-discipline.md` 的"归属验证"条（各分析 agent 常驻片段）；本节只保留 SSRF 场景特有内容。
```

末条替换为：
```
- **止损后去向**：把预算转回目标本身（谁持有高价值数据/会话、经什么路径暴露）。
```

### 2.3 与现有文档的关系

- 本需求是两处既有设计的**收口校正**：命令执行权威方向修正（原"以 §6 为准"）；归属验证规则去除双写。判据语义本身不变（三问、没有/错过、口径定义保持现状）。
- 修订记录落在各自既有需求文档（v3 / v5）与 progress，不另起历史。
- **自包含性说明**：ssrf §7 采用"指针而非重写"，依据 规则 8"不重复已有知识（引用而非重写）"；指针给出明确文件路径，且规则片段为各分析 agent 常驻（读取 ssrf 的 agent 上下文内即有该规则），不构成理解障碍。

## §3 实现规范

### 3.1 实施步骤拆分

**步骤 1. 归因单源：命令 L13（N1）+ §6 指针（N2）+ 蓝图同步（attribution v2 需求文档 §2.2 + v3 行 + progress 记录）**
- 文件：`commands/analysis-attribution.md`、`retrospective-methodology.md`、`2026-09-29-analysis-attribution-v2.md`、`progress-2026-09-29-analysis-attribution-v2.md`
- 预估行数：约 5 行内
- 验证点：① 逐字对照 N1/N2；② 命令蓝图 diff 复跑（v2 需求 §2.2 vs 落盘）全 True；③ grep 断言"执行权威：本文"存在且"先读它再动手"零残留
- 依赖：无

**步骤 2. 归属验证收口：ssrf §7（N3）+ 蓝图同步（evidence-guards 需求文档 T4 + v5 行 + progress 记录）**
- 文件：`ssrf-advanced.md`、`2026-09-29-evidence-guards-and-bot-host-matrix.md`、`progress-2026-09-29-evidence-guards-and-bot-host-matrix.md`
- 预估行数：净 ~0 行（行内替换）
- 验证点：① 逐字对照 N3；② 证据防线批次逐字 diff 复跑（T1-T6）全 True；③ 运营面断言：三问规则文本在 `agents-rules/` 与各 `knowledge-base/` 中仅 `evidence-discipline.md` 一处（ssrf 仅指针；需求文档蓝图与修订记录属历史，不计）
- 依赖：无

**步骤 3. 收尾核查**
- 文件：全部被改文件 + 本需求 progress
- 预估行数：+1（进度文件）
- 验证点：① 两组蓝图 diff 全跑（命令蓝本 + T1-T6）；② 不可见字节扫描（6 个被改文件）；③ 两个 progress 修订记录 + 本需求 progress 写入；④ 路径形式检查（`$OPENCODE_ROOT` 变量形式）
- 依赖：步骤 1-2

## §4 验收标准

**功能验收**：N1/N2/N3 逐字落盘；"归属验证"规则单源（evidence-discipline 一处全文 + ssrf 一处指针）。
**回归验收**：两组蓝图 diff 全 True；命令行数 77 不变；ssrf 净行数变化 ≤1；grep "先读它再动手" 零残留。
**架构验收**：改动落位合规；SSRF KB 对常驻片段的引用使用 `$OPENCODE_ROOT` 变量形式（与仓内路径规范一致）；未引入对 `docs/` 或绝对路径的引用。

## §5 与现有需求文档的关系

- 修订 `2026-09-29-analysis-attribution-v2.md`（→ v3）与 `2026-09-29-evidence-guards-and-bot-host-matrix.md`（→ v5）。
- 与用户会话确认的"方案 A"与"收口"要求一一对应；本需求自身为两条收口的执行记录。
