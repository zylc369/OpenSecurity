# 进度：2026-09-25 readtwice 复盘落地

> 需求文档：`2026-09-25-readtwice-retro-to-system.md`
> 执行规则：严格按 §3.1 步骤顺序；每步完成即更新本文件

## 步骤清单

- [x] S1 A1 查新触发段（web-analysis.md 阶段 A）
- [x] S2 A2 searcher Web 域源（平台新特性源子节）
- [x] S3 B1 状态要素对照条（probe-first-strategy.md）
- [x] S4 B2 外部断言复测条（evidence-discipline.md）
- [x] S5 C1 新文档 html-parse-differentials.md
- [x] S6 C2 新文档 navigation-and-fetch-metadata.md
- [x] S7 C3 attack-orchestration §2.4
- [x] S8 C4 client-side-attacks bfcache 行校正
- [x] S9 C5 知识库索引登记
- [x] S10 D1 writeup 规范更新
- [x] S11 终检

## 执行记录

- S1：web-analysis.md 阶段 A 加"浏览器机制类目标：开工先做一次平台查新"触发段（含范围约束"以当前目标涉及的机制为限"）；验证：触发条件/动作/产出三要素齐；展开行数复算 <450 ✓
- S2：dynamic-by-agent-searcher-web-analysis.md 新增"### 平台新特性源（查新用）"子节（4 源 + 检索式约定），插入"查询术语约定"之前；验证：格式与现有条目一致、检索式自包含 ✓
- S3：probe-first-strategy.md 原则表新增"状态要素对照"行（窗口/弹窗、中间导航、响应头、同源关系、时序；未覆盖不得外推）；验证：可据此列实验前清单 ✓
- S4：evidence-discipline.md 新增第 3 条（外部断言先本地最小复测）；验证：与现有 2 条格式一致、边界（已知方案处理策略不受影响）已写入需求文档 ✓
- S5：新文档 html-parse-differentials.md（76 行；触发条件/四种机制/条件式 payload/双态检查方法/边界）；验证：零叙事词、无 docs/ 引用、五节齐全、交叉引用 xss-advanced 存在 ✓
- S6：新文档 navigation-and-fetch-metadata.md（88 行；Sec-Fetch 体系/none 条件/判读表/回退重发/BFCache 版本条件/检查方法/边界）；验证：探针引用路径 `$AGENT_DIR/scripts/probe-navigation/README.md` 存在、零叙事词 ✓
- S7：attack-orchestration.md 新增 §2.4 "MessagePort 转交劫持"（信任缺陷 + 三跳攻击模式 + 最小代码 + 审计要点）；验证：与 §2.1-2.3 不重复、衔接结构正确 ✓
- S8：client-side-attacks.md bfcache 行校正为条件限定表述（HTTPS 页面/无 cookie 变更等；HTTP 或条件不满足仍不进）；验证：与 C2 表述一致 ✓
- S9：web-analysis.md 知识库索引登记两行（xss-advanced 行后、client-side-attacks 行后）；验证：路径存在、触发条件为现象形态 ✓
- S10：write-writeup.md 更新（规则 1 改"通俗直讲/禁自造名词/禁拟人化类比"；新增规则 8-12：代码先行/执行顺序/术语统一/真实数据/排版；禁忌表 +4 行）；验证：编号 1-12 连续、与现有条款无冲突 ✓
- S11：终检——两新文档 docs 引用/叙事词 = 0；web-analysis.md 展开约 416 行 < 450；索引目标存在；桌面演练（浏览器机制类开工走查：触发段位于强制阶段 A、动作与产出入台账、searcher 域源经 dynamic-by-agent 展开可达）= PASS

## Phase 6 审计记录

- 第 1 轮：需求项全覆盖核对（A1-D1）；结构核查（searcher wrapper 闭合、attack-orchestration §2.3→2.4→§3 衔接、writeup 编号 1-12 连续）→ 零问题
- 第 2 轮：跨文件一致性（C2/C4 的 no-store 表述一致、索引行 vs 文档触发条件一致、新文档引用路径存在）→ 零问题
- 纯审计轮：零问题 → 通过
- 记录项：① D1 的"类比条款"改动按用户"继续"视为批准已实施（如需保留类比可回退该行）；② 探针未复跑（环境不在手边），C4 采用条件限定表述并保留"以复跑为准"指引

## 用户评审调整（实施后，本文件为 as-built 记录）

- **C2/C4 BFCache 条件精确到版本号**：改为"Chrome 116 起分阶段放量、134/135（2025-03/04）全量"；条件按 Chrome 官方文档补全（HTTPS 页面；cookie/授权状态变更即 evict；未使用 WebSocket/WebTransport/WebRTC；无返回 no-store 的 fetch/XHR；企业策略 `AllowBackForwardCacheForCacheControlNoStorePageEnabled` 可禁用；仅 Chrome）
- **C1 补机制版本号**：声明式 Shadow DOM = Chrome 90 起引入（111/124 逐步完善）；DPU = Chrome 150 起支持（机制小节 + 边界汇总两处）
- **S4 撤销（用户移除）**："外部断言本地复测"条从 evidence-discipline.md 移除（用户认为无需；核实 execution-discipline"认知纪律"已覆盖相近纪律）
- **S3 迁移+精简**：probe-first-strategy.md 的"状态要素对照"行撤销；精简版写入 `agents/web-analysis.md` 试探优先策略节（"浏览器行为实验：先列出真实场景的完整状态要素（窗口/弹窗、中间导航、响应头、同源关系、时序）再设计实验"）；"未覆盖不得外推（注明未覆盖：X）"半句删除（execution-discipline 未测清单机制已覆盖）
- **新增交付（用户要求）**：`docs/分析/web/分析-readtwice.md` 由记忆库整理为题面简报——数据来源：readtwice 任务 flow（flow-7270dc2be6dd410080be7d2852b61361）执行记忆（平台页面捕获、get_desc 输出、redeploy 输出）+ 全局知识条目（5026/5039/5055/5276）+ 归档附件（Attachments/readtwice/）；含题面元数据表/附件清单（15 文件）/目标与关键约束，保留用户原有"提醒"块
- **S1 查新段再迁移（用户评审）**："浏览器机制类目标：开工先做一次平台查新"从阶段 A（信息收集）移至阶段 B（分析规划）开头（规则片段之前）——查新属外部知识收集而非目标信息收集；"是否浏览器机制类"的判定依赖阶段 A 结果，放 B 开头作为方案输入更顺。展开行数复算 416 < 450 ✓
- **顺带修正**：`plugins/lib/session-manager.ts` 的 `resolveFirstSecurityAgentSessionData` 注释失准（旧命名 `domain-sources-*`/`general` 兜底描述 → 更正为现行 `dynamic-by-agent-<片段名>-<agentName>` 命名与"null 时不展开"行为；仅注释，不改行为）
