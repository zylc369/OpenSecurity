# 2026-09-27 知识优先策略（问题驱动 + 触发即读 + 观测优先）

> 状态：已实施（Phase 6 审计通过；v3 评审修订；v4 勘误）| 入口：复盘（You Are Kidding Me 机制贡献归因）→ 用户确认强版 + ai-security 瘦身 + 范围
> 修订 v2：检索触发由「开工先查」改为「问题驱动」（用户纠正：开工时无可检索对象）；crypto 标题行格式统一（+4 行）——§1/§2.1/§2.2/§2.3/§2.6/§3.1/§4 已同步
> 修订 v3（外部评审）：① 落盘裁剪「不豁免」长句（§2.1 fence/§2.7/§4 同步）；② ai-dialogue 手册补 summarize/scan 与策略文件示例（§2.4 同步）；③ 提取类验证改对照脚本地面真值
> 修订 v4（勘误）：撤除「长文档读章节」表述（该行为未落地、后续经用户否决；§1 已改）；`security-analysis-evolve.md` 标题一致性已由 d247f0f6 落地（§2.2/§5 已勾销）
> 实施进度与 as-built 记录：`progress-2026-09-27-knowledge-first-strategy.md`
> 关联：A 已落地（`2026-09-27-jwt-kid-defense-aware-upgrade.md`）——A 修内容质量，B′ 提升消费概率

## §1 背景与目标

**来源痛点**（复盘数据）：
1. 本次分析中 JWT/技术信号出现后，知识库读取 0 次——现有规则写"按需加载"（触发=模型主观"需要"），模型自信即跳过；索引的"触发条件"列实际无强约束。
2. 跳过读取 = 反馈闭环断裂：知识库的缺口与错误只有被"消费"才能暴露；本次缺口（kid 小节误导）是复盘偶然发现，而非使用时发现。
3. **检索触发语义不统一**：记忆库侧曾按"开工检索"设计——开工时尚未形成可检索的问题对象，为空转；知识库侧依赖索引触发条件。两处统一为"问题驱动"。

**用户决策**：强版语义（触发即读，"觉得会了"不豁免）；ai-security 顺带瘦身；范围=5 个分析 agent + 2 个共享片段。

**目标**：行为规范升级——① 本地知识先行顺序（记忆库 + 触发文档读取 → 模型知识补充/交叉验证 → 外部检索）；② 遇到相关问题先查（记忆库 + 知识库），检索由问题驱动而非开工；③ 问题信号命中索引触发条件 → 先读文档再动手；④ 冲突裁决以实际观测为准、差异报进化流程。

**预期收益（四维度）**：准确度显著（一致性 + 可维护知识源 + 缺口暴露闭环）；上下文轻微代价（命中时读取）；速度/轮次：快解任务 ±1 次 Read，未知领域任务可避免错向试错。

## §2 技术方案

### 2.1 B1 文本全文稿（插入 `agents-rules/knowledge-management.md`）

插入位置：第 5 行"分析过程中，遵守以下知识管理规则："之后、"### 查已有知识"之前。

```markdown
### 知识优先（先查再动手）

分析任务遵守**本地知识先行**顺序：**记忆库检索 + 知识库触发文档读取 → 模型知识补充与交叉验证 → 外部检索（searcher）**。
- **遇到相关问题先查**：识别出技术栈、漏洞类型、机制或具体障碍等信号时，先检索记忆库（同类记录与历史教训；memorist 或直查 MCP）、读取命中触发条件的知识库文档，再针对该问题形成假设或动手。检索由具体问题驱动，不设"开工检索"规定动作（问题未成形前无可检索对象）。
- **冲突裁决**：知识库/记忆库内容与实际观测冲突 → 以实际观测为准并标注差异，向用户报告该条目待修订（走进化流程）；不得因个别条目存疑而整体跳过读取。

```

净增量 **+6 行**（23 → 29 行）。与既有条目兼容性：既有"需要确定分析方向时"（深化查）不改；"吸取历史教训"条目同步改为问题驱动表述（原"任务开工或卡壳时"→"遇到具体问题或卡壳时"）。

### 2.2 文件改动清单

| # | 文件 | 改动点 | 行数 |
|---|------|--------|------|
| B1 | `agents-rules/knowledge-management.md` | 新增「知识优先」小节（上文全文稿）；"吸取历史教训"条目同步改表述 | +6 |
| B2 | `agents-rules/analysis-planning-rules.md` | 第 4 行规则 3 替换 | 1 行替换 |
| B3 | `agents/{web,binary,mobile,ai,crypto}-analysis.md` | 索引标题行（§2.3）；crypto 格式统一 +4 行 | 4×1 行替换 + crypto +4 |
| B4 | `agents/ai-security-analysis.md` + 新建 `ai-security-analysis/knowledge-base/ai-dialogue-usage.md` | ai-dialogue 详述（:166-220，55 行）抽至知识库，prompt 留指针段（§2.4）；KB 索引 +1 行 | 净 -43 |

