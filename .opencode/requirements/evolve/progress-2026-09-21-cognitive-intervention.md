# 进度：2026-09-21 认知干预系统（反公理固化）

> 需求文档: `requirements/evolve/2026-09-21-cognitive-intervention-system.md`
> 设计稿: 本会话讨论产物（四关模型：落纸 / 投票 / 外人 / 穿越）

## 状态

- Phase 2 需求文档：完成
- Phase 3 审计：完成（2 轮修复 + 纯审计通过）
- Phase 4 执行计划：完成（S1→S4→S6→S5→S7→S8→S9→S10→S11）
- Phase 4.5 展开行数：web 405 / binary 443 / mobile 402 / **ai 453（450–600 提示带，汇报时给提取建议）** / crypto 280
- Phase 5 实施：S1–S11 全部完成
- Phase 6 审计：Round 1 修复 3 项 + Round 2 修复 1 项（见下）
- 汇报：待用户查看

## 实施明细（步骤 → 文件 → 结果）

| 步骤 | 文件 | 结果 |
|---|---|---|
| S1 | `agents-rules/execution-discipline.md` | +7 行（95）：认知纪律节（结论三件套 / 台账 / 预登记 / 卡壳触发） |
| S2 | `agents-rules/knowledge-management.md` | +2 行（23）：写入三段式 + 历史教训检索 |
| S3 | `binary-analysis/knowledge-base/knowledge-writing-guide.md` | +15 行（174）：§2.5 双键约定 |
| S4 | `web-analysis/knowledge-base/race-conditions.md` | +38 行（140）：§4 消息跨文档切换投递；§5 重排；`web-analysis.md` 索引行 |
| S5 | `skills/stuck-protocol/SKILL.md` | 新建 45 行 |
| S6 | `agents/fresh-eyes.md` | 新建 69 行 |
| S7 | `commands/frame-audit.md` | 新建 43 行 |
| S8 | `plugins/lib/{constants,session-manager,task-session-persistence,checkpoint}.ts` + `security-analysis.ts` | 计数 / 检查点注入 / 台账模板 / 委派清单；含 ROOT_TASK_DIR 注入 bug 修复 |
| S9 | `plugins/security-analysis.ts` + `constants.ts` | 压缩注入第 4 节 + 台账原样穿越（≤200 行） |
| S10 | `mcp-servers/knowledge/server.py` | 普遍结论写入校验（拒绝 + 改写指引） |
| S11 | 本文件 + 展开行数 / 引用闭环核对 | 完成 |

## 验证记录

- `node --check` ×5 通过；`server.py` compile 通过；bun 全模块导入解析通过
- checkpoint harness 9/9 PASS（19/20 次、39/40 分钟、重置、渲染）
- 台账 harness：根目录生成 ✓ 幂等 ✓ 子目录不生成 ✓ coordinator 不生成 ✓
- MCP 校验 8/8 用例 PASS（拒/过边界）
- 引用闭环：stuck-protocol / fresh-eyes / ledger.md 无死引用

## 审计发现（已全修复）

1. MCP 标记过宽（"全部 / 100%" 易误伤）→ 收敛为 6 个封闭词
2. fresh-eyes 输出路径依赖 `$ROOT_TASK_DIR`，而该变量存在注入 bug → 改为"调用方指定路径（默认 $ROOT_TASK_DIR）"
3. 附带修复：`buildEnvSection` 子会话 `$ROOT_TASK_DIR` 误注入子会话自身目录（`getTaskDir()` → `rootTaskDir`）
4. `frame-audit` 缺独立 `$ARGUMENTS` 行（对照 health-check 约定）→ 补齐
5. race-conditions §4 消息目标引用不一致（A/B 组用 parent、模板用 top）→ 统一为 `target` 说明
6. 台账模板与压缩注入未限定五分析 agent（会给 coordinator/evolve 注入空台账噪音）→ 双重 gating（persistence + compacting hook）
7. 设计稿 F 组件"复发升级"条款遗漏（同失败模式二次出现 → 改进项先落地）→ 补入 knowledge-management 与需求文档 §2.7

## 待观察（需重启 opencode 后生效）

- 检查点注入日志（`[INFO] system.transform: 注入认知检查点 #N`）
- 压缩注入中的"分析台账（未经总结的原始记录）"段
- skill 出现在 available_skills；fresh-eyes 出现在可委派清单

## 追加修复（使用侧审计，同日）

- **三子代理 description 重写**（源码核实：description 是唯一路由层，正文对主 agent 不可见）：
  - `fresh-eyes`：补"卡壳时主动委派"触发条件 + "必须传：目标/原始材料/分析台账" + 返回物（二稿：把"拆零件求值时刻/维度表已变未变"等内部黑话改写为可读表述——description 是给人/主 agent 读的路由层）
  - `searcher`：补显式触发（需要外部知识/不熟技术/换词检索）+ "必须传"措辞
  - `memorist`：补触发（开工/卡壳/压缩后/同类案例）+ 委派说明要求 + 返回格式
