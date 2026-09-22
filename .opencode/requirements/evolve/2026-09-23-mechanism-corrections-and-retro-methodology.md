# 2026-09-23 机制更正（e.source / Lax 宽限）与复盘方法论（C7）

> 状态：需求文档（Phase 2）| 入口：书籍评审（用户发起）→ 全链路更正排查
> 实施进度见 `progress-2026-09-23-mechanism-corrections.md`

## §1 背景与目标

**来源痛点**：
- 《Web安全书籍》评审发现两类机制描述错误（受控探针在 Chrome 146/148/153 上一致复现）：
  1. **e.source**：被描述为"寄出瞬间定格为旧文档窗口对象/快照；源文档销毁则消息被取消投递"。实际：**投递时源文档已销毁则为 `null`**（消息正常投递，不取消）。
  2. **Lax 宽限**：被描述为"2 分钟内 Lax cookie（含显式声明）也随跨站 POST 发送"。实际：**仅未显式声明 SameSite 的 cookie 享受**；显式 `SameSite=Lax` 不适用。
- 错误传播载体（排查后完整清单）：书籍（评审后已修）→ web-analysis 知识库 3 文件 → 源 writeup 2 份 → 记忆库 knowledge 条目 10 条 → events 图库（历史执行记录，flow 隔离，不修）。

**目标**：
1. 修正 web-analysis 知识库 3 处 + 书籍残留 1 处 + writeup 2 份
2. 记忆库追加 2 条更正沉淀（覆盖 10 条受影响条目中的错误断言）
3. 落地 C7（复盘方法论知识库 + prompt 索引行），收尾 2026-09-20 暂存进化候选清单

**预期收益（四维度）**：准确度显著（消除未来分析与知识复用错误机制的风险）；上下文/轮次/速度无变化（纯内容更正）。

**排查完备性结论**：
- 全仓 grep（`docs/` + `.opencode/`，含变体词"写死/固化为/旧文档窗口/取消投递/宽限/不可绕过"）→ 除本清单外零命中
- 记忆库 knowledge 表全量 SQL 扫描（5283 条记录）→ 受影响知识条目 10 条，全部纳入更正条目正文
- events 图库（Neo4j, flow-983ccf89…）扫描 → 仅历史执行摘要与工具记录；按 flow 隔离，未来任务检索不可达，保留不修

## §2 技术方案

### 2.1 更正基准（机制定义 + 证据）

**机制 A（e.source）**：postMessage 事件对象的 `e.source` 在**投递时**求值——源文档仍存活 → 指向该发送窗口；**源文档已销毁 → `null`**（非"旧窗口对象"、非"取消投递"）。判据：处理函数打印 `e.source === null`；对照实验 = 存活期发送（比较相等）vs pagehide 发送（比较不等且 `srcNull=true`）。
证据（本会话复跑，三版本一致）：
```
[probe] e.source===null: true | e.source===savedBeforeSwitch: false | toString: [object Null]
MSG: closing=true eq=false data={"pagehideMsg":1} → PASSED FILTER
```

**机制 B（Lax 宽限）**：`Lax-allowing-unsafe`（2 分钟宽限）**仅适用未显式声明 SameSite 的 cookie**；显式 `SameSite=Lax` 不享受。对照实验要点：种 cookie 方与发 POST 方必须跨 site；**同 host 不同端口 = 同 site，实验会失真**（历史误判疑源）。
证据（本会话复跑）：
```
Chrome 148/153：cookies = t=explicitLax(sameSite=Lax) | u=unspecified(sameSite=undefined)
跨站 POST 接收端 Cookie 头 = "u=unspecified"（显式 Lax 未发送，未声明者发送）
```

### 2.2 文件改动清单

| # | 文件 | 改动点 | 行数 |
|---|------|--------|------|
| A1 | `.opencode/web-analysis/knowledge-base/race-conditions.md` | §4 机制 3 句（:107/:109/:125）+ 判读加 null 探针 + 对照实验片段加接收端打印 | ±20 |
| A2 | `.opencode/web-analysis/knowledge-base/csrf-clickjacking.md` | §4 第 3 条重写（限定"未显式声明 SameSite"+ 对照验证要点） | ±8 |
| A3 | `.opencode/web-analysis/knowledge-base/web-vulnerabilities.md` | :285 "2 分钟豁免"加限定语 | ±1 |
| B1 | `docs/书籍/Web安全书籍/07-postMessage与窗口引用.md` | :3 一句话"写死"→ null 模型 | ±1 |
| B2 | `docs/书籍/Web安全书籍/12-竞态攻击与时序.md` | :9 类比、:16 定义句（审计期追加） | ±2 |
| C1 | `docs/解题报告/Web/readonce-revenge.md` | :1080/:1082/:1288 机制句改 null 模型 | ±10 |
| C2 | `docs/解题报告/Web/readonce-revenge-老文档.md` | :11/:212-214/:812/:818/:877/:883/:915/:946/:952/:954/:974/:1814 | ±40 |
| D1 | `.opencode/security-analysis-evolve/knowledge-base/retrospective-methodology.md` | 新文件（复盘方法论） | ≤150 |
| D2 | `.opencode/agents/security-analysis-evolve.md` | "知识库文档"索引表 +1 行指针 | +1 |
| E | 记忆库（knowledge.db，经控制台 API） | 追加 4 条更正条目（C-A/C-B 主条目 + 2 条检索调优版；检索按内容 embedding 匹配，调优版含高权重检索词） | ±90 |

