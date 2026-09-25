# 2026-09-23 evolve prompt 瘦身（635 → <450）

> 状态：已执行（2026-09-25 由 `2026-09-25-knowledge-system-restructure.md` 步骤 7 合并落地: 641→439 行 <450; 实际执行含索引表误伤修复，详见 progress-2026-09-25-knowledge-system-restructure.md）
> 触发债务：`2026-09-22-selfcheck-noise-fixes.md` §5 约定"若后续需往 evolve prompt 新增内容，先立瘦身需求"；`2026-09-23-mechanism-corrections-and-retro-methodology.md` S8 新增 1 行触发红线——本文档兑现该约定，解除下一次增改被 600 行红线阻塞的状态

## §1 背景与目标

**来源痛点**：`security-analysis-evolve.md` 展开行数 **635 > Phase 4.5 红线 600**（本次机制更正新增 1 行索引落地时确认）。该 prompt 无真占位符（L47/L215 的 `{{buwai-rule:...}}` 是架构图与流程说明文字，非可展开占位符），故展开行数 = 文件行数。

**目标**：按 Phase 4.5 渐进式披露原则，把"特定场景才需要"的块提取到 `$AGENT_DIR/knowledge-base/`，展开行数降至 **<450**；主 prompt 每块保留"触发条件 + 核心规则（3-10 行）"。

**预期收益（四维度）**：减少上下文占用**显著**（该 prompt 每轮注入，是运行时阅读成本最高的一份文件）；轮次/速度中性；准确度中性（不改变行为，只改变加载路径）。

## §2 技术方案

### 2.1 块清单与提取去向（行号基于当前 635 行版本）

| # | 块（行号） | 大小 | 去向 | 主 prompt 保留 | 净减 |
|---|-----------|------|------|---------------|------|
| X1 | 架构树 + 归属规则 + 依赖方向 + Plugin hooks（39-113） | 75 | `architecture-map.md`（新） | 3-5 行：产出归属速查 + "禁止反向依赖" | ~65 |
| X2 | 变量表（119-130） | 12 | `architecture-map.md` 附录 | 0（值由环境每轮注入，需要时查 KB） | ~10 |
| X3 | 四维度量（280-300）+ 价值评估框架（329-356） | 49 | 主 prompt 内合并压缩（不提取） | 合并为单节 ~30 行 | ~19 |
| X4 | 反模式警告（301-313） | 13 | `evolution-playbook.md`（新） | 2 行指针（触发：提议改动/写候选方案时） | ~11 |
| X5 | 高风险改动表（314-328） | 15 | `evolution-playbook.md` | 2 行：高风险=六类改动、必须全下游端到端验证 | ~12 |
| X6 | 规则 7 长文档编辑策略（473-490） | 18 | `long-document-editing.md`（新） | 2 行：>300 行禁全量 Write、分段 Edit | ~16 |
| X7 | 规则 8 的"为什么是铁律"段（~496-510） | ~7 | 追加至 `knowledge-writing-guide.md` | 硬规则条目全保留 | ~6 |
| X8 | 规则 9 的原因段（~535-540） | ~5 | 压缩为 1 行（不搬运） | 铁律条目全保留 | ~4 |
| X9 | 规则 12 自检清单（555-570） | 16 | 追加至 `knowledge-writing-guide.md`（该文件在 KB 写入前必读，天然适配） | 1 行指针 | ~15 |
| X10 | OpenCode 开发知识库 + 源码参考（571-604，含其索引表） | 34 | `opencode-references.md`（新） | 2 行指针（触发：涉及 Plugin/Agent 开发时） | ~32 |
| X11 | 异常处理表（623-635） | 13 | `evolution-playbook.md` | 2 行指针（触发：验证点连续失败/审计不收敛/需求本身有问题） | ~11 |

合计净减约 **201 行** → 预计落至 **~434 行**。

### 2.2 涉及文件

- **新增 4 个 KB**（均放 `$AGENT_DIR/knowledge-base/`）：
  - `architecture-map.md` — 架构树、归属规则、依赖方向、Plugin hooks、环境变量表（X1+X2）
  - `evolution-playbook.md` — 反模式、高风险改动、异常处理（X4+X5+X11）
  - `long-document-editing.md` — >300 行文档编辑策略（X6）
  - `opencode-references.md` — 开发知识库索引 + 源码查阅流程（X10）
- **修改 2 个文件**：主 prompt（`security-analysis-evolve.md`）、`$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`（X7+X9 并入）