- **MCP 描述微调**：`search_knowledge` 补"卡壳/不熟悉技术时再次调用"；`search_in_memory` 补"压缩后/回溯时调用；跨任务不可用（跨任务走 memorist）"
- **新增 KB 规则**：`$SHARED_DIR/knowledge-base/opencode-agent-format.md` 增"description 是唯一路由层（写 agent 的硬要求）"节（四要素/触发句式/单行无竖线/适用于 skill 与 MCP 工具）
- evolve agent 知识库索引触发词同步
- 实测依据：store_knowledge 158 次 vs search_knowledge 6 次 / search_in_memory 1 次（2026/7/24–9/21 日志窗口）
- 验证：三份 frontmatter YAML 解析通过（单行/无 `|`）；server.py compile 通过；校验函数 8/8 用例通过
- 生效：重启 opencode

## 追加修复 2（描述/正文学术分工 + 撤销机械标准，同日）

- 「成本最低」机械化标准撤销：改为"信息量优先（结果若不同就能改变当前判断）"——涉及 execution-discipline、checkpoint 注入文本、fresh-eyes、frame-audit、requirements 模板
- fresh-eyes：description 只留【是什么 + 何时调用 + 必传/返回】；正文由"按顺序流水账"改为"卡点形态 → 方法"（校验/比较代码 → 求值时刻表；结论死锁 → 维度表；需要下一步 → 建议实验；分类存疑 → 独立归类）
- frame-audit 派发模板：删除重复的执行流程，只传输入 + 约束
- searcher/memorist description：去掉实现细节（检索源/库名——属正文内容）
- stuck-protocol：description 收敛为"何时加载 + 是什么"；正文"按顺序执行四步"改为"顺序可按情况调整"
- KB（opencode-agent-format）补第 6 条：描述与正文分工约定（description=是什么/何时/如何调用；正文=情况→方案；反例：无条件"挑成本最低"）

## 追加修复 3（描述风格统一 + 清晰度审计，同日）

定式（用户给定）：description 要讲清【作用 + 为什么这么做（避免什么损失）+ 最终目的（拿到什么）】——只罗列机制/内部黑话，调用方读不懂，也无法判断值不值得委派。

- `fresh-eyes`：description 首句改为"对卡壳中的分析做不带任何既有结论的独立重判，这是为了避免既有结论的干扰，目的是找到真正的突破点"（原"图片点"为笔误；"的对"语序理顺）；正文"没有公理负担"改白话"不带任何既有判断"并补目的
- `opencode-agent-format` §description：四要素要求补"为什么 + 最终目的"；第 6 条分工同步；✅ 好例换成新首句
- `stuck-protocol`：description 补目的（打破封闭结论、找回被删维度）；"无知证书"补白话定义、格式三栏加说明；台账路径补子会话写法；"实验清单"统一为"建议实验"
- `frame-audit`：description 补目的并去掉"零公理负担"黑话；"自行调用"改为正确动作（命令只能用户触发；agent 自行委派走 task，对应 stuck-protocol 第 4 步）；术语同步
- `searcher`：description 补"已尝试/已知错误"的用途（避免重复检索同样的查询）
- `memorist`：description 补"避免重复已走过的弯路"；正文新增"按失败教训/改进项查"检索模式（闭环状态由调用方判定）
- `execution-discipline`：认知纪律节补目的行；台账条目补根/子会话两种路径写法
- `knowledge-management`：历史教训条目补动机；"先处理/升级"改写为可执行动作（自行落地，或报告用户走进化流程）
- `race-conditions` §4：修正"只允许自家人发消息"的反向表述（实际语义：比较为 true 的消息被跳过）；对照实验注释与前置条件措辞对齐
- `server.py`：拒绝消息改为从 `_UNIVERSAL_MARKERS` 动态拼接（消除"消息里列的词 ≠ 实际校验的词"漂移）
- 检查点注入第 1 条："最后更新在第几步"→"在什么时候"（台账无步骤编号）；模板列"更新于"→"更新于（时间）"
- 代码注释：去掉需求文档内部编号（"组件 A/D/E"），改为描述性名称
- `shell.env` 补注入 `ROOT_TASK_DIR`（仅子会话）：环境信息段承诺"括号内变量可在 bash 直接引用"，此前仅 prompt 级注入——memorist/fresh-eyes 用 bash 读根任务目录会拿到空值；现子会话 bash 可直接引用

