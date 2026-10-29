# 需求：反思盘点检索前置 + 知识来源登记表

> 状态: ✅ 痛点 1 落地（检索前置 + 纯指针文案）; 痛点 2 整体放弃（用户判定全隔离复测场景不再需要，见 §6）
> 创建: 2026-09-30
> 来源: 2026-09-30 SiteCheck 全隔离复测（progress-2026-09-29-reflection-system.md《实战验证》节暴露的两个改进候选）

## §1 背景与目标

**痛点 1（检索绑定在低频分支）**: 复测中纸条触发 4 次、skill 加载、台账盘点均正常，但本地记忆库检索 0 次。根因不是执行力，是结构: 本地检索写在 SKILL.md §5（"判 D 工具"），而 4 次判定全落在 A/B/C，从未走到判 D 分支。记忆库有同类知识时不查 = 重复试错（做题会话归因估算最高可省 2 小时/次）。

**痛点 2（残留检测的语义盲区）**: 全隔离复测的残留检测靠题名 grep，但零来源叙事规范（knowledge-writing-guide 铁律）要求沉淀知识去题名 → 合规知识必无题名 → grep 必失明。复测中 `web-analysis/knowledge-base/bot-patterns.md`（191 行答案级洞察）靠用户人工发现删除，机制上无保障。

**目标**:
1. 本地检索从"判 D 工具"提升为"盘点第 0 步"——每次反思盘点先用技法词直查一次记忆库，命中即免该方向试错
2. 建立 MD 知识沉淀的来源登记表（外部账本，不破坏零来源规范），配查询/隔离工具，使复测残留检测从"grep 碰运气"变为确定性清单

**预期收益**（四维）: 准确度（避免重复已有知识）、速度（复测准备人工排查 → 一条命令）。

## §2 技术方案

### 2.1 检索前置（痛点 1）

| 文件 | 改动 |
|---|---|
| `.opencode/skills/reflection-protocol/SKILL.md` | §1「方向盘点」开头加"盘点第 0 步"（技法词直查记忆库，命中即免试错）；§5 首句补分工说明（首轮轻查已并入 §1，本节为判 D 深化检索），避免双处重复执行 |
| `.opencode/plugins/lib/reflection.ts` | `renderReflectNudge` 文案加 1 行（盘点第 0 步提示）；`renderReflectionHeartbeat` 步骤 0 加 ③（同义，含"命中即采用，该方向盘点结束"） |

文案措辞原则: 注入文案只放一行提示（触发动作），完整规范仍在 SKILL.md（单一权威）。

### 2.2 来源登记表（痛点 2）

| 文件 | 改动 |
|---|---|
| `<repo>/.opencode/knowledge-source-registry.jsonl` | 新建。JSONL，每行 `{"path": "<仓库根相对路径>", "source": "<来源标识>", "written_at": "YYYY-MM-DD"}`。agent 分析流程不读（无任何索引指向它） |
| `$AGENT_DIR/scripts/source-registry.py` | 新建。子命令: `add <path> <source>`（登记，path+source 去重，path 不存在时告警仍登记）/ `list [source]`（列出，可过滤）/ `quarantine <source>`（输出该来源全部路径，一行一个，供隔离消费）。registry 定位: 优先 `$OPENCODE_ROOT` 环境变量，缺失时按脚本自身位置回退推导（`.opencode/security-analysis-evolve/scripts/` → 上溯 3 级 = `$OPENCODE_ROOT`） |
| `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md` | 加「来源登记」节: 所有写入 MD 知识库的新文件/新章节，完成后必须 add 登记；来源标识命名约定（CTF: `赛事-年-题名`；其他: `YYYY-MM-DD-任务名`）；说明与零来源叙事的配合关系（正文零来源 + 外部账本登记）。**命令引用用 `$OPENCODE_ROOT/security-analysis-evolve/scripts/source-registry.py` 全称**（共享文档读者是各 agent，`$AGENT_DIR` 因人而异不可用） |
| `$AGENT_DIR/knowledge-base/retrospective-methodology.md` | 加「隔离复测残留检测」节: ① quarantine 反查拿确定性清单 → 隔离；② 记忆库/事件库整体剪切（引用本次实践）；③ 兜底: 目标 agent knowledge-base 全量备份；④ 明示题名 grep 只是辅助（合规知识无题名）。脚本引用同上用 `$OPENCODE_ROOT/` 全称 |

位置决策: registry 放 `$OPENCODE_ROOT/` 根（平台级数据文件，类比 `.ai_env`），不放任何 agent 目录——它是跨 agent 沉淀的公共账本；工具脚本放 evolve scripts/（隔离检测是 evolve 复盘职责，符合"独立 Python 工具 → 对应方向 scripts/"）。

回填登记（历史文件补账）: `web-analysis/knowledge-base/bot-patterns.md`、`docs/解题报告/Web/sitecheck.md`、`docs/解题报告/Web/SiteCheck/机制贡献归因.md` ← 均为 `SunshineCTF-2026-SiteCheck`。记忆库条目不登记（记忆库复测时整体剪切）。

### 2.3 架构影响

无新依赖方向。SKILL.md 行为扩展（+4 行，80→84）；reflection.ts 纯文案（机制零改动）；guide/methodology 为文档增节。registry 无 agent 运行时读取方（grep 验证）。

## §3 实现规范

- 编码: source-registry.py 用标准库（json/argparse/pathlib），无第三方依赖；输出稳定可管道
- 文案: 注入文案单行、不引入新术语（"技法词""记忆库"为既有词汇）
- 知识零来源铁律不放宽——registry 是账本不是知识正文

