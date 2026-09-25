# 需求: 知识体系职责重构（scout 专职侦察 + evolve 独占进化）

## §1 背景与目标

**来源**: 2026-09-25 知识命令家族设计的多轮讨论收敛。用户最终决策:
1. 专职知识搜索子 agent（hidden，可被调用但零注入）
2. 知识搜索命令薄壳（任何 agent 会话可用的情报检索）
3. 蒸馏与进化能力**只归 security-analysis-evolve**——knowledge-distill 命令删除，其他 agent 不可触发蒸馏
4. knowledge-pipeline 命令不做——"先搜后蒸"是 evolve 内部流程
5. scout 纯侦察（只找+评估+落盘+报告），**不写知识库**; 所有知识库写入经 evolve

**目标**:
- 职责分层: scout = 情报（找），evolve = 进化（写）; 概念唯一大脑（evolve）+ 唯一侦察兵（scout）
- evolve 瘦身借势完成（636 → <450，合并执行挂起需求 `2026-09-23-evolve-prompt-slimming.md`）
- 触发速查: 任何 agent 会话 `/knowledge-search`（检索）; evolve 会话直接对话（蒸馏/先搜后蒸/给定文件/复盘/提案）

## §2 技术方案

### §2.1 最终形态

```
agents/knowledge-scout.md                       # 新建: hidden 子 agent（专职侦察）
knowledge-scout/knowledge-base/
  └── knowledge-sourcing-guide.md               # 迁入 + 改造（gap 判定入、报告格式、洗叙事）
commands/knowledge-search.md                    # 新建: 唯一命令薄壳 → scout
agents/security-analysis-evolve.md              # 大改: 入口 C 重写 + 蒸馏收口 + 瘦身
security-analysis-evolve/knowledge-base/
  └── distillation-methodology.md               # 更新: 对话入口 + 五分支挪入 + 先搜后蒸
删除: commands/knowledge-distill.md、commands/evolve-from-writeups.md
```

### §2.2 各文件设计

**A. agents/knowledge-scout.md**（新建 ~130 行）
- frontmatter: `mode: subagent`、`hidden: true`（依据: agent.ts:40 schema 支持; tool/task.ts:131 派发按 name 解析不过滤 hidden; prompt.ts 全部 `filter(!a.hidden)` 不注入; 内置 compaction/title/summary 同用法）、description 按规范单行; **tools 白名单机制化禁区**——仅开 webfetch/read/bash/glob/grep，不含 edit/write（"不写知识库"从纪律升级为机制保证）; 不含 task/todowrite（侦察是叶子执行者，且 subagent 默认 deny——维持默认）
- 正文: 角色 = 情报侦察（信源扫描→gap 对照→价值评估→素材落盘→侦察报告）; **明确禁区: 不写知识库、不改 agent prompt、不做结构改动**——发现值得沉淀的只列入报告"建议沉淀清单"（每条: 技术+建议落点+价值理由+素材路径），沉淀由 evolve 执行
- 方法论指针: `$AGENT_DIR/knowledge-base/knowledge-sourcing-guide.md`（scout 的 $AGENT_DIR = knowledge-scout/）
- 工具面: webfetch/bash（下载）/glob/grep; 按需声明

**B. sourcing-guide 迁移 + 改造**（~60 行改动）
- `git mv` 至 `knowledge-scout/knowledge-base/`
- 新增 §0 角色定位（侦察非沉淀）+ gap 两维判定节（方向级看目录/技术点级必读内容对照、禁 grep 判覆盖——从 evolve 系统提示下沉的权威定义）+ 侦察报告格式节（扫描范围/跳过清单/建议沉淀清单/素材路径/遗留）
- §3"教训（本次进化中犯的错误）"节: 按规则 8 洗叙事（标题改中性、内容保留规则本体）
- 删除与沉淀相关的指引（若有），writing-guide 引用移除（scout 不沉淀）

**C. commands/knowledge-search.md**（新建 ~45 行）
- 薄壳: 输入解析五分支（空=all/方向/URL/主题/兜底——继承 evolve-from-writeups）→ task 派发 `subagent_type: "knowledge-scout"`（显式指定，不依赖 description 路由）→ 原样呈现侦察报告
- 模板要点: 输入、时间范围（90 天）、方法论唯一权威 sourcing-guide（报告格式按其侦察报告格式节，模板不重复罗列）、**明确"不沉淀，只建议"**