验证：5 份 frontmatter YAML 解析通过；`server.py` compile + 校验函数 5 用例（拒绝消息与词表一致）；`node --check` ×4 通过；grep 残留（图片点/实验清单/组件 x/第几步）清零（仅需求文档保留历史表述）；五个分析 agent 展开行数复算：binary 445 / mobile 404 / web 407 / ai 455（仍在 450–600 提示带）/ crypto 282。

## 偏离与未做记录（同日）

- `fresh-eyes` 未设 `tools` 白名单（需求 §2.5 提及）：核实该字段在 opencode 已标识 deprecated（映射为 permission；未列出的工具不受限，非硬白名单）；仓库内全部 subagent 均无此字段；行为边界由正文"禁止事项"承担
- `fresh-eyes` 不在 `ALL_REGISTERED_AGENTS`：其会话不写时间线与执行记忆（评审产出 = 落盘报告 + task 返回值）；`AGENTS_WITH_DELEGATION_RULES` 只管"可委派清单"可见性，两者职责不同
- 需求文档中"第几步""零公理负担"等旧表述保留为历史记录，以本文件为准

## 追加修复 4（术语完整性审计，同日）

- 补漏（上轮批次被打断遗留）：requirements ×4（唯一记录处 / 观测记录 / 待复核记录 / 候选追加）、progress ×1、KB 示例 ×1、server.py 注释 ×1
- 同类统一：5 个分析 agent 输出纪律行——"事实/推测" → "观测/推测"；"已验证的事实" → "已确认的观测"（×10 行）
- 全仓复扫：`任务台账` 清零；剩余"事实"均为固定搭配（事实标准 / 事实来源）或劝诫用法（不把推断当事实），已分类保留并报备用户
- 存量 KB 两处待定：model-security-analysis-guide"已验证…的事实"、multimodal-jailbreak"实测决策事实"（涉章节改名 + 索引联动，等用户决定）

## 追加修复 5（评审原则修正，同日）

- `fresh-eyes` 处理规则原句"与原始材料核对不一致时，以原始材料为准"撤销：该写法把"核对"写成"裁决"，等于否定评审本身（若某一来源自动赢，评审无意义）
- 新规则：不一致**不裁定谁对**——不一致本身作为发现保留（写进报告），必要时设计能判别两者的实验
- requirements 输入契约同步（"只采信原始材料与台账记录"→"评审只依据原始材料与台账记录独立重判"）
- 顺带扫描其他「为准」用法：frame-audit 输入解析"以其为准"→"以它作为评审目标"（输入选择，非真值裁定）；压缩注入"以其为准"→"直接沿用其记录，不要重写"（保留保真，非真值裁定）；execution-discipline 的"以实际测试结果为准"**保留**（实验仲裁=世界投票，方向正确，与"来源仲裁"是两回事）

## 追加修复 6（存量 KB 术语统一，同日）

- `model-security-analysis-guide.md` §6：「已验证不受攻击模型影响的事实」→「已验证不受攻击模型影响的特征」（去除"事实=已验证结论"式表述）
- `multimodal-jailbreak.md` §3 标题：「实测决策事实」→「决策要点」（"实测"属来源修饰、"事实"属加载式表述，一并去除）；`ai-security-analysis.md` 知识库索引行同步
- 全仓「事实」复扫结论：剩余均为固定搭配（事实标准 / 事实来源）或劝诫用法（不把推断当事实 / 推测不等于事实），无加载式表述

## 追加修复 7（核心约束收口为片段，同日）

- 新建 `agents-rules/evidence-discipline.md`（证据纪律：观测/推测区分 + 禁止编造）；五个分析 agent（web/binary/mobile/ai-security/crypto）的重复两行统一替换为 `{{buwai-rule:evidence-discipline}}`
- 抽取时统一措辞：来源括注 = "（来自原始材料与工具输出）"；"禁止编造结论或目标值（如 flag）"（原表述不一：IDA 数据库 / 工具输出 / 题目给定参数；结论 / flag）
- 展开行数与抽取前完全一致（内容搬移，不增不减）：web 407 / binary 445 / mobile 404 / ai 455 / crypto 282
- 未抽的重复候选（报告，未达"3 次阈值"）：`binary`/`mobile` 的"不能直接操作 IDA GUI"行 ×2；安全红线 web/ai 同文、crypto 变体

## 追加修复 8（术语精确化：未变 → 从未被当过变量，同日）

- 原词"未变"会被误读为"结论未变"；全量替换为"从未被当过变量"：
  - `fresh-eyes`：description、维度表列头（"已变 / 未变"→"是否被当过变量"）、正文三处
  - `frame-audit` ×2、`stuck-protocol` ×1、`checkpoint`（注释 + 检查点注入文本"哪个条件从未被当过变量？"）、`execution-discipline` 台账规则
  - requirements ×3（根因摘要 / 常驻规则 / 检查点模板）
