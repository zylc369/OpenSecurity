# 需求: knowledge-distill 蒸馏命令 + 整库蒸馏方法论

## §1 背景与目标

**来源**: 2026-09-25 PwnSec-CTF-2026 整库蒸馏任务（22 步，25 gap 落位）的复盘产出。该任务 80% 流程可复用（盘点→精读→gap 判定→验证→写入→回归），但 6 条关键洞察（gap 两维判定、Tier 验证分级、源 writeup 可信度处理、回归检查清单、工程坑、流程编排）未持久化——下次蒸馏需重新摸索。

**目标**:
1. 新命令 `/knowledge-distill`——用户给定 Git 仓库/离线知识库时一步触发完整蒸馏流程
2. 新方法论文档 `distillation-methodology.md`——把本次验证过的六阶段流程 + 坑集固化为唯一权威
3. 与既有 `evolve-from-writeups` 命令划清边界并互引（宽度扫描 vs 深度榨干）

**用户确认的决策**（2026-09-25 对话）:
- 命令名 `knowledge-distill`（非 `evolve-from-repo`，取"蒸馏知识"含义）
- 只写知识库文件，不做记忆库（events/knowledge MCP）联动
- 方法论放 `$AGENT_DIR/knowledge-base/`（与 sourcing-guide 同目录，蒸馏是 evolve 职责）
- 流程最后一环**直接触发**独立复审（task 派发，不询问用户）

**预期收益**（四维度量）:
- 轮次: 用户从描述完整意图 → `/knowledge-distill <URL>` 一步触发
- 速度: 流程设计环节（本次约 3-4 轮）直接按方法论执行，省去
- 准确度: 本次踩坑（grep 假阳性、串行 Edit、章节错位、writeup 证伪）固化为检查项
- 上下文: 命令仅触发时加载，方法论按需读取，零常驻成本

## §2 技术方案

### §2.1 新增文件

**文件 A**: `.opencode/commands/knowledge-distill.md`（~65 行）

薄触发器风格（与 `evolve-from-writeups.md` 一致）:
- frontmatter: `description: 知识蒸馏 — 对整库/离线知识库（Git 仓库、题目集、内部文档）全量精读、gap 判定、验证分级、沉淀到知识库。薄触发器：解析输入后派发给 security-analysis-evolve agent 执行`
- 输入解析表（$ARGUMENTS）:
  | 输入 | 行为 |
  |------|------|
  | Git 仓库 URL（github.com/.../tree、裸仓库链接） | 克隆到临时区（`--depth 1`，LFS 仓库加 `GIT_LFS_SKIP_SMUDGE=1` 先跳过大文件按需取）→ 全量蒸馏 |
  | GitHub 单篇文件 URL（含 `/blob/`） | 提示散篇场景走 `/evolve-from-writeups`，不进入整库流程 |
  | 本地路径 | 直接盘点该目录 → 全量蒸馏 |
  | `--focus <方向>` 附加参数（可位于 URL/路径之前或之后，解析时先剥离再取主参数） | 限定蒸馏该方向（binary/mobile/web/crypto/ai-security/forensics 之一），其余方向只盘点跳过 |
  | 空字符串 | 报错并提示必需参数（与 evolve-from-writeups 的默认 all 不同——整库蒸馏无默认对象） |
  | 其他文本（非 URL 非路径） | 报错提示走 `/evolve-from-writeups`（散篇/主题场景） |
- 派发模板: 引用 `$AGENT_DIR/knowledge-base/distillation-methodology.md` 为唯一权威，传输入与 focus 参数
- 约束: 散篇信源扫描走 `/evolve-from-writeups`（互引）

**文件 B**: `.opencode/security-analysis-evolve/knowledge-base/distillation-methodology.md`（~170 行）

六阶段流程（每阶段含: 目标 / 步骤 / 检查点 / 常见坑）:

1. **素材获取与盘点**
   - 克隆（LFS 处理）/ 路径确认 → 结构识别（目录约定、素材粒度）→ 分类统计 → 计数交叉验证（分项加总 == 总数，逐目录核对防统计口径错漏）→ 归档规划（`docs/资料/writeup-sources/<来源名>/`，Windows 兼容名扫描: 非法字符 `< > : " / \ | ? *`、保留名、尾部空格/点）
   - 坑: 大仓库先 `du -sh` 评估，LFS 大文件按需 smudge

