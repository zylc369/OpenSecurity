# 进度: 单源收口（归因执行单源 + 归属验证规则单源）

> 需求: `2026-09-29-single-source-consolidation.md`（Phase 3/6 审计通过：Phase 3 含 1 轮修复；Phase 6 Round 1/2 + 纯审计）
> 来源: 用户拍板"方案 A" + 用户指出的收口问题（evidence-discipline ↔ ssrf-advanced 双写）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|---|---|---|---|
| 1 | 归因单源：命令 L13 + §6 指针 + 蓝图同步（v3 记录） | ☑ | 命令蓝图 diff 逐字一致；"执行权威：本文"=1、"先读它再动手"=0 |
| 2 | 归属验证收口：ssrf §7 + 蓝图同步（v5 记录） | ☑ | T1-T6 diff 全 True；三问运营面仅 `evidence-discipline.md` 一处；"止损判据"残留 0 |
| 3 | 收尾核查 | ☑ | 两组蓝图 diff 全跑；字节扫描 7 文件 OK；两处 progress 记录；本文件写入 |

## 终验数据（2026-09-29）

- 命令仍 77 行（L13 行内替换，行数不变）；`ssrf-advanced.md` 129 行（§7 行内替换，净 ~0）
- 指针落点：`retrospective-methodology.md` §6 顶部（指向命令）+ `ssrf-advanced.md` §7（指向 `$OPENCODE_ROOT/agents-rules/evidence-discipline.md`）
- 断言：三问规则运营面单源（agents-rules/evidence-discipline.md）；"止损判据"运营面归零（改"止损后去向"）
- 修订记录：attribution-v2 需求 → v3；evidence-guards 需求 → v5；两份 progress 各 +1 条

## 修订记录

- 2026-09-29（落位校正 + §6 去重，第二轮）：归属验证迁至 `agents/web-analysis.md` 核心原则 #7（ssrf §7 与共享片段清出）；§6 与命令去重（执行规程单源在命令、§6 改导航 + 编号顺延）。见 `2026-09-29-consolidation-round2.md`。