- 保留：`progress` 与 `opencode-agent-format` 中作为"内部黑话坏例"的历史引用（教学用途，指向已删除的旧词）
- 验证：workstream 文件「未变/已变/没变过」清零；checkpoint 语法 + harness 复跑

## 追加修复 9（两个可读性/正确性问题 + $TASK_DIR 全仓审计，同日）

- **可读性**：执行纪律"挑一项'结果若不同就能改变当前判断'的未测条件立刻跑"重写为"挑选标准只有一条：万一它的结果与预期不一样，能不能推翻现在的结论？能，就优先跑（即使预期它会失败）"；checkpoint 注入文本与需求模板同步
- **$ROOT_TASK_DIR 全量可用**：插件改为对**所有会话**注入 `$ROOT_TASK_DIR`（根会话=自身任务目录，等于 `$TASK_DIR`；子会话=根任务目录）——此前只注入子会话，这正是台账路径要写一长串解释的原因；随后台账引用统一简化为 `$ROOT_TASK_DIR/ledger.md`（execution-discipline / checkpoint / compacting / frame-audit / skill / requirements）
- **$TASK_DIR → $ROOT_TASK_DIR 全仓审计**（任务级产物统一落根任务目录）：
  - 策略层：execution-discipline 文件放置规则（表行+4 条）、binary/mobile/coordinator/web agent、frame-audit、gui-interact-pc
  - 内容层：17 个 KB 文件（binary 12 / mobile 4 / web 1）+ 12 个脚本 usage 示例
  - 规则：**任务级共享产物 → `$ROOT_TASK_DIR`；本会话私有草稿 → `$TASK_DIR`**（根会话两者相同=零行为差异；子会话下产物不再落"主分析找不到"的私有目录）
  - 保留未改：plugin KB 中描述"taskDir 存在性判定"的机制文本、历史需求文档
  - 已知边缘：并联同名子 agent 写同名产物文件存在撞名可能（如两个 binary-analysis 同写 result.json），需要时由 coordinator 在派发时加前缀区分

## 追加修复 10（race-conditions §4 去压缩重写，同日）

- 用户反馈：§4 描述被压缩过度、句子不通顺（沿用了 §1-3 速查表格的电报风格）
- 重写范围：§4 全部叙述句——触发场景加"一句话"开篇；机制 4 条改为完整句子（去掉"现场查询/隔着消息队列与任务调度/恒真/封闭结论"等压缩词）；检查方法/判读/利用模板/边界同步理顺
- 技术语义未变（与复盘结论、源码核对一致）；§1-3 为存量速查体，未动

## 追加修复 11（$ROOT_TASK_DIR 审计修复，同日）

- 子代理审查 + 逐条复核确认后修复：
  1. 遗漏补扫：`task-archive.md`（summary.json 写入根任务目录）、`output-format.md`（任务目录行）；4 个分析 agent + memorist 的"任务目录"措辞统一为"根任务目录"
  2. 边界回归修复：非注册根会话（evolve/build/general 等）派发的子会话此前 `ROOT_TASK_DIR` 为空（父链无任务目录）→ `session-manager` 增加回退：`parentSession?.rootTaskDir || taskDir`（子会话自身目录兜底，保证 `$ROOT_TASK_DIR` 始终可用）
  3. compacting 台账读取：`session.getTaskDir()` → `session.rootTaskDir || session.getTaskDir()`（与"台账在根任务目录"的承诺一致）；requirements §2.6 同步
  4. coordinator 分发指引：并联同类型子 Agent（或多子任务）时要求子 Agent 中间产物放入 `$ROOT_TASK_DIR/<子任务标识>/` 子目录（或加唯一前缀），防同名覆盖
- 未改（记录）：PowerShell 模板中 `$ROOT_TASK_DIR` 应为 `$env:ROOT_TASK_DIR`（既有写法，HEAD 同款；Windows 场景实际启用时再修）

## 追加修复 12（$ROOT_TASK_DIR 过度替换回退，同日）

- 讨论结论：**默认锚点 = 当前 agent 自己的目录（`$TASK_DIR`）**（根会话下即任务目录，子会话下即自己的子任务目录；子目录本身在 `<root>/subtasks/` 之内，放自己目录不会丢，只是嵌套）；只有**跨角色共享产物**用 `$ROOT_TASK_DIR`
- 回退为 `$TASK_DIR`：17 个 KB 的全部工具模板输出路径 + 12 个脚本 usage 示例 + `binary-analysis`(5)/`mobile-analysis`(7)/`web-analysis`(1) 的工具输出路径 + `文件放置规则`（重写为"中间产物→当前 agent 的 `$TASK_DIR`；跨角色共享→`$ROOT_TASK_DIR`"，表行同步）+ `gui-interact-pc` fallback + 4 个分析 agent 的"记住…任务目录"措辞恢复
- 保留 `$ROOT_TASK_DIR`（跨角色共享）：台账全链（execution-discipline 台账条目 / checkpoint / compacting / frame-audit / skill / fresh-eyes / requirements）、coordinator 报告指引、task-archive、output-format、memorist、插件注入与回退修复
- 插件环境描述同步：TASK_DIR=本会话工作目录（中间产物写这里）；ROOT_TASK_DIR=跨角色共享产物（台账、报告）
- 待定（不阻塞）：coordinator 并联指引去留；子分析会话的台账模板问题

