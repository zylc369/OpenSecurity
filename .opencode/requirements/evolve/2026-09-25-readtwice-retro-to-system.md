# 2026-09-25 readtwice 复盘落地：查新 / 实验纪律 / 知识沉淀 / writeup 规范

> 状态：需求文档（Phase 2）| 入口：readtwice 复盘第八章 → 与用户逐条讨论确认
> 实施进度见 `progress-2026-09-25-readtwice-retro-to-system.md`（执行时创建）

## §1 背景与目标

**来源**：readtwice 赛后复盘（报告第八章）。8.4 的因果链结论：远程解出需要"检查器绕过 + `none` 导航"两扇门同时打开；两扇门分别被"假确定性的否定结论"与"简化实验外推 / 二手断言采信"关死。8.5 给出五条措施。

**与用户逐条讨论后的范围决策**：

- 措施 2（否定结论纪律）：**不做**——`agents-rules/execution-discipline.md`"认知纪律（反公理固化）"节已完整覆盖（结论三件套 / 未测清单 / 禁止裸写"不可能" / 卡壳触发）。
- 措施 3（检索双轨制）：**不做**——`skills/stuck-protocol` 步骤 2（换词检索矩阵含"机制"列）与步骤 3（无知证书）已覆盖卡壳场景的机制向检索。
- 保留落地：措施 1（查新）、措施 4（实验状态要素）、措施 5（外部断言复测）；外加两项本会话新确定的沉淀：readtwice 机制知识入库、writeup 规范升级。

**目标**：

1. **查新**：浏览器机制类目标在开工信息收集阶段，先做一次"目标浏览器近 12-18 月平台新特性"检索（触发规则 + 检索源）。
2. **实验纪律两条**：a) 浏览器行为实验设计前先列全真实场景状态要素，未覆盖不得外推；b) 决定方向取舍的外部断言先做本地最小复测。
3. **知识沉淀**：解析差异类、导航与请求元数据类文档入知识库；跨窗口消息类扩现有文档；校正一处与实测矛盾的表述。
4. **writeup 规范**：把本会话打磨出的硬规则（代码先行 / 注释在代码里 / 执行顺序 / 术语统一 / 真实数据）写入 writeup 命令。

**预期收益（四维度）**：准确度显著（黑天鹅特性从"未知的未知"变为"开工可检索"；实验结论不再从简化场景外推；二手断言不再静默左右方向）；上下文/轮次/速度无运行时开销，知识入库后同类题目可直接复用。

## §2 技术方案

### 2.1 文件改动清单

| # | 文件 | 改动点 | 预估 |
|---|------|--------|------|
| A1 | `.opencode/agents/web-analysis.md`（阶段 A） | 加"浏览器机制类目标开工先做平台查新"触发段 | +3 |
| A2 | `.opencode/agents-rules/dynamic-by-agent-searcher-web-analysis.md` | 新增"平台新特性源（查新用）"子节（源 + 检索式） | +15 |
| B1 | `.opencode/agents-rules/probe-first-strategy.md` | 增"实验状态要素对照"规则条 | +4 |
| B2 | `.opencode/agents-rules/evidence-discipline.md` | 增"外部断言本地复测"规则条 | +1 |
| C1 | `.opencode/web-analysis/knowledge-base/html-parse-differentials.md` | 新文档（解析差异 / 条件式 payload / 检查器绕过模式） | ≤180 |
| C2 | `.opencode/web-analysis/knowledge-base/navigation-and-fetch-metadata.md` | 新文档（Sec-Fetch 取值与 `none` 条件 / 回退重发条件 / BFCache 与 no-store / 探针引用） | ≤180 |
| C3 | `.opencode/web-analysis/knowledge-base/attack-orchestration.md` | §2 增 "2.4 MessagePort 转交劫持" | +30 |
| C4 | `.opencode/web-analysis/knowledge-base/client-side-attacks.md` | bfcache 行校正（no-store 条件限定） | ±2 |
| C5 | `.opencode/agents/web-analysis.md`（知识库索引） | 登记 C1/C2 两个新文档 | +2 |
| D1 | `.opencode/commands/write-writeup.md` | 写作风格规则 + 禁忌表更新 | ±25 |