### 2.3 约束

- **规则号 / Phase 号不得变更**：全仓大量历史需求与进度文档按"规则 8.0""规则 1.5""Phase 4.5"引用编号，提取只搬内容、不改编号
- 主 prompt 保留的"核心规则"须足以避免未加载 KB 时犯关键错误；KB 自包含、遵守知识编写规范（无来源叙事、场景驱动、可操作）
- 引用格式统一 `$AGENT_DIR/knowledge-base/<file>.md`，不硬编码绝对路径
- 提取后同步修订主 prompt 内的交叉引用（指向被移动段落的引用改指 KB；指向主 prompt 内保留规则的引用不动）

### 2.4 风险

- 架构树移出后，文件放置类决策依赖 KB 加载 → 触发条件写死"新增/移动文件、判定归属前必读"，并以保留的归属速查表兜底
- 异常处理/反模式移出后，边缘时刻可能漏读 → 触发条件用可观察形态反复写进主 prompt 保留行

## §3 实现规范

### 3.1 实施步骤

**S1. 交叉引用盘点**
- 范围：全仓 grep `规则 [0-9]|Phase [0-9]|§[0-9]`（重点：`requirements/evolve/*`、各 agent prompt、`agents-rules/*`）
- 产出：替换清单（哪些引用需改指 KB、哪些保持不变）
- 验证点：清单覆盖全部命中；"编号不变"不变量确认

**S2. 提取 X1+X2 → architecture-map.md**
- 文件：主 prompt（39-130 区域）+ 新 KB | 预估：KB ~85 行；主 prompt 净减 ~75 行
- 验证点：主 prompt 剩"归属速查 + 禁止反向依赖"；KB 自包含（树/归属/依赖/hooks/变量齐全）

**S3. 合并 X3（四维度量 + 价值评估框架）**
- 文件：主 prompt（280-300 + 329-356 区域） | 预估：净减 ~19 行
- 验证点：合并单节含四维度表 + 分级表 + 评估模板；Phase 1 内"见四维度量"引用仍有效

**S4. 提取 X4+X5+X11 → evolution-playbook.md**
- 预估：KB ~41 行；主 prompt 净减 ~34 行
- 验证点：三块完整迁入；主 prompt 保留高风险六类 + 异常可观察触发条件

**S5. 提取 X6 → long-document-editing.md；X7 → guide；X8 压缩**
- 预估：净减 ~26 行
- 验证点：规则 7 步骤完整迁入；guide 新增小节自包含；主 prompt 保留 2 行核心

**S6. 提取 X9 → knowledge-writing-guide.md（自检清单节）**
- 预估：guide 增 ~16 行；主 prompt 净减 ~15 行
- 验证点：清单条目完整；主 prompt 保留 1 行指针；规则 12 编号保留

**S7. 提取 X10 → opencode-references.md**
- 预估：KB ~36 行；主 prompt 净减 ~32 行
- 验证点：表格 + 查阅流程完整迁入；主 prompt 保留 2 行指针（触发=涉及 Plugin/Agent 开发时）

**S8. 全量校验**
- 验证点：`wc -l` 展开行数 **<450**；逐块核对"触发 + 核心规则"在位；全仓抽查交叉引用无断链；新 KB 无来源叙事词

### 3.2 编码规则

- 主 prompt 编辑遵循规则 7（分段 Edit，禁全量 Write）
- 本需求本身属于"修改 Agent prompt"高风险改动 → S8 走查按规则 6 做端到端阅读验证（模拟"改知识库→审计→实施"链条，确认每个指针可达且核心规则不缺）

## §4 验收标准

**功能验收**：展开行数 <450；§2.1 十二块全部处理（提取/合并/压缩）；每块在主 prompt 留有"触发 + 核心规则"。
**回归验收**：规则号/Phase 号全仓引用仍有效（按 S1 清单逐条核对）；四维度量、审计节奏、验证方式、异常触发等高频要素在主 prompt 可直接读到（不需加载 KB）。
**架构验收**：4 个新 KB 位于 `$AGENT_DIR/knowledge-base/`；guide 增补后仍自包含；无新跨层依赖。

## §5 与现有需求文档的关系

- 兑现 `2026-09-22-selfcheck-noise-fixes.md` §5 约定；承接 `2026-09-23-mechanism-corrections-and-retro-methodology.md` S8 的红线债务
- 实施后 evolve prompt 的下一次增改不再被 600 行红线阻塞