## 追加修复 13（删除 security-coordinator agent，同日）

- 用户决定：该编排 agent 无用，删除。连根拔执行：
  - 删除 `agents/security-coordinator.md`
  - 插件：`constants.ts` 移除 `AGENT_SECURITY_COORDINATOR` 常量 + `SECURITY_AGENTS` 条目 + 注释；`security-analysis.ts` 移除 import + `getCompactionContext` 的"编排状态"分支（含函数签名与调用点去参）
  - evolve prompt 架构树移除该行
  - console：`deps.py` 工具归属组 + `ToolsSection.tsx` 标题映射移除（dist 未重建：映射键不再出现即无害，下次构建自动同步）
  - 仓库文档：README.md / README.en.md（删表格行、改写使用说明；顺带补上缺失的 crypto-analysis 行、"四个领域"修正为"五个"）、PR 模板 checkbox、bug 报告示例
- 上节两个待定项随之作废（coordinator 已删）
- 挂起项（需用户决定）：`auto-analysis/server/opencode.ts` 硬编码 `agent: "security-coordinator"`（删除后会报 Unknown agent）——改指向哪个 agent 或一并废弃 auto-analysis，等用户定
- 遗留报告（未动）：`docs/` 4 处提及（contributing/add-new-agent、项目介绍×2、进化-分析持续性增强），属用户文档，待用户安排

## 追加修复 14（规则去重 + 术语统一 + 若干澄清，同日）

- `execution-discipline`：删除与"文件放置规则"节重复的表格行（细则只保留小节，与"工具输出有效性判定"等仅有小节的形态同构）；"结论三件套"去掉"、不得入库"（入库规则归 knowledge-management）
- `knowledge-management`：写入格式去重——不再重复量词清单与等级枚举，改为"按'结论三件套'填写；缺'未测清单'会被 MCP 校验拒收"
- 术语统一：三段式/适用条件 → **结论三件套 / 已验证范围**（server.py 拒绝文案 + 注释、requirements ×3 同步；顺带修正 requirements 中过期的 MCP 标记清单——与 server.py 实际词表对齐）
- `output-format`："任务目录"行恢复为示例路径（该行是"填实际路径"的模板；根会话即该示例，子会话填自己目录）
- `opencode-agent-format`：明确 Task 注入范围 = `mode` 不为 `primary` 的 agent（含 `all` 与 `subagent`）

## 追加修复 15（ROOT 落点具体化，同日）

- 用户三点质疑（成立）：① 文件放置规则第 4 条残留已删除的 coordinator、"根分析"含糊、且把"评审/记忆怎么读"混进"写"规则；② memorist"根任务目录"未给变量；③ task-archive 的 ROOT 落点逻辑未写明
- `execution-discipline` 第 4 条重写为"文件→路径"对照（不再用"跨角色共享"概念，不重复读取方约定）：
  - 分析台账 → `$ROOT_TASK_DIR/ledger.md`；无记忆评审报告 → `$ROOT_TASK_DIR/fresh-eyes-<时间戳>.md`；任务归档 → `$ROOT_TASK_DIR/summary.json`
- `memorist`：根任务目录补（`$ROOT_TASK_DIR`）
- `task-archive`：写明归档逻辑（任务级产物集中存放便于事后查找）；"命令结束"→"分析任务结束"。考证：该约定来自早期 IDA/GUI 命令式流程（`~/bw-ida-pro-analysis/workspace/<task_id>/summary.json`），**当前无运行时消费方**，保留但落点=任务根目录
- 插件 env 两行描述具体化（去掉"跨角色共享产物"模糊词；ROOT 行列明三类文件）+ L1234 注释同步

## 追加修复 16（删除 task-archive 片段，同日）

- 用户决定：summary.json 归档约定无运行时消费方 → 连根拔删除：
  - `agents-rules/task-archive.md` 删除
  - 5 个分析 agent（web/binary/ai/crypto/mobile）的 `## 任务存档` 小节 + 挂载行删除（原小节两侧的两道 `---` 合并为一道；合并前的双 `---` 由替换产生，自检时发现）