### 2.2 关键设计

**A. 查新**

- **触发条件（"浏览器机制类"的判定）**：分析对象涉及浏览器解析、CSP、导航与请求元数据（Sec-Fetch 等）、缓存与历史、窗口/跨源通信、Bot 行为，或出现"同一份输入被两种环境读取、结果不同"类现象。
- **触发点为什么在 web-analysis 侧**：searcher 是被委派的、无阶段感知；"开工"这一时刻只有分析 agent 知道。查新结果写入台账并作为阶段 B 规划输入。
- **检索源为什么放在 searcher 的 Web 域文件**：域源按派发方动态注入（插件将 `{{buwai-rule:dynamic-by-agent_searcher}}` 展开为 `dynamic-by-agent-searcher-<派发agent>.md`）。浏览器平台源属于 Web 域能力；不放 `searcher.md` 本体（避免跨域污染）。
- **A1 拟稿**（阶段 A 末尾新增）：

  > **浏览器机制类目标：开工先做一次平台查新。** 委派 searcher 检索目标浏览器近 12-18 个月的平台新特性（检索源与检索式见 searcher 的 Web 域源），重点覆盖：解析行为、导航与请求元数据、缓存/历史、跨源通信的新增或变更；范围以当前目标涉及的机制为限（不做全平台泛读）。查新结果写入台账，作为阶段 B 规划的输入。

- **A2 拟稿**（新增独立子节"### 平台新特性源（查新用）"，不扰动现有攻击向源列表的编号与顺序；子节内容）：

  - Chrome 开发者博客 `https://developer.chrome.com/blog/`（平台新特性、弃用公告）
  - Chrome Status `https://chromestatus.com/`（特性状态与发布版本）
  - MDN `https://developer.mozilla.org/`（HTML/JS/Web API 行为与兼容性）
  - WHATWG HTML 规范 `https://html.spec.whatwg.org/`（解析/导航行为的规范源）
  - 检索式约定：`chrome <版本> new features`、`chromestatus <关键词>`、`<行为关键词> site:developer.chrome.com`、`<机制关键词> MDN`

**B. 实验纪律两条**

- **B1 拟稿**（probe-first 原则表新增一行）：

  | **状态要素对照** | 设计浏览器行为实验前，先列出真实场景的全部状态要素（窗口/弹窗、中间导航、响应头、同源关系、时序），逐项标注实验覆盖情况；未覆盖的要素不得外推（结论中注明"未覆盖：X"） |
  |------|------|

- **B2 拟稿**（evidence-discipline 新增第 3 条）：

  > - 将决定方向取舍的外部断言（他方产品行为转述、他人结论），先做最小本地复测再采信；未复测的外部断言不得作为方向取舍依据

  - 边界：不改变 execution-discipline"已知方案处理策略"（执行已验证路径时按其规则）；本规则只约束"用外部断言排除方向"的场景。

**C. 知识沉淀**

- **C1 `html-parse-differentials.md` 骨架**（≤180 行，遵守知识编写规范：零来源叙事）：

  1. 触发条件：目标存在"同一份输入被两种环境读取"（DOM 检查 vs 真实渲染；JS 开/关；检查器/审核器）
  2. 机制清单：`<noscript>` 双态解析；声明式 Shadow DOM（`shadowrootmode`）对 DOM 查询的影响；DPU（`<?marker>` + `<template for>`）的迟到搬移；meta CSP 的生效时刻
  3. payload 模式：条件式 payload（检查态无害 / 渲染态执行）的构造原则
  4. 检查方法：双态对比（关 JS 读 DOM vs 开 JS 看行为）与判据
  5. 边界：浏览器版本差异；与 `xss-advanced.md` 的 noscript 条交叉引用