### §3.1 实施步骤

```
1. 新建 source-registry.py
   - 文件: $AGENT_DIR/scripts/source-registry.py（新建目录 scripts/）
   - 预估行数: ~110
   - 验证点: python -c compile 通过；python source-registry.py --help 三子命令可见；
     用临时 registry 实测 add（含去重、不存在路径告警）/list/quarantine 输出正确
   - 依赖: 无

2. 正式 registry 创建 + 历史回填登记
   - 文件: $OPENCODE_ROOT/knowledge-source-registry.jsonl（3 行）
   - 预估行数: 3
   - 验证点: list 显示 3 条；quarantine "SunshineCTF-2026-SiteCheck" 输出 3 个路径且逐一存在
   - 依赖: 步骤 1

3. knowledge-writing-guide.md 加「来源登记」节
   - 文件: $SHARED_DIR/knowledge-base/knowledge-writing-guide.md
   - 预估行数: ~20
   - 验证点: 人工读（自包含 + 命令可复制执行）；不可见字节扫描干净
   - 依赖: 步骤 1（引用脚本路径）

4. retrospective-methodology.md 加「隔离复测残留检测」节
   - 文件: $AGENT_DIR/knowledge-base/retrospective-methodology.md
   - 预估行数: ~16
   - 验证点: 同上；与本需求 §2.2 流程一致
   - 依赖: 步骤 1

5. SKILL.md 检索前置
   - 文件: .opencode/skills/reflection-protocol/SKILL.md
   - 预估行数: +5/-1
   - 验证点: §1 开头有"盘点第 0 步"；§5 有分工说明；总行数 ≤ 86；description 触发条件不变
   - 依赖: 无

6. reflection.ts 双通道文案 + 单测
   - 文件: .opencode/plugins/lib/reflection.ts；/var/folders/.../opencode/reflection-unit-test.ts（同步）
   - 预估行数: +6/-2
   - 验证点: bun build 通过；单测全绿（含新文案断言）；两处文案 grep "记忆库" 命中
   - 依赖: 步骤 5（措辞一致）

7. 全局回归
   - 验证点: grep 确认 agents/ 全部文件无 registry 引用（agent 不读）；单测全绿复跑；
     SKILL/guide/methodology 三文档人工复读一致无冲突
   - 依赖: 1-6
```

## §4 验收标准

**功能验收**:
- [ ] `python3 $AGENT_DIR/scripts/source-registry.py quarantine SunshineCTF-2026-SiteCheck` 输出 3 个存在路径
- [ ] add 重复登记不产生重复行；不存在路径有告警
- [ ] SKILL.md §1 含盘点第 0 步；纸条与心跳文案均含技法词直查记忆库提示
- [ ] guide 有「来源登记」节且命令可复制执行；methodology 有「隔离复测残留检测」节

**回归验收**:
- [ ] bun build 通过；反思单元测试全绿
- [ ] SKILL.md 展开后 ≤ 86 行；触发条件（description）未变
- [ ] agents/、agents-rules/、plugins/ 中无对 registry 的运行时读取引用

**架构验收**:
- [ ] 无散落文件（registry 在 $OPENCODE_ROOT 根 = 平台数据先例位；工具在 evolve scripts/）
- [ ] 依赖方向无违规；零来源叙事规范未放宽

## §5 与现有需求文档的关系

- `2026-09-29-reflection-system.md` 的后续改进: 同一反思系统，本需求修复其实战验证暴露的两个缺口（检索结构、验证基础设施）
- 与 `2026-09-27-knowledge-first-strategy.md` 的关系: 检索前置强化其"知识优先"在反思节点的落地，无冲突
- 不改动 stuck-protocol 退役结论；不触碰统一注入器机制

## §6 执行中修订（2026-09-30 用户评审后撤换痛点 2 方案）

撤销: source-registry.py + registry.jsonl + guide §6.1（已全部删除，architecture-map 同步回退）。

撤换原因（用户评审意见，三条全部成立）:
1. 记忆库/已有基础设施更准——最终形态是 git: 知识库文件均在 git 管理下，`git log --since <做题前> --name-only` 直接产出残留清单，提交即记录、零登记成本
2. 数据结构缺陷——一行 {path, source} 无法建模多来源文件（一个知识文档可吸收多题洞察），隔离语义错误（会过度隔离）; git 按版本回退天然精确（多来源文件回到做题前版本，不误伤）
3. 复杂而脆弱——登记是软约束（忘了就漏）、JSONL 手写可错、归一逻辑自实现（开发中已出 2 bug）; git 无这些失败面

替代方案曾落地为 git 时间窗流程，随后用户判定全隔离复测场景本身不再需要（效果已验证），§6.3 整节删除——git 时间窗/worktree 快照的实践经验保留在 progress-2026-09-29-reflection-system.md《实战验证》节与隔离区 RESTORE.md，未来若需复测可从那里取。

保留: 痛点 1 的全部改动（SKILL §1 第 0 步 / reflection.ts 双通道文案 / 心跳压缩为指针式 / 单测 30 条）。

## §6 修订 2（2026-09-30，review 对账）

§4 功能验收"纸条与心跳文案均含技法词直查记忆库提示"作废: 用户评审后注入文案定为纯指针式（skill 名 + 时机语义），检索提示唯一承载于 SKILL §1 盘点第 0 步。模型不加载 skill 则提示不触达——已知取舍，接受。