- 引用同步：`execution-discipline` 文件放置规则第 4 条去掉"任务归档"条目；插件 env 行与 L1234 注释去掉"任务归档/归档"
- 说明：本进度文件此前条目（追加修复 15、ROOT 扫遍）中的 task-archive 记录属历史过程留痕，保留

## 追加修复 17（删除插件委派块 + GENERAL_SUB_AGENTS 重构，同日）

- 用户决策：① 删除插件委派块 ② fresh-eyes 加入 GENERAL_SUB_AGENTS（注册进 events/memory + 工具时间线）
- 决策依据：
  - opencode core 已把全部非 primary agent 的 description 每轮注入 Task 工具说明（vendor registry.ts:265-277），插件名单表冗余
  - 委派纪律文本（传全上下文 / 可操作结果 / 拿回继续）已被 knowledge-management 片段 + 各子 agent 自身 description + execution-discipline 覆盖（零知识损失）
  - memorist 冲突（被注入"用 Task 委派"但它无 task 工具且提示词声明不调用其他 agent）随块删除自动消失
- 变更：
  - `constants.ts`：删除 `AGENTS_WITH_DELEGATION_RULES`；`BASIC_GENERAL_AGENTS` 更名 `GENERAL_SUB_AGENTS`（searcher/memorist/fresh-eyes）；数组区新增"成员 × 集合"矩阵 + 各集合消费点注释
  - `session-manager.ts`：`isBasicGeneralAgent()` 更名 `isGeneralSubAgent()`（方法保留，随数组更名）
  - `security-analysis.ts`：删除 `buildDelegationBlock` + `readAgentDescription`（连带 descCache）+ 注入点；清理无用 import（AGENT_FRESH_EYES/AGENTS_WITH_DELEGATION_RULES/statSync/js-yaml）；1587→1474 行
- 验证：插件 bun import OK；常量派生打印（GENERAL_SUB=3；ALL_REGISTERED=8；fresh-eyes 已注册、evolve 未注册）；全仓残留引用清零；两处删除交接区结构读回无痕
- 备注：需求文档 S8"加入 AGENTS_WITH_DELEGATION_RULES"机制已被本决策取代（可见性由 core 自动注入承担），需求文档保留为历史

## 追加修复 18（认知契约收口：单源 + 校验脚本，同日）

- 用户决策：收口"结论台账与未测清单"等认知规则的跨文本重复——收口"必须逐字一致的契约词汇"，保留各文本用途差异
- 指正：session-manager.ts 无该文本；实际承载点为 task-session-persistence.ts（台账模板）↔ security-analysis.ts（压缩 §4），另涉及 checkpoint.ts / server.py / execution-discipline.md
- 发现并修正 4 处既有漂移：
  - D1 否定词表三版本（§4 的 3 词 / md 的 5 词且写"全部" / server 的 6 词）→ 统一为 server 权威 6 词
  - D2 server 拒绝消息"证据"→"证据等级（含取值枚举）"
  - D3 模板列名"等级"→"证据等级"
  - D4 task-session-persistence 注释与模板 blockquote 重复 → 注释收敛
- 实施：
  - 新建 `plugins/lib/cognition.ts`（单一来源：字段口径/节名/台账文件名/否定词表/未测标记）
  - 消费方插值：LEDGER_TEMPLATE、压缩 §4、checkpoint 文案（改 cognition.ts 即全量同步）
  - `getCompactionContext` 导出（便于验证，与 renderCheckpointText 同款先例）
  - 新建 `security-analysis-evolve/scripts/check-cognition-consistency.py`（7 项跨 TS/Python/Markdown 校验；失败退出码 1）
- 验证：校验器 7/7 PASS；负向测试（故意把 md 词表改回"全部"→ 精确报差异 + exit 1 → 恢复）；LEDGER_TEMPLATE/checkpoint/§4 三项渲染物实测；插件 bun import OK；server.py compile + 校验用例 8/8
- 备注：evolve prompt（634 行）受 >600 行瘦身规则约束，未把校验器写入 prompt；运行方式见脚本头与 server.py / cognition.ts 注释

## 追加修复 19（校验器形态修订：bun/TS 直跑，同日）

- 用户反馈：Python 校验脚本形态丑（Python 套 bun -e 子进程 + JSON 往返 + 154 行脚手架）
- 重写：`check-cognition-consistency.py` 删除 → `check-cognition-consistency.ts`（bun 直跑）
  - 直接 import cognition.ts / task-session-persistence.ts / checkpoint.ts / security-analysis.ts——无子进程、无 JSON 往返
  - 保留：4 项镜像点检查（server.py 词表 ×2 + 拒绝消息 + md 词表）+ 3 项渲染冒烟
  - 引用同步：cognition.ts 头注释、server.py 注释