**不做**：events 图库（历史执行记录/flow 隔离）；历史需求文档 2026-09-21（过程记录，见 §5）；执行记录类记忆条目（`[bash]/[read]` 日志）。

### 2.3 C7 设计（复盘方法论）

- **产出**：`$AGENT_DIR/knowledge-base/retrospective-methodology.md`，内容骨架：
  1. **三层因果**：表象层（可观察事实）→ 决策层（当时的选择逻辑）→ 结构层（缺失项）；改进候选只从结构层产生
  2. **反事实写法**：每个关键决策点写"如果当时做 X 会怎样"（X 须当时可执行；反复出现的替代路径 = 高价值候选）
  3. **改进项四要素**：少（克制）/ 有主（具体文件+规则）/ 有期限（先于什么） / 要复查（怎么验证、何时闭环）
  4. **反模式**：只列现象不挖结构层；愿景式改进项；懊悔式反事实；结论缺未测清单
- **接入**：evolve prompt 的"知识库文档（优先查找）"索引表加 1 行（触发条件 = 写复盘报告/提炼进化候选时）。主 prompt 增量 ≤2 行（展开已超 600 行，保持渐进式披露）。

### 2.4 记忆库更正方法（决策）

- **事实**：`store_knowledge` 为**纯追加**（MCP 与控制台 API 均无 update/delete；`clean_databases.py` 仅支持全库清空）。
- **受影响条目 10 条**（SQL 全量扫描）：
  - e.source/封锁类 7：5255（旧文档 window 对象/保留旧引用）、5122（取消投递）、5150（取消不发 null）、5155（取消+不可绕过完整证明）、5161（数学上完备封锁）、4917（结论"无法绕过"部分）、5116（窗口身份恒等类结论）
  - Lax 类 3：5240（显式 Lax 宽限生效）、1297（通用绕过条目的宽限表述）、5353（第 5 条引用"152 对显式 Lax 有豁免"）
- **方法（选定）**：追加 4 条更正条目（C-A / C-B 主条目 + 2 条检索调优版），正文含正确机制 + "被取代条目清单"；检索到旧条目时以更正条目为准。（as-built 说明：检索按**内容 embedding** 匹配、接口纯追加——主条目裸存会沉底，故增加镜像问法 + 高权重检索词的调优版，确保更正条目进入 top-5。）
- **否决的方案**：
  - In-place SQL 编辑旧条目：绕过服务不变量（embedding 陈旧、无回滚面、live 库直改风险）
  - 删除旧条目：破坏性，丢失条目内有效信息（如 5255 含完整解法与 flag）
- **验证**：store 后用原问题检索，确认更正条目可检出且内容正确。

## §3 实现规范

### 3.1 实施步骤

**S1. 知识库 race-conditions.md §4 修正**
- 文件：A1 | 预估：±20 行 | 依赖：无
- 要点：:107 "之后不再变化"→"投递时源文档已销毁则为 null"；:109 "还是旧文档窗口"→"为 null"；:125 去"实测"、补 null 判据；判读句加 `e.source === null` 判别；接收端探针打印行
- 验证点：更新后 §4 通读自洽；grep `不再变化|旧文档窗口|实测` 零命中；对照实验片段含 null 探针

**S2. 知识库 csrf-clickjacking.md + web-vulnerabilities.md 修正**
- 文件：A2、A3 | 预估：±10 行 | 依赖：无
- 要点：条目 3 限定"未显式声明 SameSite 的 cookie（默认 Lax）"；显式 Lax 不适用；利用前提=目标 cookie 未显式声明；验证要点（跨 site 对照）写入；web-vulnerabilities :285 加限定语
- 验证点：两文件表述一致；`显式.*Lax.*（带上|发送|生效）` 类误述零命中

**S3. 书籍 07:3 + 12:9/12:16 修正**
- 文件：B1、B2 | 预估：±3 行 | 依赖：无
- 要点：12:9/12:16 两处以审计期追加方式落地（见 progress Phase 6 记录）
- 验证点：与 7.4/12 章 null 模型一致；`写死` 在该句零命中

**S4. 新文档（readonce-revenge.md）机制句修正**
- 文件：C1 | 预估：±10 行 | 依赖：无
- 要点：:1080 "e.source 是旧文档的窗口"→null；:1082 blockquote 机制改 null 模型（投递时求值）；:1288 "旧文档窗口在卸载瞬间投递"→"投递时源文档已销毁、e.source 为 null"
- 验证点：grep `取消|旧文档的窗口` 该文件零命中；三处读通

