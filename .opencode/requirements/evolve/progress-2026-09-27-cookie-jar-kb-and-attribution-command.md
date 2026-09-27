# 进度: Cookie Jar 技法入库 + 记忆检索策略 + 机制归因命令

> 需求: `2026-09-27-cookie-jar-kb-and-attribution-command.md`（Phase 3 审计通过）
> 来源: CookieCorp 复盘 → 用户确认 A+B+C′

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|------|------|------|------|
| S1 | bot-patterns.md §3.4 + §4.1 微调 | ☑ | 116→160 行（+44）；叙事词零命中；§4.1 行 L153 更新 |
| S2 | web-analysis.md 索引行替换 | ☑ | L181 替换；252 行不变；占位符 7 处；展开 428（S4 后复核） |
| S3 | xss-advanced.md 交叉引用 | ☑ | L80 新增；指向 bot-patterns §3.4（锚点存在） |
| S4 | knowledge-management.md +2 行 | ☑ | 29→31 行；两条 bullet 就位；5 agent 展开 428/449/407/416/320 |
| S5 | commands/analysis-attribution.md 新建 | ☑ | 54 行；frontmatter YAML 合法；无硬编码路径 |
| S6 | 全量验证 | ☑ | 展开 428/449/407/416/320；占位符 7×5；锚点/引用/叙事词全绿 |

## as-built 记录

- Phase 3 审计：2 轮修复（嵌套围栏/措辞/行数估计）+ 1 轮纯审计（发现 2 处→修复后新周期：2 轮 + 纯审计零问题）通过。
- Phase 5/6：S1-S6 全部完成；实现与 §2.1/§2.3 全文稿 `diff` 为零；git diff 仅含预期 hunk。
- Phase 6 审计：2 轮 + 纯审计（零问题）通过。
- 交付物：`bot-patterns.md` §3.4（+45/-1）、`web-analysis.md` 索引行、`xss-advanced.md` +2、`knowledge-management.md` +2、`commands/analysis-attribution.md`（54 行）。
- 回归数据：展开行数 web 428 / binary 449 / mobile 407 / ai 416 / crypto 320；占位符 7×5；叙事词零命中。

## 功能测试（Phase 6 后补测 + 修订 v2）

- **本地 Playwright 机制验证**（Chromium 151.0.7922.34，脚本 `cookiejar-test/test_cookie_jar.py`、`test2.py`~`test4.py`）：
  - T1 同路径 HttpOnly 不可被 JS 覆盖（写 `role=chief` 后仍为旧值、无新 cookie）→ PASS
  - T2 溢出驱逐旧 role（无 Priority）→ 末尾补写 `role=chief` 成功，`session`（`Priority=High`）幸存 → PASS
  - T3 目标写在最前（无后续补写）→ 被批量驱逐清掉（顺序条件成立）→ PASS
  - T4 配额动态：180 上限；超过时**一次批量清至低水位 150**（150↔180 锯齿，幸存者=最新写入）→ 据此修订 §3.4 驱逐描述（v2）
- **命令端到端**：`opencode run --command analysis-attribution <task-dir> --auto` 对 `20260927_160838_e8ba_web-analysis` 完整产出归因报告（机制贡献表/知识消费明细/没有与错过清单/改进线索）→ PASS；对照组（不存在的命令）报错 → 验证加载机制
- **修订 v2**：§3.4 驱逐描述细化（批量低水位）；命令补"外部目录权限提示"行（首测发现非交互模式外部目录读取被权限拦截）
- 遗留观察：binary 449 贴近 450 红线（下次 +1 行需先瘦身评估）。
