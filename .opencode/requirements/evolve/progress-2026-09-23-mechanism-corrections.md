# 进度：2026-09-23 机制更正（e.source / Lax 宽限）与复盘方法论（C7）

> 需求文档：`2026-09-23-mechanism-corrections-and-retro-methodology.md`
> 执行规则：严格按 §3.1 步骤顺序；每步完成即更新本文件

## 步骤清单

- [x] S1 知识库 race-conditions.md §4 修正
- [x] S2 知识库 csrf-clickjacking.md + web-vulnerabilities.md 修正
- [x] S3 书籍 07:3 修正
- [x] S4 新文档（readonce-revenge.md）机制句修正（3 处）
- [x] S5 老文档 e.source 机制群修正（15 处，sweep 新增 :1434）
- [x] S6 老文档 Lax 宽限群修正（:212/:214/:818）
- [x] S7 C7 复盘方法论文件（新文件）
- [x] S8 evolve prompt 索引行
- [x] S9 记忆库更正沉淀（C-A / C-B，实落 4 条）
- [x] S10 终检与报告

## 执行记录

- S1：race-conditions.md :107/:109/:122/:125 —— 机制改"投递时求值（源文档销毁→null）"+ 接收端 `srcNull` 探针行；验证 `不再变化|旧文档窗口|实测` 零残留 ✓
- S2：csrf-clickjacking.md §4-3 重写（限定"未显式声明 SameSite"+ 跨 site 验证要点）；web-vulnerabilities.md :285 加限定语 ✓
- S3：书籍 07:3 一句话改 null 模型 ✓
- S4：新文档 :1080/:1082/:1288 改 null 模型；验证机制错误词零残留 ✓
- S5：老文档 15 处（:11/:812/:877/:883/:907/:915/:922/:946/:952/:954/:974/:1082/:1095/:1434/:1814）；验证零残留 ✓
- S6：老文档 :212/:214/:818 宽限范围更正（含删"152 对显式 Lax 生效"+ 站判定失真提示）；验证零残留 ✓
- S7：`retrospective-methodology.md` 创建（58 行：三层因果/反事实/四要素/反模式/检查清单/关联）；叙事词零命中 ✓
- S8：evolve prompt 索引表 +1 行（:581）；文件 634 → 635 行 ✓
- S9：落库 4 条——5657（e.source 更正）、5658（Lax 更正）、5659/5660（e.source 检索调优版；5660 含 readonce-revenge 等高权重检索词，目标问句 top-1/2 命中）。落 4 条原因：检索按**内容 embedding** 匹配（`store` 只 embed 正文）且接口纯追加无覆盖；通过镜像问法 + 检索词调优确保更正条目进 top-5。验证：3 组查询更正条目均进 top-2 ✓
- S10：全仓终扫（.opencode + docs）两错误类变体零残留（仅需求/进度文档的审计叙述命中，属预期）；书籍 07/12 章、知识库 race-conditions §4 抽查自洽 ✓
- Phase 6 审计：3 个周期收敛——①2 轮通过 → 纯审抓 4 处（:1383 规范外推、:1430/:1431 取值规则、:1442 表、:1445 概括句）；②修复 → 2 轮通过 → 纯审再抓 3 处（:1581 拆零件示例、书籍 12:9 类比、12:16 定义句）；③修复 → 2 轮 + 纯审零问题（全载体旧模型词仅剩合法语境：:834 COOP"旧窗口复活"、描述题目固定代码的"写死"、BFCache"内存快照"）✓
- 不修项（已记录）：events 图库（flow 隔离历史记录）、记忆库执行记录条目（[bash]/[read] 日志）、历史需求文档 2026-09-21（过程记录，由本需求 §5 承接）
- 探针归档（补充执行）：`.opencode/web-analysis/scripts/probe-message-lifecycle/`（5 个）、`probe-cookie-scope/`（1 个）、`probe-navigation/`（2 个）——每目录自包含 README + package.json（可整体拷走）；命名规则：目录 = `probe-<行为域>`、文件 = `probe_<断言>.js`；原 `browser-probes` 单目录方案作废，旧暂存路径已从 git index 撤下