**明确不做**：给读取设任何跳过豁免（用户定强版）；改 searcher/memorist 工作流；改 Plugin（片段文件名不变，展开机制不变）；改 `security-analysis-evolve.md` 的"按需加载索引"标题（其不消费本两片段；记为一致性观察，留待后续；**已落地** d247f0f6：标题统一为「触发即读」）。

### 2.3 B3 标题行统一文案

- 4 个 agent（web:165 / binary:195 / mobile:154 / ai:230）：
  `以下文档按需加载（不在分析开始时全部读取）：` → `以下文档触发即读（命中触发条件先读再动手；不在分析开始时全部读取）：`
- crypto（标题行内嵌，改为与其余 4 个一致的联合格式）：
  `## 知识库索引（$AGENT_DIR/knowledge-base/，按需加载）` → `## 知识库索引` + `以下文档触发即读（命中触发条件先读再动手；不在分析开始时全部读取）：` + `### 密码学知识库（$AGENT_DIR/knowledge-base/）`（三段式，+4 行）

### 2.4 B4 抽取方案

**源区间**：`ai-security-analysis.md:166-220`（### 目标模型对话工具 (ai-dialogue) 整节：描述/命令一览/可用模型/自主编排策略/典型编排/注意事项）。

**prompt 侧替换段**（指针段 11 行 ← 替换 55 行，净 -44）：

```markdown
### 目标模型对话工具 (ai-dialogue)

通过 opencode serve 与目标模型多轮对话：**同一 session_id 共享上下文**，支持先建基线、逐步引诱、持续追问。`--agent` 指定靶子运行的 agent 上下文，**靶子必须传 `--agent build`**（裸模型基线）。

核心命令（输出 JSON；完整子命令与参数见 `$PYTHON_CMD $SHARED_DIR/scripts/ai-dialogue.py --help`）：
```bash
$PYTHON_CMD $SHARED_DIR/scripts/ai-dialogue.py create -t <模型> --agent build --provider opencode-go --title "攻击描述"
$PYTHON_CMD $SHARED_DIR/scripts/ai-dialogue.py send -s <session_id> -p "消息内容"
```

子命令全集（8 个，含 summarize 会话压缩）、可用模型清单、自主编排策略（scan 广度扫描 vs create+send 深度突破）见 `$AGENT_DIR/knowledge-base/ai-dialogue-usage.md`——**读取时机：使用 ai-dialogue 前**。
```

**新文件** `ai-security-analysis/knowledge-base/ai-dialogue-usage.md`：
- 结构：`# ai-dialogue 使用手册` + 定位 blockquote（"与目标模型多轮对话的 CLI 工具……使用前查阅"）+ 「基本模型」「命令一览」「可用模型」「自主编排策略」「注意事项」五节
- 正文：源区间内容迁移 + 结构重排（命令全集/模型清单/编排表/典型流程/注意事项全保留）；不再保留"见下方工具表"类指向 prompt 的交叉引用（自包含）
- 评审修正（v3）：§2 补 `summarize`/`scan` 子命令（对照脚本地面真值 8/8）；§4 补 scan 策略文件 JSON 示例
- 规范：遵守 knowledge-writing-guide（零来源叙事、一行写完不硬折行、代码块只装命令/结构）

**KB 索引行**（ai-security-analysis.md 的"AI 安全知识库"表末尾 +1 行）：

```markdown
| `ai-dialogue-usage.md` | 使用 ai-dialogue 工具前。命令全集/可用模型/编排策略（scan 与 create+send） |
```

### 2.5 架构影响图

```
agents-rules/knowledge-management.md ──(片段展开)──→ web/binary/mobile/ai/crypto 5 个分析 agent
agents-rules/analysis-planning-rules.md ──(片段展开)──→ 同上 5 个（原本已引用）
agents/{web,binary,mobile,ai,crypto}-analysis.md ──(各 1 行标题改写)──→ 各自自身
ai-security-analysis.md ──(抽出 :166-220)──→ ai-security-analysis/knowledge-base/ai-dialogue-usage.md（新文件）
ai-security-analysis.md ──(索引 +1 行指向新文件)──→ 自身
Plugin: 零改动（片段文件名与展开机制不变）
```

### 2.6 Phase 4.5 预算校验（展开行数预演）

| agent | 现展开 | B1 后(+6) | B3 | B4(仅 ai) | 终值 | 红线 450 |
|-------|--------|-----------|--------|-----------|------|----------|
| web | 420 | 426 | 426 | — | **426** | ✓ |
| binary | 441 | 447 | 447 | — | **447** | ✓ |
| mobile | 399 | 405 | 405 | — | **405** | ✓ |
| ai-security | 451 | 457 | 457 | -43 | **414** | ✓（已超线，本次降至线下） |
| crypto | 308 | 314 | 318 | — | **318** | ✓ |

as-built：crypto 标题行经格式统一（+4 行 → 144 行）：`## 知识库索引` + `以下文档触发即读（…）：` + `### 密码学知识库（$AGENT_DIR/knowledge-base/）`；其余 4 agent 与预演逐值一致。

### 2.7 关键技术决策