2. **全量精读与 gap 判定**
   - 逐篇精读（不设上限但按方向分批，单批 ≤10 篇防上下文膨胀）→ 每篇列技术点清单 → **gap 两维判定: 方向级看目录有无对应文件; 技术点级必须读已有知识库实际内容对照，禁止只看索引或 grep 关键词判"已覆盖"**
   - 产出: gap 清单（每条标注: 方向/技术点、目标落位文件、预验证级别）

3. **验证分级（Tier 1-4）+ 源 writeup 可信度处理**
   - 铁律: writeup 可能有已证伪内容，关键断言必须读原题源码/原始响应核实
   - Tier 1 源码级核实（默认必做）/ Tier 2 本地仿真 / Tier 3 完整复跑（QEMU/Docker/本地执行）/ Tier 4 多版本探针（浏览器类）
   - 降级策略: 无法动态复跑（外部依赖如 sage、环境不可得）时降级为静态对照（solve 脚本阶段与 writeup 对照），在 progress 记录降级原因
   - 独立验证替代: 全链不通时对**核心断言**做最小验证程序（如最小 C 程序验证系统调用语义）

4. **写入（走完整进化流程 Phase 2-5）**
   - 蒸馏任务同样写需求文档（含 §3.1 分步）+ progress 进度文件到 `$OPENCODE_ROOT/requirements/evolve/`（防上下文压缩丢失）
   - 归属判定（通用/移动端/PC 端/方向专属，不确定放通用层）→ 沉淀前必读 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md` → 新文件 >80 行才建，补章节注意收尾节（决策/注意）之前插入、编号单调 → agent prompt 知识库索引行 → Phase 4.5 瘦身检查（展开 <450 行）
   - 产出可运行探针时: 自包含（自起 server）、失败路径符合契约（输出 JSON + 非零 exit，不挂起）、README 含 npm install 类依赖安装步骤、多版本验证
   - 坑: 同文件多次 Edit 必须跨消息串行（并行必失败）; oldString 失配先 `python repr()` 比对

5. **回归检查清单**（全量扫描，不只扫新增文件）
   - 叙事词词边界正则: `\bCTF\b|\bwriteups?\b|比赛|赛事|实测|亲测|复盘|验证过`（必须 `\b` 词边界——`reactFiber` 子串会假阳性匹配 `ctF`）
   - 章节顺序（编号单调、收尾节在尾）、prompt 索引行在位、交叉引用路径存在（`$AGENT_DIR`/`$SHARED_DIR` 变量形式）、归档文件计数 == 盘点计数、探针 README 判据完整
   - git diff 审查: 删除行逐条确认全是叙事修正，核心内容零删除

6. **独立复审（直接触发，不询问用户）**
   - 自审收敛后（2 轮审计 + 纯审计轮零问题），**立即用 task 工具派发独立复审子任务**（`subagent_type: security-analysis-evolve` 的 fresh 实例，无本会话上下文——独立视角与 fresh-eyes 同理）
   - 复审 prompt 模板（收入方法论文档）: 审查维度 = 章节路由正确性（重号/错章节/编号单调）/ 叙事词残留（改动范围内文件）/ 探针工程质量（失败路径契约、README 自足性）/ 引用路径 / 技术内容抽查; 附改动文件清单与 git diff 范围; 要求按严重度分级输出 findings
   - 收到 findings 后: 全部修复（不设严重度门槛）→ 修复项回归验证 → progress 记录
   - 复审发现的修复完成后不再递归复审（一轮独立复审即收敛，避免无限循环）

### §2.2 修改文件

**文件 C**: `.opencode/commands/evolve-from-writeups.md`
- 输入解析表后加一行互引: 整库/离线知识库（Git 仓库、题目集）走 `/knowledge-distill`

**文件 D**: `.opencode/agents/security-analysis-evolve.md`
- "知识库文档"表加一行: `| $AGENT_DIR/knowledge-base/distillation-methodology.md | 整库蒸馏时（Phase 0 入口 C 的仓库/离线库形态）（/knowledge-distill 命令入口） |`

### §2.3 架构位置

```
commands/knowledge-distill.md                      # 命令层（薄触发器）
security-analysis-evolve/knowledge-base/
  ├── knowledge-sourcing-guide.md                  # 既有: 散篇信源下载（宽度的那半）
  └── distillation-methodology.md                  # 新增: 整库蒸馏流程（深度的那半）