**S5. 老文档（readonce-revenge-老文档.md）e.source 机制群修正**
- 文件：C2 | 预估：±40 行 | 依赖：无
- 要点：:11 preview、:812（"直接取消投递，连 null 都不给"→机制更正）、:877 取代表、:883、:915、:946、:952/:954 时序图、:974、:1814 总结表；6.2 拆迁类比（:900-907）与 6.3 银行类比（:922）改 null 模型；实验解说段（:1082/:1095）改 null 模型；全文 sweep `寄件地址|旧楼|旧窗口|地址是旧` 逐处核对
- 验证点：grep `取消投递|固化为|写死在信封|旧文档的 window|旧楼` 机制语境零命中（合法语境：:834 COOP"旧窗口复活"句保留）；与 5.3 的 null 描述（:806-808 本就正确）自洽

**S6. 老文档 Lax 宽限群修正**
- 文件：C2 | 预估：±30 行 | 依赖：无
- 要点：:212-214 冷知识块重写（适用范围=未显式声明；设计来源保留；删"Chrome 152 对显式 Lax 生效"与"双重实测"）；:818 重写（显式 Lax 不适用宽限→POST 路径的 cookie 门槛说明；删"服务器日志 admin=true"证据句）
- 验证点：grep `显式.*也生效|Chrome 152 对显式` 零命中；:818 结论（路径死）保持

**S7. C7 复盘方法论文件**
- 文件：D1（新文件） | 预估：≤150 行 | 依赖：无
- 前置：读 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`
- 验证点：自包含（不依赖主 prompt 上下文）；无来源叙事词；含"三层因果/反事实/四要素/反模式"四节；读一遍可独立理解

**S8. evolve prompt 索引行**
- 文件：D2 | 预估：+1 行 | 依赖：S7
- 要点：增量控制在索引表 1 行（该 prompt 展开行数已 >600，Phase 4.5 要求先瘦身——本次以最小索引行落地，**瘦身已立独立需求** `2026-09-23-evolve-prompt-slimming.md`，不在本需求范围）
- 验证点：索引行指向 D1 且触发条件="写复盘报告/提炼进化候选时"；prompt 文件增量 ≤2 行

**S9. 记忆库更正沉淀（C-A / C-B）**
- 目标：knowledge.db（经 `POST http://127.0.0.1:9776/api/knowledge/store`，已确认可达、无鉴权） | 预估：±60 行（JSON） | 依赖：无
- 要点：payload 用 python3 + json.dumps 构造（避免手写中文/换行转义错误）；正文含"被取代条目清单"与"检索到相反表述以本条为准"声明
- C-A 正文：机制 A 定义 + 判据 + 被取代清单（5255/5122/5150/5155/5161/4917/5116）+ 未测清单（pagehide 路径外行为、更早版本）
- C-B 正文：机制 B 定义 + 对照实验要点（跨 site 前提/同端口陷阱）+ 被取代清单（5240/1297/5353）+ 未测清单（Chrome 152 精确版本未复测）
- 验证点：store 返回 stored=true；用两问检索，更正条目命中且正文正确

**S10. 终检与报告**
- 验证点：全仓两错误类变体 grep 零命中（含 `旧窗口|旧地址|旧楼|寄件地址` 机制语境；豁免：历史需求文档、记忆库执行记录条目、非本主题条目）；书籍/知识库/writeup 相关章节抽查通读；输出完成报告（含探针脚本留存位置）

### 3.2 编码规则

- 知识文本遵守 `knowledge-writing-guide.md`（S7 写前必读）；更正条目遵守"结论三件套"（证据等级+已验证范围+未测清单）
- writeup 采用**直接修正**（不留"更正注"，不保留错误原句）
- 知识库文件禁止引用 `docs/`（规则 11）；更正条目正文不外引 writeup 路径

## §4 验收标准

**功能验收**：S1-S10 验证点全部通过；记忆库两问检索命中更正条目。

**回归验收**：
- 书籍 07 章、知识库 race-conditions §4、csrf-clickjacking §4 通读无自相矛盾
- writeup 修正处上下文读通（尤其老文档 ch6 教学类比与时序图一致性）
- 历史需求文档（2026-09-21）保持原样（见 §5）

**架构验收**：D1 位于 `$AGENT_DIR/knowledge-base/`（规则 4）；D2 增量 ≤2 行；无新增跨层依赖；知识库无 docs/ 引用。

## §5 与现有需求文档的关系

- **承接** `2026-09-21-cognitive-intervention-system.md`：其 :108/:137 的 race-conditions §4 首版机制描述（"快照 vs 实时"）是当时过程记录，**不改写历史**；本更正以本文档为正式承接。
- **收尾** 2026-09-20 暂存进化候选清单（`/var/folders/.../opencode/evolve-candidates-readonce-revenge.md`）：C1-C5 已落地，本次 C7 为最后一项。
- 书籍（`docs/书籍/`）修复记录在本文档；书籍不在 requirements 索引体系内。
- **债务承接**：S8 向 evolve prompt 新增 1 行触及其 600 行红线；瘦身已立独立需求 `2026-09-23-evolve-prompt-slimming.md`（兑现 `2026-09-22-selfcheck-noise-fixes.md` §5 的"先立瘦身需求"约定）。
