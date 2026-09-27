# 2026-09-27 Cookie Jar 技法入库 + 记忆检索策略 + 机制归因命令

> 状态：已实施（Phase 6 审计通过）| 入口：CookieCorp（SunshineCTF 2026）分析复盘 → 用户确认 A+B+C′
> 来源痛点：复盘确认"自身经验+现场实测 ≈95%、知识库 0%、记忆库≈0、分身 0"；决定性技法（cookie jar 溢出 + Priority 驱逐）KB 全仓零覆盖；开工检索（题目名导向）0 有效命中
> 关联：`2026-09-27-knowledge-first-strategy.md`（B 在其「知识优先」之上细化）；`2026-09-27-gopher-ssrf-tooling-and-knowledge.md`（同日并行，无交集）
> 实施进度与 as-built 记录：`progress-2026-09-27-cookie-jar-kb-and-attribution-command.md`
> as-built：bot-patterns +45/−1（116→160）、xss-advanced +2、web-analysis 1 行替换、knowledge-management +2（29→31）、命令 54 行；5 agent 展开 428/449/407/416/320；实现与 §2.1/§2.3 全文稿 diff 为零
> 修订 v2（功能测试）：§3.4 驱逐细化（批量清至低水位约 150 的 150↔180 锯齿——本地 Playwright T1-T4 验证）；命令端到端实测（对 `20260927_160838_e8ba_web-analysis` 产出完整归因报告）；命令增加外部目录权限提示行

## §1 背景与目标

**来源痛点（复盘数据）**：
1. **内容缺口**：`.opencode/web-analysis/knowledge-base/` 48 篇文档对 "cookie jar 溢出 / Priority 驱逐 / 攻击者可写 cookie 时替换 HttpOnly" 零覆盖（全仓 grep 零命中）；决定性技法靠模型原生知识支撑。同类 bot/cookie 注入题将重复从零探索（本次探索路径：属性注入 → 同路径覆盖 → 溢出驱逐）。
2. **触发条件缺口**：`bot-patterns.md` 索引触发条件是源码形态（"分析 Bot server.js 时"）——黑盒 bot 题（无 server.js）不命中，违反 retrospective-methodology §6.4"可观察形态"标准。
3. **检索策略缺口**：开工检索用题目名（0 命中）；事后技法词复测能命中相邻条目但非决定性——内容缺口为主、检索为辅；且写入条目的标题/关键词形态影响跨题召回。
4. **归因工具缺口（用户需求）**：机制贡献归因目前靠人工追问模型，无按需触发的标准化入口。

**用户决策**：A（KB 技法入库）+ B（检索/沉淀策略微调）+ C′（只写一个 opencode 命令，按需主动触发，不做自动挂钩）。

**目标**：① bot-patterns 新增「攻击者可控 Cookie 写入面」技法节（含识别信号、两条替换路线、构造模板、验证/排错）并扩宽索引触发条件；② knowledge-management 片段补"检索词双路 + 写入粒度"两条规则；③ 新建 `/analysis-attribution` 命令供按需归因。

**预期收益（四维度）**：同类 bot cookie 题速度显著（定向验证替代探索试错）、准确度显著（payload 次序与两路线判定防误判）；B 为长期召回质量；C′ 将复盘归因标准化。上下文代价：索引行 1 行替换 + 片段 +2 行。

## §2 技术方案

### 2.1 改动 1（A）：bot-patterns.md 新增 §3.4 + 索引触发条件 + 交叉引用

**插入位置**：`web-analysis/knowledge-base/bot-patterns.md` 在 §3.3 之后、§4 之前新增 `### 3.4`；§4.1 决策树中 httpOnly 行同步微调。全文稿：

````markdown
### 3.4 攻击者可控 Cookie 写入面（cookie 播种 / jar 溢出）