- **C2 `navigation-and-fetch-metadata.md` 骨架**（≤180 行）：

  1. `Sec-Fetch-*` 系列概览与取值表（含 `none` 的语义）
  2. `none` 的产生条件：浏览器发起（地址栏/书签/外部程序/回退前进/goto）；重定向继承；脚本类导航为什么拿不到 `none`
  3. 回退/前进重新发请求的条件：BFCache 排除条件、`Cache-Control: no-store` 与版本/HTTPS 限定、状态要素组合
  4. 判读表：各导航方式的 `Sec-Fetch-Site` 实测值（引用 `$AGENT_DIR/scripts/probe-navigation/README.md` 基线）
  5. 边界与未测清单

- **C3 `attack-orchestration.md` §2.4 "MessagePort 转交劫持"**（+30 行）：MessageChannel 双端与 `postMessage` 第三参数的转移语义；端口可跨窗口/跨源转交；**端口消息不携带可验证发送者**；"等就绪信号"类审批流程的信任缺陷；把端口转交给攻击者页面的模式；检测要点。

- **C4 `client-side-attacks.md` 校正**：

  - 现状："Chrome 默认开 bfcache；2025/09 起连 `Cache-Control:no-store` 也开 bfcache"
  - 校正为带条件表述："Chrome 2025 起在满足条件（HTTPS 页面、无 cookie/授权状态变更等）时 `Cache-Control:no-store` 页面也可进 bfcache；条件不满足或 HTTP 页面仍不进（回退重新发请求）"
  - 依据：探针基线（Chrome 146/148/153）+ Chrome 平台公告；实施时以探针复跑结果为准。

- **C5 索引登记**：按现有表格式在 Web 安全知识库表加两行，拟稿：
  - `html-parse-differentials.md`｜存在"同一份输入被两种环境读取"类现象（DOM 检查 vs 渲染；JS 开/关），或需要构造"检查态无害、渲染态执行"的 payload 时
  - `navigation-and-fetch-metadata.md`｜分析依赖 `Sec-Fetch-*` 判定、历史回退/重发、BFCache 条件、导航类型时

**D. writeup 规范（D1）**

- **写作风格规则新增**：
  1. **代码先行**：每个攻击环节先给完整、真实的代码（注释直接写在代码里），再展开步骤与概念；不写"近似代码"（伪代码须标注）。
  2. **按执行顺序讲**：同一主题归并（一类一起讲）；在事情发生的节点就地讲清，禁止"补充/后记"式事后找补。
  3. **术语统一**：同一对象全文同一称呼；禁止自造名词（用读者能直接懂的说法）。
  4. **真实数据**：出现提交/请求/日志时使用真实运行数据（编号、rid、响应片段）。
  5. **排版**：全文不使用 `——`（用冒号/分号/括号替代）。
- **禁忌表新增**：自造名词；事后找补（"补充说明"式章节）；近似代码（未标注）；同一对象多称呼。
- **待用户确认项**：现有风格规则第 1 条"用类比或通俗语言解释"——本会话确立的偏好是"通俗直讲、禁自造名词"。**拟改为**："用通俗语言直讲；必要背景用最小具体示例；不用自造名词、不用拟人化类比。"（此项在 Phase 3 审计后、实施前向用户确认）

### 2.3 明确不做

- 措施 2/3 重复项（结论纪律、机制检索）——已由 execution-discipline 认知纪律与 stuck-protocol 覆盖；
- 不新增独立 agents-rules 片段（并入现有片段，控制片段数）；
- 不给"不可绕过"类结论做自动阻断（文本纪律已足够）。

## §3 实现规范

### 3.1 实施步骤

- **S1. A1 查新触发段**｜文件：web-analysis.md｜预估：+3 行｜依赖：无
  验证点：读通上下文；明确"触发条件/动作/产出"三要素；展开行数复算 <450。