- 验证：该独立脚本形态未经完整验证即被方案 A 取代（见追加修复 20）

## 追加修复 20（校验并入插件启动自检，独立脚本删除，同日）

- 用户决策：方案 A——不单独跑脚本；校验挂在"本来必然发生"的启动路径上
- 变更：
  - `cognition.ts`：新增 `verifyCognitionMirrors()`（server.py 词表 ×2 + 拒绝消息 + md 词表；返回不一致项列表）
  - `security-analysis.ts`：setup 启动自检 `verifyCognitionSelfCheck()`（镜像项 + 渲染冒烟：压缩注入/检查点/台账模板 token）——不一致 → debugLog WARN + TUI toast；不阻塞启动
  - 独立脚本 `check-cognition-consistency.ts` 删除；引用同步（cognition.ts 头注释 / server.py 注释）
- 手动即时验证（无文件）：`bun -e "const m=await import('./plugins/lib/cognition.ts'); console.log(m.verifyCognitionMirrors())"`
- 验证：函数直调返回 []；负向测试 ×2（md 词表漂移 / server.py 未测标记漂移 → 均精确报出 → 恢复后归零）；插件 bun import OK；server.py compile + 校验用例 8/8
- 验证中发现并修复：TS 正则误用 Python 的 `\Z`（JS 不支持）导致拒绝消息区匹配失败——首跑即暴露假阳性（若跳过验证将每次启动弹假警报）→ 改用 `$` 并收紧为"下一个 def（含 async）或文件尾"

## 追加修复 21（cognition.ts 类化收口，同日）

- 用户要求：cognition.ts 常量/函数太散 → 用类包装；充分测试不出意外
- 变更：`CognitionContract` 类（只读字段：triadName / evidenceLevelValues / fields / evidenceLevelSpec / sections / ledgerFilename / universalDenyMarkers / untestedMarkers；方法 verifyMirrors + 私有 pyMarkers / sameList）→ 模块级单例 `cognition`
  - 消费方 3 处同步：task-session-persistence / checkpoint / security-analysis（含启动自检与手动命令注释）
- 验证（重点：渲染产物零变化）：
  - refactor 前后对三个渲染物（LEDGER_TEMPLATE / renderCheckpointText / getCompactionContext）做**字节级 diff → 全部零差异**
  - `cognition.verifyMirrors()` → []；负向测试（md 词表漂移）→ 精确报出 → 恢复归零
  - 插件 bun import OK；旧导出标识符运行时残留清零（仅剩 cognition.ts 内指向 server.py 的 Python 变量名字符串，应保留）

## 追加修复 22（压缩 §4 台账说明措辞精确化，同日）

- 用户审读：原句"（分析台账 $ROOT_TASK_DIR/ledger.md 会被原样注入；…）"——未说清注入的是文件还是内容、给谁（读者=总结器看不到插件内部机制）
- 改为："（分析台账 $ROOT_TASK_DIR/ledger.md 的内容已随本提示一并提供——超 200 行时截断并附全文路径；结论与未测清单照其原文保留，不要改写或精简）"
  - "内容"= 事实（插件 readFileSync 后以文本注入，非文件/附件）
  - 超 200 行截断说明先告知，避免总结器把截断注当废注丢弃
  - "200"用 LEDGER_INJECT_MAX_LINES 插值（常量改动自动同步）
- 验证：临时副本渲染（改写相对导入 + globalThis 暴露内部函数，不动仓库文件）→ 与改前快照 diff 仅该句一行变化；cognition.verifyMirrors() → []；插件 bun import OK
- export 移除（已澄清）：用户有意去掉 `getCompactionContext` 的 export——该函数在生产代码中仅有本模块调用（原导出是为外部渲染验证）；保持现状，验证改走临时副本法（改写相对导入 + globalThis 暴露，不动仓库文件）
- verifyMirrors 分支覆盖补测：`_UNIVERSAL_MARKERS` 不匹配 / 拒绝消息缺字段口径 / 镜像文件读取失败 → 三分支均精确报出单条问题；恢复后 []；顺带 server.py 回归 8/8

## 追加修复 23（台账注入函数化 + 自检本体补测，同日）

- 用户要求：台账注入段封装为"返回内容则由调用方决定是否 push"的函数
- 变更（security-analysis.ts）：
  - 新增 `buildLedgerContextBlock(session): string | null`（五分析 agent + 有任务目录 + 台账非空 → 返回块；>200 行截断附路径；否则 null）
  - compacting hook 内联段替换为 `const ledgerBlock = buildLedgerContextBlock(session); if (ledgerBlock) output.context.push(ledgerBlock);`
  - 顺带修正：台账文件名改用 `cognition.ledgerFilename`（原为字面量 "ledger.md"）