**何时查本节**（满足其一即读）：
- bot 端脚本/预览页出现 `document.cookie = <拼接用户输入>` 的数据流（用户输入被当 cookie 写进浏览器）；
- 提交类功能（配方/配置/表单字段）的值最终成为 bot 浏览器 cookie；
- 服务端 Set-Cookie 出现 `Priority=High/Low`（Chromium 专有属性，涉及 jar 行为）；
- 单次输入可写入 cookie 数量接近或超过浏览器上限（Chromium 180/host）；
- 同一站对同类对象下发的一组 cookie 属性不对称（如 `session` 带 `Priority=High` 而 `role` 不带）——设计意图指纹。

**替换 HttpOnly 的两条路线**：

| 路线 | 前提 | 做法 |
|------|------|------|
| 1 路径 shadowing | 能向 cookie 字符串注入属性（`; path=/x` 未被清洗） | 同名不同 path 的新 cookie 与旧 cookie 并存；请求命中更长 path 时优先发送，服务端取首/末个取决于解析库（Express `cookie` 包取首个）——以目标行为的实际观察为准 |
| 2 jar 溢出驱逐 | 属性注入被清洗（`;`/空格/`=` 被剥离） | 先撑爆 jar 挤掉旧 cookie，再补写同名目标 cookie（见下） |

**Jar 溢出驱逐机制（Chromium）**：
- 每 host 配额 180 条；超过时触发**批量驱逐**——一次清掉最久未用的一批（低水位约 150，之后继续累积，形成 150↔180 锯齿；低水位与批量随版本而异）；
- 驱逐按 Priority 分层（Low → Medium → High），同级按访问时间最久先驱逐；`document.cookie` 写入默认 Medium；
- HttpOnly 不影响驱逐；同名同域同路径的 HttpOnly 不能被 JS 覆盖（非 HTTP API 写入被整体忽略）——所以必须"先驱逐、后补写"；
- 验证方法：Playwright 打开页面执行 `document.cookie = 'role=chief; path=/'` 后读 `context.cookies()`——旧 HttpOnly 值仍在、且未产生新 cookie。

**构造模板（路线 2，目标 cookie 名 `T` 值 `V`）**：

```
写入序列（bot 端逐条执行）：
1..N:  填充 cookie（唯一名 f0..fN-1）
最后 1 条: {T: V}
```

- 填充数使 `现存数 + 写入数 > 上限`（触发驱逐）且目标写入后不被挤出——**目标 cookie 必须放序列末尾**（批量驱逐淘汰最旧项，中间位置会被后续写入或下一轮批量驱逐清掉）；填充数 ≥ 上限 − 现存数 + 1；工程上总写入数常取上限的 1.1~1.7 倍留余量；
- 落地方式随场景：配方/字段数组逐项一条，或循环生成批量字段。

**验证与判断**：
- 成功：目标接口按新角色响应（更高权限内容/flag）；
- 对照组：只写填充（不含目标 cookie）→ 原角色响应——证明差分来自目标 cookie；
- 未生效排查：① 总量未达上限（未触发驱逐）；② 目标写入太早被 LRU 挤出（应放末尾）；③ 服务端角色判定不在 cookie（改查服务端会话）；④ bot 非 Chromium——Firefox 上限 150/域、无 Priority 属性、驱逐策略不同，路线 2 主要针对 Chromium 系（Docker chromium / Puppeteer / Playwright 默认）。

**黑盒复现（无源码时）**：
- 站点若提供"bot 视角预览页"（如 `/review/:id`、`/preview/:id` 形态的路由渲染并执行 bot 端脚本）→ 用自己的会话打开该页，以本地无头浏览器观察 cookie 写入结果与后续请求，避免对线上盲目试发；
- 预览页脚本顺序即 bot 实际执行顺序（播种 → 业务请求），可作为事实基线。

> HttpOnly 的其他旁路（服务端回显、CSRF via XSS）见 `$AGENT_DIR/knowledge-base/xss-advanced.md`「HttpOnly 不是终点」节。
````

