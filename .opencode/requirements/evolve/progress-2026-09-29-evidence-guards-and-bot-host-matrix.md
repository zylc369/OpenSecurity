# 进度: 证据防线（负面结论复核 / 线索归属验证）+ Bot 宿主形态知识节

> 需求: `2026-09-29-evidence-guards-and-bot-host-matrix.md`（Phase 3 审计通过：2 轮修复 + 纯审计零问题）
> 来源: SiteCheck 复盘 → 用户确认（一期 = 候选 1/2/3/5）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|---|---|---|---|
| 1 | T1+T2 规则增补（execution-discipline / evidence-discipline） | ☑ | 逐字对照通过；断言各 1 次；展开行数复算（5 agent） |
| 2 | T3+T4 SSRF 知识（ssrf-advanced） | ☑ | 逐字对照；禁用词 0；§3.5 交叉引用有效 |
| 3 | T5 Bot 知识节 + 索引行（bot-patterns / web-analysis.md） | ☑ | 逐字对照；禁用词 0；索引触发条件含截图形态 |
| 4 | T6 卡壳检索渠道（stuck-protocol；含第 2 步标题修正） | ☑ | 逐字对照；frontmatter 未动 |
| 5 | 收尾核查 | ☑ | git numstat 核对；不可见字节 0；展开行数复算；进度文件写入 |

## 终验数据（2026-09-29）

- git numstat（v3 修订后）: evidence-discipline +1/-0；execution-discipline +1/-0；web-analysis.md +2/-2；stuck-protocol +2/-2（含标题修正）；bot-patterns +32/-1；ssrf-advanced +10/-1
- 展开行数（改后）: web 431 / ai 418 / binary 451 / mobile 409 / crypto 322
- 禁用叙事词扫描: ssrf-advanced 0；bot-patterns 0
- 不可见字节扫描: 7 文件全 OK

## 遗留（建议）

- binary-analysis 展开 451 行（450-600 建议区）：「工具脚本清单」节（query.py 查询类型 / update.py 操作类型 / GUI 自动化 / 脚本生成 / 网页渲染 / 进程 Patch，约 50 行）与既有 KB（technology-selection / script-generation / gui-automation / web-rendering / process-patch-reference）职责重叠，可评估提取为触发式读取，主 prompt 保留一行指引入口。建议单独立项（Agent prompt 属高风险改动）。
- 候选 4（终解前新落库回检）：**已关闭**（既有 `2026-09-27-knowledge-first-strategy.md`「问题驱动检索 / 触发即读」覆盖同意图；终端时点形态无增量）。候选 6（复盘方法论补注）：可选，待决。
- 观察项（无行动，留档）：任务内新落库条目的「应用/消费」缺口（检索已按问题驱动触发、结果未改变方向 + 跨压缩后细节失存）——首次发生且代价小；若二次出现，按"二次出现升级"规则评估。

## 修订记录

- 2026-09-29（用户复核触发）：T2 及 §7 文案修订（v2）——① 逻辑修正："多问皆否"→"①、②都答'不'"（原表述对问题③不适用）；② 表述平实化（"目标形状"→"目标要拿的结果"；"加量投入"→"增加尝试"）。同步：`agents-rules/evidence-discipline.md`、`ssrf-advanced.md` §7、需求文档 T2/§7/目标行。（前次修订声明未落盘，本次实际执行并复验。）
- 2026-09-29（同日，用户复核第二触发）：T2 单行化（v3）——两条合并为一条（条件-动作依赖；拆行会被读作两条独立规则）。同步：`agents-rules/evidence-discipline.md`、需求文档 T2。
- 2026-09-29（同日，外部评审触发）：T2/§7 口径修订（v4）——② 改肯定式提问（"是否需要这类线索？"），消除否定问句在"答'不'"上的歧义（严格读法下原句可读成"不是不需要"）。同步：`agents-rules/evidence-discipline.md`、`ssrf-advanced.md` §7、需求文档 T2/T4 蓝图。
- 2026-09-29（同日，单源收口触发）：§7 归属验证改"指针 + 场景补充"（规则单源在 `agents-rules/evidence-discipline.md`；止损判据改"止损后去向"）。同步：`ssrf-advanced.md` §7、需求文档 T4 蓝图。
- 2026-09-29（同日，落位校正触发）：T2 归属验证条迁出共享片段（→ `agents/web-analysis.md` 核心原则 #7）；T4 §7 整节撤除（内容全部迁至同处）。同步：`evidence-discipline.md`（回退 2 条）、`ssrf-advanced.md`（§7 删除+头部）、`web-analysis.md`（原则 #7 + 索引行）、需求文档 T2/T4 块。

## 审计补全记录（2026-09-29，用户质询触发）

补做 Phase 6 完整节奏（首轮实施未走完）：

- Round 1：蓝图 vs 落盘逐字 diff（T1-T6 精确命中、T5 逐字一致、索引行 2 处正确）；禁用叙事词 0；旧词残留（非修订记录）0；不可见字节全 OK；numstat 与记录一致；删除行核对 = 恰好 6 处预期替换行（零意外删除）→ 零发现
- Round 2：六项逐字复跑（稳定性）→ 全 True；零发现
- 纯审计轮：零问题 → Phase 3/6 通过（含补审）