**D. agents/security-analysis-evolve.md 大改**（净改动 ~80 行; 与 S7 瘦身叠加）
- 入口 C 重写: "素材进化"三路径——① 直接蒸馏（对话"蒸馏 <仓库 URL|本地路径>"，输入形态五分支: 仓库 URL/含 /tree 子目录（以子目录为盘点范围）/单篇 blob URL（提示走 /knowledge-search）/本地路径/其他文本（追问素材来源）; 方向限定由自然语言表达（"只做 crypto 部分"），无 --focus 标志——对话场景参数即语言）② 先搜后蒸（对话触发，evolve 派 scout → 素材落盘 → 对产物走六阶段）③ 给定文件（对话丢文件，gap 对照后走完整进化流程沉淀）
- 入口 C 原段落的 gap 判定权威定义删除 → 指针到两份方法论（distillation-methodology 阶段二 / sourcing-guide——后者注明归 scout 侧）
- "需要散篇素材时派 knowledge-scout"指引一句（智能判断在 evolve，执行在 scout）
- 索引表: 删 sourcing-guide 行（归 scout）、distillation-methodology 行触发条件改"对话触发蒸馏/先搜后蒸时"
- 知识库写入独占声明（配合规则 4 归属判定——已是 evolve 职责，无需新增，仅保持）

**E. distillation-methodology.md 更新**（~40 行）
- 头部"命令入口: /knowledge-distill"改"入口: 对 evolve 直接下达蒸馏指令（对话触发）"
- 阶段一前加输入五分支**详解**（每分支行为说明——evolve prompt 只留一行速查版，详解唯一权威在此，避免双份维护）
- 新增先搜后蒸路径说明（阶段零: 需素材时派 scout，产物路径即输入）
- 清除 /knowledge-distill 字样

**F. 删除与清理**
- 删 commands/knowledge-distill.md（57 行）、commands/evolve-from-writeups.md（68 行）
- 引用清理（已盘点 4+1 处）: distillation-methodology.md、agents/security-analysis-evolve.md 索引行、两命令互引行
- 历史文档豁免: requirements/evolve/ 下的需求与 progress 是历史事实记录，不回改

**G. 瘦身执行**（合并执行 `2026-09-23-evolve-prompt-slimming.md` 的 X1-X11 方案）
- 在 D 步重构后的新 prompt 上执行: 提取 architecture-map/evolution-playbook/long-document-editing/opencode-references 四个新 KB 文件 + 合并压缩 X3 + 并入 writing-guide（X7/X9）
- 目标: 展开 <450 行

**H. hidden 知识沉淀**
- `$SHARED_DIR/knowledge-base/opencode-agent-format.md` 新增 hidden 字段说明: 语义（不注入任何 agent 的 task 列表/不出现在切换菜单）、派发不受影响（tool/task.ts 按 name 解析）、适用场景（内部专用 agent）、内置先例

### §2.3 架构合规

- hidden 机制经 vendor 源码三处证据确认（schema/派发/注入过滤），无单向依赖问题（scout 不引用 evolve 文档; evolve 派 scout 是 task 调用非文档引用）
- 归属: scout 的搜索知识归 scout 目录（谁执行谁持有）; 进化知识归 evolve; hidden 知识归共享层（opencode 机制是通用知识）
- 触发面收窄验证: 蒸馏触发从"任何 agent 命令"变为"仅 evolve 对话"

## §3 实现规范