**§4.1 决策树行修改**：
- 原：`│   └── httpOnly: true? → XSS 不可读，需要 CSRF 或其他方式`
- 新：`│   └── httpOnly: true? → XSS 不可读：CSRF / 服务端回显；可向 bot 浏览器写 cookie 时走 §3.4（shadowing / jar 溢出驱逐）`

**索引行修改**（`agents/web-analysis.md:181`）：
- 原：| `bot-patterns.md` | 分析 Bot server.js 时。Bot 代码通用结构、单页/双页模式快速分类、安全决策分析（URL 验证、httpOnly、Docker Chromium 特性）、攻击链决策树 |
- 新：| `bot-patterns.md` | Bot 类题目（源码可见或黑盒可观察：自动审核/提交后自动访问/机器人预览页），或需分析 bot 浏览器 cookie/存储可达性时。Bot 代码通用结构、单页/双页模式快速分类、安全决策分析（URL 验证、httpOnly、cookie 播种与 jar 驱逐、Docker Chromium 特性）、攻击链决策树 |

**交叉引用**（`xss-advanced.md`「HttpOnly 不是终点」段后 +1 行）：

```markdown
**攻击者可写 cookie 时**（输入→`document.cookie` 数据流，bot 浏览器场景）：同路径 HttpOnly 无法 JS 覆盖——路径 shadowing 或 Cookie Jar 溢出驱逐后补写（Chromium 180/域，超限批量驱逐至低水位；Priority 分层 + LRU），见 `$AGENT_DIR/knowledge-base/bot-patterns.md` §3.4。
```

### 2.2 改动 2（B）：knowledge-management.md +2 行

**插入 1**（「直接调 MCP 工具查」的 bullet 列表末尾，+1 行）：

```markdown
- **检索词双路**：先按目标/题目特征词查一轮，再用技法/机制词（中英标识符原样，如 `cookie jar overflow`、`HttpOnly 绕过`）查一轮；单路无命中换另一路——题目名不是好的召回键，技法词才能命中跨题同类记录。
```

**插入 2**（「存分析结论」的 bullet 列表末尾，+1 行）：

```markdown
- **写入粒度**：优先技法级结论（可跨题复用）；标题/正文含技法名与英文标识符，题目与赛事情境仅作最小锚点。
```

净增量 **+2 行**（29 → 31 行）；与「知识优先」节为互补关系（该节管"何时查"，本改动管"用什么词查、怎么写便于被查到"）。

### 2.3 改动 3（C′）：新建命令 `commands/analysis-attribution.md`

全文稿（新文件）：