- **S2. A2 searcher Web 域源扩展**｜文件：dynamic-by-agent-searcher-web-analysis.md｜预估：+15 行｜依赖：无
  验证点：源列表格式与现有条目一致；检索式自包含、无需额外上下文即可执行。
- **S3. B1 状态要素对照条**｜文件：probe-first-strategy.md｜预估：+4 行｜依赖：无
  验证点：规则可执行（照它能列出一份实验前清单）。
- **S4. B2 外部断言复测条**｜文件：evidence-discipline.md｜预估：+1 行｜依赖：无
  验证点：与现有 2 条格式一致、语义不重叠。
- **S5. C1 新文档**｜文件：html-parse-differentials.md（新）｜预估：≤180 行｜依赖：无（写前必读 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`）
  验证点：自包含（不依赖主 prompt 上下文可理解）；零来源叙事；交叉引用路径正确；章节骨架五节齐全。
- **S6. C2 新文档**｜文件：navigation-and-fetch-metadata.md（新）｜预估：≤180 行｜依赖：无
  验证点：同上；引用 `$AGENT_DIR/scripts/probe-navigation/README.md` 的路径存在且描述一致。
- **S7. C3 扩 attack-orchestration §2.4**｜文件：attack-orchestration.md｜预估：+30 行｜依赖：无
  验证点：与 §2.1-2.3 不重复；代码示例最小可执行；无来源叙事。
- **S8. C4 bfcache 行校正**｜文件：client-side-attacks.md｜预估：±2 行｜依赖：无
  验证点：校正后表述与探针基线不矛盾；上下文自洽。
- **S9. C5 索引登记**｜文件：web-analysis.md｜预估：+2 行｜依赖：S5、S6
  验证点：两行路径/触发条件正确；与表内其他行风格一致。
- **S10. D1 writeup 规范更新**｜文件：write-writeup.md｜预估：±25 行｜依赖：待确认项（§2.2-D）需用户裁决
  验证点：新规则与现有条款无冲突；禁忌表去重。
- **S11. 终检**｜依赖：S1-S10
  验证点：全库 grep（新文档无 `docs/` 引用、零来源叙事词）；web-analysis.md 展开行数复算；索引一致性；输出完成报告。

### 3.2 编码规则

- 知识文档遵守 `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`；知识零来源叙事（铁律）。
- 规则片段改动只并入现有文件；单文件增量 ≤30 行。
- 新知识文档禁止引用 `docs/`；脚本引用用 `$AGENT_DIR` 相对表述。

## §4 验收标准

**功能验收**：S1-S11 验证点全部通过；桌面演练：以"浏览器机制类题目开工"为场景人工走查 web-analysis prompt，确认查新触发段可被识别与执行（留走查记录）。

**回归验收**：web-analysis.md 展开行数 <450；searcher Web 域文件结构与现有段落一致；attack-orchestration §2 前后自洽；C4 校正与 probe-navigation 基线一致。

**架构验收**：文件位置符合进化规则 4（prompt→`agents/`、规则→`agents-rules/`、知识→`web-analysis/knowledge-base/`、命令→`commands/`）；无 `docs/` 引用；无新增跨层依赖。

## §5 与现有需求文档的关系

- **承接** `2026-09-21-cognitive-intervention-system.md`：本次补充其未覆盖的"开工查新 / 实验状态要素 / 外部断言复测"，不重复其结论纪律与卡壳协议机制。
- **关联** `2026-09-23-mechanism-corrections-and-retro-methodology.md`：该批产出探针脚本归档与复盘方法论；C2/C4 引用其探针基线，属同类"机制准确性"维护。
- **收尾** readtwice 复盘 8.5 五条措施：1/4/5 落地本批；2/3 去重记录见 §1。
- evolve prompt 无改动（无新增瘦身债务）。
