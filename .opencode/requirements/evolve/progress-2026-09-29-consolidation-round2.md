# 进度: 收口第二轮（归属验证落位校正 + §6 去重）

> 需求: `2026-09-29-consolidation-round2.md`（Phase 3/6 审计通过：Phase 3 含 1 轮修复；Phase 6 Round 1/2 + 纯审计）
> 来源: 用户复核（归属验证落位过宽 + §6 与命令重复）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|---|---|---|---|
| 1 | 归属验证落位校正（web 原则 #7；片段回退 2 条；ssrf §7 删除 + 头部/索引去词） | ☑ | 运营面单源断言：唯一 `agents/web-analysis.md`；三问在 agents-rules/与 KB 零命中；"共享基础设施"运营面零命中 |
| 2 | §6 去重（命令吸收 §6.2 独有要点 + L13 去反向引用；§6 导航化；6.3/6.4 顺延；evolve prompt 两处引用改指） | ☑ | 命令蓝本 diff 逐字一致；命令内 "§6" 零命中；evolve prompt §6.2 残留零；§6.1/6.2 编号连续 |
| 3 | 收尾核查 | ☑ | T1/T3/T5/T6 精确复跑全 True；T2/T4 "已撤 v6" 注记在案；字节扫描 10 文件 OK；展开行数复算对账 |

## 终验数据（2026-09-29）

- 行数：evidence-discipline 2（-1）；ssrf-advanced 121（-8）；web-analysis 254（+1）；retrospective-methodology 74（-16）；命令 77（不变）；evolve prompt 449（不变）
- 展开行数：web 431 / ai 417 / binary 450 / mobile 408 / crypto 321（binary 450 属 450-600 建议区，沿用既有提取建议）
- 断言：归属验证运营面单源 = `agents/web-analysis.md` 核心原则 #7；§6（retrospective 系）运营引用零；引用单向（§6→命令，命令不再指 §6）
- 记录：evidence-guards 需求 v6、consolidation 需求 v2、attribution-v2 需求 v4（含蓝图 L13/步骤 2 同步）+ 3×progress 记录 + 本文件
- 2026-09-29（收尾修正，用户复核触发）：evolve prompt 中复测/取证描述整句删除（L17-18 注释、L63 工具策略）——工具策略只留权限/用途级说明；规程单源在命令、路由走 retrospective §6 导航。evolve prompt 449→448 行。