```markdown
---
description: 机制贡献归因 — 分析一次分析任务中「自身经验/知识库/记忆库/无记忆评审分身」的贡献占比；三源取证（任务目录日志 + 记忆库落库状态 + 配置核对）与「没有/错过」判定。按需主动触发。
---

## 角色与目标

对**已完成的一次分析任务**做机制贡献归因：统计四类机制的调用与消费，给出贡献占比、证据等级与改进线索。只审计、不重做分析、不修改任何文件。

方法论唯一权威：`$OPENCODE_ROOT/security-analysis-evolve/knowledge-base/retrospective-methodology.md` §6（取证路径、没有/错过判据、检索复测规则）——先读它再动手；本文只写触发、输入解析与流程骨架，取证细节与判据不一致时以 §6 为准。

## 输入解析（$ARGUMENTS）

| $ARGUMENTS | 行为 |
|------------|------|
| 空 | 当前会话对应任务：`$TASK_DIR` 优先；为空（非 instrumented 会话）取 `~/bw-security-analysis/workspace/` 最新任务目录，报告首行标注来源；分析上下文在当前会话内时，第 4 步自述可用 |
| 任务目录路径 | 直接使用 |
| 产出文档路径（writeup/报告） | 从文档回溯所属任务目录（按路径就近找 workspace 任务目录）；回溯失败 → 降级模式 |
| `self` | 当前会话即分析会话，以会话上下文自述为主 |

$ARGUMENTS

## 取证步骤

1. **客观调用计数**（任务目录 `logs/timeline.log` + `logs/plugin.log`）：
   - 记忆库：`knowledge_search_knowledge` / `knowledge_store_knowledge` / `knowledge_search_in_memory` / memorist 派发次数；
   - 知识库：`read`/`grep` 命中 `knowledge-base` 路径的行为（timeline 的 read 条目不含路径 → 用 bash `detail`、`ledger.md`、`progress.md`、产出文档交叉还原；无法还原时标注"计数不完整"）；
   - 子 agent：task 派发对象（searcher / memorist / fresh-eyes / knowledge-scout）；
   - 其他分析工具调用（环境相关，如 idat）；
   - 配置核对：相关 agent 的 frontmatter、片段挂载、工具权限（解释某机制"没有调用"的工具侧原因）。
2. **落库状态核对（区分"没有/错过"）**：
   - 直读 `~/bw-security-analysis/db/knowledge/knowledge.db`：`answers` 表按关键词/时间查条目、`answer_vectors_rowids` 查向量索引状态；
   - 直读仅用于存储/索引状态审计；**检索质量复测必须走真实检索路径**——派发 memorist 用技法词复测（要求逐字返回 id + question）；无权限/不可用时标注"未复测"并列入遗留。
3. **消费质量归因**：读 `ledger.md`/`progress.md`/产出文档与日志时间线，判断各调用是否真正支撑关键步骤/突破；无法判断的条目标注"需自述"。
4. **自述补充**：当前会话包含分析上下文时，基于会话自述突破归因；不含时标注"自述缺失"，仅给日志侧结论。

## 输出格式

1. **机制贡献表**（四行固定：自身经验 / 知识库 / 记忆库 / 无记忆评审分身）：

| 机制 | 调用计数 | 有效消费项 | 贡献占比（估计） | 证据等级 |
|------|---------|-----------|----------------|---------|

（占比合计 100%；后两者为 0 时同样列出并给零证据）

2. **知识消费明细**（可选）：| 来源（KB 文件/记忆条目 id） | 命中方式 | 是否被消费 | 支撑了哪一步 |
3. **没有 / 错过 清单**：| 项 | 判定 | 依据 | 修复方向 |
4. **结论**：占比 + 置信度 + caveat（回溯归因主观、单样本无法消融）；发现的缺口列候选改进线索（交进化流程评估，不在此实施）。

## 约束

- 只读审计：不修改任何文件、不写知识库/记忆库；
- 不重做分析、不评价分析结论对错（只归因机制贡献）；
- 路径引用保持 `$OPENCODE_ROOT`/`$TASK_DIR`/`~` 形式，禁止硬编码绝对路径；
- 任务目录与知识库 DB 位于项目外（`~/bw-security-analysis/`）——交互会话遇外部目录权限询问时放行只读访问（非交互运行需预授权）；
- 日志缺失时降级：标注"降级模式（无任务目录日志）"，仅用产出物 + 自述归因并降低证据等级。
```

### 2.4 文件改动清单

| # | 文件 | 改动点 | 行数 |
|---|------|--------|------|
| A1 | `web-analysis/knowledge-base/bot-patterns.md` | 新增 `### 3.4` 节；§4.1 决策树 1 行微调 | +45 / 1 行替换 |
| A2 | `agents/web-analysis.md` | 索引表 `bot-patterns.md` 行替换（触发条件可观察化） | 1 行替换 |
| A3 | `web-analysis/knowledge-base/xss-advanced.md` | 「HttpOnly 不是终点」段后 +1 行交叉引用 | +1 行内容（diff 计 +2 含空行） |
| B | `agents-rules/knowledge-management.md` | 「直接调 MCP 工具查」「存分析结论」各 +1 bullet | +2 |
| C′ | `commands/analysis-attribution.md` | 新命令文件 | +55 左右（新文件） |