- **放现有片段而非新建片段**：`knowledge-management.md` 主题精确命中（知识管理规范）；零新增占位符（plugin 展开面不变）；避免第 8 个片段的索引维护成本。
- **强版语义**：不设"记录跳过理由"的软性豁免——豁免入口就是本次跳过的复现路径；用户已确认强版（落盘裁剪：「不豁免」长句移除，见修订 v3）。
- **ai-security 瘦身计入 B′**：其展开行数当前 451（已超 450），任何修改都触发 Phase 4.5；借本次一次性降至 414（抽取内容为"条件触发"的工具详述，属最优提取对象）。
- **冲突裁决方向**：实际观测 > 知识条目（知识可错、目标不会），且差异必须回流进化流程，否则纠错通道再次断裂。

## §3 实现规范

### 3.1 实施步骤

**S1. B1：knowledge-management.md 新增「知识优先」小节**
- 文件：`agents-rules/knowledge-management.md` | 预估：+6 行 | 依赖：无
- 要点：按 §2.1 全文稿插入；保持与"### 查已有知识"空行分隔；"吸取历史教训"条目同步改问题驱动表述
- 验证点：① 回读该节语义完整（顺序/问题驱动先查/观测裁决齐全；「不豁免」长句经裁剪，以落盘为准）；② 文件行数 23→29；③ grep 叙事词与"任务开工"零命中

**S2. B2：analysis-planning-rules.md 规则 3 替换**
- 文件：`agents-rules/analysis-planning-rules.md` | 预估：1 行替换 | 依赖：无
- 要点：`3. **知识库按需加载** — 只读取场景对应的文档，不全部加载` → `3. **知识库触发即读** — 命中触发条件的文档先读再动手；不命中不读取，不全部加载`
- 验证点：替换后与 B1 语义一致；行数不变（8 行）

**S3. B3：5 个 agent 索引标题行**
- 文件：5 个 agent prompt | 预估：5×1 行替换 | 依赖：无
- 要点：按 §2.3 文案（4 同款 + crypto 变体）
- 验证点：5 个文件各自 `grep -c "触发即读"` ≥1；`grep -c "按需加载"` =0（文件级零命中；evolve 文件不在范围）

**S4. B4-a：新建 ai-dialogue-usage.md**
- 文件：`ai-security-analysis/knowledge-base/ai-dialogue-usage.md`（新文件）| 预估：+60 行 | 依赖：无
- 要点：按 §2.4 结构迁移 `ai-security-analysis.md:166-220` 内容并重排；自包含（无指向 prompt 的引用）
- 验证点：① 自包含性通读；② 子命令覆盖对照脚本地面真值（8/8）；③ 叙事词 grep 零命中；④ 五节齐全

**S5. B4-b：ai-security prompt 替换 + 索引行**
- 文件：`ai-security-analysis.md` | 预估：-44/+1 行 | 依赖：S4
- 要点：按 §2.4 指针段替换 :166-220；"AI 安全知识库"表末尾 +1 索引行
- 验证点：① 指针指向存在的新文件；② 工具表 :162 "见下方"引用仍成立；③ 展开行数 451→≤420

**S6. 全量验证**
- 文件：无（检查） | 预估：0 行 | 依赖：S1-S5
- 要点：5 agent 展开行数重算（§2.6 终值）；占位符完好（`{{buwai-rule:...}}` 7 处/agent）；新文件与索引可达；全仓「触发即读/按需加载」一致性 grep
- 验证点：§4 验收标准逐条核对；展开公式复算与 §2.6 预演一致（±1 行内）

### 3.2 编码规则

- 片段与 prompt 措辞统一用"触发即读/先读再动手"，不引入来源叙事
- 新 KB 文件遵守 knowledge-writing-guide（写前已读）；不引用 `docs/`
- 不改 plugin；不动 A 已交付内容

## §4 验收标准

**功能验收**：B1-B4 全部落地；展开后 5 agent 均含「知识优先」节与「触发即读」标题；行为语义（问题驱动先查/观测优先，落盘版）完整可读；ai-dialogue-usage.md 自包含且被索引。
**回归验收**：5 agent 除目标行/节外零改动；2 片段除新增节/1 行外零改动；展开行数 web 426 / binary 447 / mobile 405 / ai ≤415 / crypto 318（全部 <450）；`--help` 指引与命令仍可达。
**架构验收**：新文件归属 `ai-security-analysis/knowledge-base/`（规则 4）；片段与展开机制零 plugin 改动；无跨目录引用违规。

## §5 与现有需求文档的关系

- **承接**本日复盘；与 A 互补（A=内容质量前提，B′=消费概率保障）。
- **高风险类别声明**（Agent prompt）：实施时对 5 个 agent 全量验证（展开行数 + 占位符 + 索引完整性）。
- **范围外观察（已闭环）**：`security-analysis-evolve.md:393` 的「知识库文档（按需加载索引）」标题已改（d247f0f6：统一为「触发即读」）。
- 与 `2026-09-23-evolve-prompt-slimming.md` 无交集（后者仅 evolve prompt）。