- 遵守知识编写规范（规则 8）: 全部新写内容零来源叙事; 洗净 sourcing-guide"教训"节
- 路径一律 `$AGENT_DIR`/`$SHARED_DIR`/`$OPENCODE_ROOT` 变量形式; **注意 scout 正文中的 `$AGENT_DIR` 指 knowledge-scout/**（各自会话各自解析，天然正确）
- evolve prompt 改动属高风险: 每步后做典型场景走查（复盘/提案/蒸馏对话/先搜后蒸/给定文件五场景）
- 同文件多 Edit 跨消息串行

### §3.1 实施步骤

1. **创建 scout agent**
   - 文件: `agents/knowledge-scout.md`（新建）+ `knowledge-scout/knowledge-base/` 目录
   - 预估行数: ~130
   - 验证点: ① frontmatter 含 `mode: subagent` + `hidden: true` + tools 白名单且格式符合 agent-format 规范 ② 正文含"不写知识库"禁区与报告格式 ③ description 单行无 `|` ④ 读 plugin security-analysis.ts 确认 $AGENT_DIR 按 agent name 通用推导（scout 会话将正确指向 knowledge-scout/），若机制特判白名单则同步适配
   - 依赖: 无

2. **sourcing-guide 迁移改造**
   - 文件: `git mv security-analysis-evolve/knowledge-base/knowledge-sourcing-guide.md → knowledge-scout/knowledge-base/` + 内容改造
   - 预估行数: ~60
   - 验证点: ① 新路径存在、旧路径无残留引用（grep evolve prompt/其他 agent）② gap 判定节在位 ③ 报告格式节在位 ④ "教训"节叙事洗净（词边界正则）⑤ 无沉淀流程残留
   - 依赖: 1（目录在）

3. **knowledge-search 命令**
   - 文件: `commands/knowledge-search.md`（新建）
   - 预估行数: ~45
   - 验证点: ① 五分支输入解析 ② 派发模板显式 `subagent_type: "knowledge-scout"` ③ 模板含"不沉淀只建议" ④ 无 /knowledge-distill / /evolve-from-writeups 引用（它们将删除）
   - 依赖: 1、2

4. **evolve prompt 职责重构**
   - 文件: `agents/security-analysis-evolve.md`（入口 C 重写 + 五分支收口 + 派 scout 指引 + gap 下沉 + 索引表调整 + 旧 sourcing-guide 路径清理）
   - 预估行数: 删 ~50（原入口 C 段落 + gap 定义 + 索引行）增 ~70（三路径 + 五分支速查 + 派 scout 指引），净 +20
   - 验证点: ① 入口 C 三路径齐全 ② 蒸馏五分支在位 ③ 索引表无 sourcing-guide 旧路径 ④ 五场景走查（复盘/提案/蒸馏/先搜后蒸/给定文件）⑤ 展开行数记录（瘦身高潮在步骤 7）
   - 依赖: 1（派 scout 指引需要 scout 存在）

5. **distillation-methodology 更新**
   - 文件: `security-analysis-evolve/knowledge-base/distillation-methodology.md`
   - 预估行数: ~40
   - 验证点: ① 对话入口表述 ② 五分支在位 ③ 先搜后蒸路径在位 ④ `/knowledge-distill` 字样清零
   - 依赖: 4（入口表述一致）

6. **命令删除 + 全仓清理**
   - 文件: 删 `commands/knowledge-distill.md`、`commands/evolve-from-writeups.md`; 清理已盘点的 4+1 处引用
   - 预估行数: ~10（清理）
   - 验证点: ① 两命令文件不存在 ② 全仓 grep 两个命令名零残留（requirements/ 历史文档豁免）③ commands/ 目录剩余命令清单正确
   - 依赖: 3、4、5（引用方先改完）

7. **evolve 瘦身执行**
   - 文件: 按 `2026-09-23-evolve-prompt-slimming.md` X1-X11 方案（4 新 KB 文件 + 主 prompt 压缩 + writing-guide 并入）在步骤 4 重构后的 prompt 上执行
   - 预估行数: 主 prompt 净 -180 以上（分多个子编辑，每个 ≤200）
   - 验证点: ① 展开行数 <450 ② 五场景走查仍通过（重构+瘦身叠加后回归）③ 四新 KB 文件自包含 ④ 瘦身需求文档标记已执行并记录实际行数
   - 依赖: 4

8. **hidden 知识沉淀**
   - 文件: `$SHARED_DIR/knowledge-base/opencode-agent-format.md`
   - 预估行数: ~15
   - 验证点: hidden 字段说明含语义/派发不受影响/适用场景/先例，格式与该文档 frontmatter 表一致
   - 依赖: 无

9. **端到端验证 + 回归 + 归档**
   - 文件: 本需求 progress + 更新瘦身需求 progress
   - 预估行数: 0（验证）
   - 验证点: ① /knowledge-search 五分支走查 ② evolve 五场景走查 ③ 全部产物叙事词终扫零真残留 ④ 蒸馏触发面收窄确认（唯 evolve）⑤ progress 记录全步骤
   - 依赖: 1-8

## §4 验收标准

**功能验收**:
- scout hidden 生效（frontmatter 静态验证 + 重启后人工确认列表无 scout）且可被 knowledge-search 显式派发
- /knowledge-search 任何 agent 会话可用，产出侦察报告（含建议沉淀清单，零知识库写入）
- evolve 对话可触发: 蒸馏（五分支输入）/ 先搜后蒸 / 给定文件; 复盘与提案入口不受影响

**回归验收**:
- 两命令删除后全仓零残留（历史文档豁免）; 互引无断链
- evolve 展开 <450 行; 五场景走查通过
- 叙事词终扫零真残留（词边界 + 人工判定）

**架构验收**:
- 知识库写入权 evolve 独占（scout prompt 有明确禁区 + 模板传达）
- 归属正确（搜索知识→scout; 进化知识→evolve; opencode 机制知识→共享层）; 无 docs/ 运行时依赖; 无依赖方向违规

## §5 与现有需求文档的关系

- `2026-09-23-evolve-prompt-slimming.md`: **合并执行**（步骤 7），执行后其状态更新为已落地
- `2026-09-25-knowledge-distill-command.md`: 其产物（命令+方法论）被本需求部分取代（命令删除、方法论改对话入口）——历史存档不回改，本需求记录取代关系
- `progress-2026-09-25-knowledge-distill-command.md`: 历史记录豁免清理