### 2.5 架构影响图

```
commands/analysis-attribution.md ──只读──→ 任务目录 logs/ + knowledge.db + 产出文档（不写任何文件）
web-analysis/knowledge-base/bot-patterns.md ──§3.4 新增/§4.1 微调──→ 自身
web-analysis/knowledge-base/xss-advanced.md ──+1 行引用──→ bot-patterns.md §3.4
agents/web-analysis.md ──索引行 1 行替换──→ 自身（触发条件可观察化）
agents-rules/knowledge-management.md ──+2 行──(片段展开)──→ web/binary/mobile/ai/crypto 5 个分析 agent
Plugin: 零改动（片段文件名/展开机制不变；命令为 opencode 原生命令目录机制）
```

### 2.6 Phase 4.5 预算校验（展开行数预演）

| agent | 现展开 | B 后(+2) | 红线 450 |
|-------|--------|----------|----------|
| web | 426 | **428** | ✓ |
| binary | 447 | **449** | ✓（贴近红线，见 §5 观察项） |
| mobile | 405 | **407** | ✓ |
| ai-security | 414 | **416** | ✓ |
| crypto | 318 | **320** | ✓ |

A 不增加任何 agent prompt 行数（索引行为 1 行替换；KB 文档按需加载不占常驻上下文）。命令文件不展开进任何 prompt。

### 2.7 关键技术决策

- **技法放 bot-patterns.md**：前置条件"攻击者输入被写入 bot 浏览器 cookie"属 bot 上下文；auth-attacks 无 bot 时该技法不适用，避免两处维护。
- **xss-advanced 只做 1 行交叉引用**：该文件已有「HttpOnly 旁路」小节，是读者找 HttpOnly 绕过的自然落点；正文不重复。
- **触发条件改可观察形态**：源码形态（"分析 Bot server.js 时"）漏黑盒题；改为"源码可见或黑盒可观察"括号列举，同时补 cookie/存储可达性场景。
- **B 只 +2 行**：binary 现展开 447，+2 后 449 仍在红线内；任何更大改动都会触发瘦身，本批次控制粒度。
- **知识零来源叙事**：§3.4 正文不含赛事名/题目名/"实测"等叙事词；技术数据（180/150、Priority、LRU）为可验证事实。
- **命令不设 `agent` frontmatter**：仓库既有命令均无此字段（bw-audit/health-check 另有 buwai-extension-id，本命令为非控制台扩展，不加）；方法论以 `$OPENCODE_ROOT/...` 变量引用，任意会话可读。
- **命令只读**：产出为报告文本；不改文件、不写记忆库——避免"审计动作污染被审计对象"。
- **命令的方法论引用**：命令位于中立目录 `commands/`，以 `$OPENCODE_ROOT/...` 变量指向 evolve KB 的 retrospective-methodology §6 为唯一权威，不复制其内容（命令只做触发/输入解析/流程骨架与操作化路径；先例：knowledge-search 命令的派发 prompt 引用 scout 的 knowledge-sourcing-guide）。

## §3 实现规范

### 3.1 实施步骤

**S1. bot-patterns.md 新增 §3.4 + §4.1 微调**
- 文件：`web-analysis/knowledge-base/bot-patterns.md` | 预估：+45 行 + 1 行替换 | 依赖：无
- 要点：按 §2.1 全文稿插入 §3.3 与 §4 之间；§4.1 httpOnly 行按 §2.1 修改
- 验证点：① 回读 §3.4 自包含（无需其他文件即可执行）；② 叙事词 grep 零命中（`CookieCorp|SunshineCTF|sun\{|实测|本次|复盘`）；③ §4.1 行新文案就位且决策树仍连贯；④ 与 `xss-advanced.md`「HttpOnly」节无重复段落（人工对照）