- 测试（临时副本法：相对导入改写为绝对 + globalThis 暴露内部函数 + 模拟 ctx.client，均不动仓库文件）：
  - `buildLedgerContextBlock` 7 组用例全过：逐字匹配 / 截断边界（含 L200、不含 L201、总数与路径）/ 空白台账 / 文件缺失 / 非五分析 agent / 无任务目录 / rootTaskDir 回退
  - `verifyCognitionSelfCheck` 本体 4 场景全过：一致（日志一行、零 toast）/ 镜像漂移（假 OPENCODE_ROOT：WARN + toast 精确报出 md 词表差异）/ 渲染冒烟失败（变异 §4：toast 报"压缩注入渲染缺否定词表"）/ toast 通道经模拟 client 实收验证

## 追加修复 24（台账注入 cap：行数 → token 预算，同日）

- 用户提议：截断按 token（真实开销计价单位）而非行数（行长方差大）
- 变更：
  - `constants.ts`：`LEDGER_INJECT_MAX_LINES = 200` → `LEDGER_INJECT_MAX_TOKENS = 4000`
  - `security-analysis.ts`：新增 `estimateTokens()`（ASCII 4 字 ≈ 1 token；非 ASCII 1 字 ≈ 1 token，保守上估；vendor 的 len/4 对中文低估 4-5 倍，未照抄）；`buildLedgerContextBlock` 改逐行累计 token、只取完整行；病态单行 → 截断首行；日志含 kept/total 行数 + 估算 token；§4 文案改为"超约 4000 token 时截断"
- 验证：15 用例全过（1999-2000-2001 行预算边界 / 长行 token 敏感 / 病态单行 / CRLF / 尾换行 / root 优先不回退 / emoji / 各 null 路径）；§4 渲染实测新文案

## 追加修复 25（认知契约全量边界测试 + token 估算基准，验证记录，同日）

- 测试矩阵（临时副本法，全部通过）：
  - verifyMirrors 7 场景（子进程隔离 OPENCODE_ROOT）：一致 / py 词表顺序调换 / py 整行移除 / md 句移除 / md 缺失 / py 单引号 / 双文件缺失
  - buildLedgerContextBlock 15 用例（见追加修复 24）
  - cognitionCheckpoint 7 用例：工具数触发并记账 / 去重 / 未达阈值 / 时间触发 / 非根 / 非分析 agent / 无目录
  - verifyCognitionSelfCheck 6 场景：一致 / 镜像漂移 / 冒烟失败 / 无 client / toast 抛异常（捕获记日志）/ 聚合 2 项
- `estimateTokens` 基准（tiktoken o200k/cl100k，装于临时目录）：混合台账文本 估算/实际 = 1.10（o200k）/ 0.86（cl100k）；4000 估算 ≈ 3633（o200k）/4633（cl100k）真实 token；emoji 段低估（0.6-0.75）
- `cognitionCheckpoint` review：与重构前内联逻辑逐项等价；建议补 doc comment（已随 26 落地）

## 追加修复 26（认知检查开关 + 检查点格式 + 接口收口 + 台账规范审计，同日）

- 开关（用户要求，默认开）：`ENV_KEY_COGNITION_CHECKPOINT = "COGNITION_CHECKPOINT_ENABLED"`（与 RESUME_ANALYSIS_ENABLED 同规则：未找到/非 0 非 false → 启用；"0"/"false"（忽略大小写）→ 禁用；控制台配置，重启 opencode 生效）
  - 判定置于 `shouldTriggerCheckpoint` 内（开关 → 阈值）：关闭 = 不触发/不记账/不注入；工具调用计数继续（重开后基线正常）
- 检查点格式：标题独立行（`## 认知检查点 序号#N`）+ 运行信息独立行 + 空行 + 列表；块首加 `\n`（vendor `llm.ts:126` 以 `\n` 连接 system 项，与其它注入块一致）；第 3 条统一 `cognition.sections.untested`
- 接口收口（用户批评成立）：`SessionData implements CheckpointTriggerStats, CheckpointRenderData` + `elapsedMinutes` 派生 getter；`cognitionCheckpoint` 改 `renderCheckpointText(session)`；接口注释双向标注（"由 SessionData 实现，字段维护见 session-manager.ts"）
- 台账填写规范审计：结论台账列口径已有（三件套）；"必须沿用模板结构"与「未测条件（维度）」五列填写规则缺失 → 补丁待用户确认
- 测试：套件3 7 用例（新格式断言）/ 套件5 开关关闭 ×2（配置读值替换 "0"/"FALSE" → 不触发不记账）/ 台账 15 / 镜像 7 / 自检 2 回归全过；插件 bun import OK + verifyMirrors []；新渲染物实测