```

- 无代码改动（.ts/.py 零触碰），纯文档 + 命令
- 方法论引用 sourcing-guide（散篇场景）与 writing-guide（规范），三份各自收口不重复

## §3 实现规范

- 改动范围: 2 新增 + 2 修改，全部为 .md
- 遵守知识编写规范（规则 8）: 方法论文档本身零来源叙事（不写"来自 PwnSec 任务"，直接写流程与坑）
- 路径引用一律 `$AGENT_DIR`/`$SHARED_DIR`/`$OPENCODE_ROOT` 变量形式
- 禁止引用 `docs/` 目录（规则 11）——方法论文档中归档目标写 `$OPENCODE_ROOT` 之外的知识库归档约定目录时用相对表述（归档动作本身写入 `docs/资料/writeup-sources/` 是产出原始资料，属例外允许）

### §3.1 实施步骤

1. **写 distillation-methodology.md**
   - 文件: `$AGENT_DIR/knowledge-base/distillation-methodology.md`（新建 ~170 行）
   - 预估行数: ~170
   - 验证点: ① grep 确认零叙事词（词边界正则，对象指称类命中逐条人工判定）② 三个引用路径（sourcing-guide/writing-guide/progress 模式）存在 ③ 六阶段齐全且第 6 阶段含"直接触发"复审模板 ④ 自包含可独立理解
   - 依赖: 无

2. **写 knowledge-distill.md 命令**
   - 文件: `.opencode/commands/knowledge-distill.md`（新建 ~65 行）
   - 预估行数: ~65
   - 验证点: ① frontmatter 格式与 evolve-from-writeups 一致 ② 输入解析表覆盖仓库 URL/单篇 URL/路径/--focus/空/其他文本兜底 六种 ③ 派发模板含输入、focus、方法论路径（$AGENT_DIR 变量形式）、回传报告格式要求 ④ 互引 evolve-from-writeups ⑤ 薄触发器约束（不在命令内做蒸馏）
   - 依赖: 步骤 1（引用其路径）

3. **互引 + agent prompt 索引**
   - 文件: `evolve-from-writeups.md`（+1 行互引）、`agents/security-analysis-evolve.md`（知识库表 +1 行）
   - 预估行数: +2
   - 验证点: ① 互引双向（knowledge-distill ↔ evolve-from-writeups）② agent prompt 索引 +1 行后的展开行数如实记录（存量已超 450/600，属瘦身需求 `2026-09-23-evolve-prompt-slimming.md` 的既有债务，不由本任务解决但必须记录并向用户报告）③ 表格格式对齐
   - 依赖: 步骤 1、2

4. **端到端验证**
   - 文件: 无新改动（验证既有产物）
   - 预估行数: 0
   - 验证点: ① 命令文件能被 opencode 识别（文件在 commands/ 且 frontmatter 合法）② 模拟输入解析四分支逻辑走查 ③ 全部产物零叙事词终扫 ④ progress 记录
   - 依赖: 步骤 1-3

## §4 验收标准

**功能验收**:
- `/knowledge-distill` 命令可被识别，六分支输入解析正确（空参数报错提示、单篇 URL 路由互引、其他文本兜底）
- 派发模板自包含（evolve agent 收到即可执行，无需回看命令文件）
- 方法论六阶段完整，第 6 阶段明确"直接触发独立复审"且含 prompt 模板

**回归验收**:
- `evolve-from-writeups` 原行为不变（仅加互引一行）
- `security-analysis-evolve.md` 仅 +1 索引行（635→636）; 存量超限（>600）为既有债务，由 `2026-09-23-evolve-prompt-slimming.md` 承接，本任务如实记录并向用户报告
- 全部产物零叙事词（词边界正则终扫）

**架构验收**:
- 命令在 `commands/`、方法论在 `$AGENT_DIR/knowledge-base/`
- 无 `docs/` 运行时依赖、无依赖方向违规、与 sourcing-guide/writing-guide 无内容重复

## §5 与现有需求文档的关系

- 来源任务: `2026-09-25-pwnsec-ctf-2026-distillation.md`（本次为其复盘产出，本文档固化其可复用部分）
- 瘦身需求衔接: `2026-09-23-evolve-prompt-slimming.md` 未被触碰，但本任务在 agent prompt 知识库表插入 1 行使其 §2.1 的行号基准整体 +1（其 635 行基准现为 636），瘦身执行时按内容锚点定位而非行号，或先做 +1 校正