**S2. web-analysis.md 索引行替换**
- 文件：`agents/web-analysis.md` | 预估：1 行替换 | 依赖：无
- 验证点：① 触发条件为可观察形态（含"黑盒可观察"）；② 替换后行数与占位符（7 处）不变，最终展开行数在 S4 后复算 = 428（S6 复核）

**S3. xss-advanced.md 交叉引用 +1 行**
- 文件：`web-analysis/knowledge-base/xss-advanced.md` | 预估：+1 行 | 依赖：S1（§3.4 需已存在）
- 验证点：① 指向锚点存在（`grep '### 3.4' bot-patterns.md`）；② 单行无硬折行

**S4. knowledge-management.md +2 行**
- 文件：`agents-rules/knowledge-management.md` | 预估：+2 行 | 依赖：无
- 验证点：① 行数 29→31；② 与「知识优先」节语义互补无冲突；③ 5 agent 展开行数复算 = 428/449/407/416/320；④ 两条新 bullet 就位（grep "检索词双路"/"写入粒度"）

**S5. 新建 commands/analysis-attribution.md**
- 文件：`commands/analysis-attribution.md`（新） | 预估：+55 行 | 依赖：无
- 验证点：① frontmatter YAML 可解析（python yaml.load）；② 路径变量齐全（`$OPENCODE_ROOT`/`$TASK_DIR`/`~`），无硬编码绝对路径；③ 与 retrospective-methodology §6 为引用关系（不复制取证细节）；④ 只读约束声明在位

**S6. 全量验证**
- 文件：无（检查） | 依赖：S1-S5
- 要点：5 agent 展开行数复算（§2.6）；占位符计数 7×5；新增/修改文件语法与完整性检查；命令文件命名与 frontmatter 合法性（`commands/*.md`）
- 验证点：§4 验收标准逐条核对通过

### 3.2 编码规则

- KB 正文遵守 knowledge-writing-guide（写前已读）：零来源叙事、一行写完不硬折行、代码块只装命令/结构、具体值代替抽象描述
- 引用一律 `$AGENT_DIR`/`$OPENCODE_ROOT` 变量形式；不引用 `docs/`
- 不改 plugin；不动既有 §1-§3.3 内容（除 §4.1 一行）

## §4 验收标准

**功能验收**：A/B/C′ 全部落地；§3.4 含识别信号、两路线判定、构造模板、验证/排错、黑盒复现五要素且可独立执行；索引触发条件命中黑盒 bot 场景；两条检索/沉淀规则在片段中就位；命令文件可被 opencode 识别（commands/ 下 .md + frontmatter 合法）。

**回归验收**：5 agent 展开行数 428/449/407/416/320（全部 <450）；占位符 7×5 不变；bot-patterns 除新增节与 1 行外零改动；xss-advanced 除 +1 行交叉引用（含 1 空行）外零改动；knowledge-management 除 +2 行外零改动；命令不产生任何 prompt 展开。

**架构验收**：KB 改动归属 `web-analysis/knowledge-base/`；命令归属 `commands/`；片段改动归属 `agents-rules/`；零 plugin 改动；无跨目录反向引用。

## §5 与现有需求文档的关系

- **承接** `2026-09-27-knowledge-first-strategy.md`：B 是其「知识优先」的行为细化（该节管何时查，本改动管关键词策略与写入粒度）。
- **并行无交集** `2026-09-27-gopher-ssrf-tooling-and-knowledge.md`（SSRF/gopher 节 vs 本文 bot cookie 节）。
- **同模式参照** `2026-09-27-jwt-kid-defense-aware-upgrade.md`（复盘→KB 内容增补）。
- C′ 引用既有 `retrospective-methodology.md` §6 为方法论权威，不新增/复制方法论。
- **范围外观察**：① binary-analysis 展开 449 贴近 450 红线——下次任何 +1 行 prompt 改动需先瘦身评估；② 索引触发条件系统性审计（本轮只修 bot-patterns 一行，全量审计另议）。
