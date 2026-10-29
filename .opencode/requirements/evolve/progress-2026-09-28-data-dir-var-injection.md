# 进度: 数据根目录变量化（$DATA_DIR 注入）与硬编码路径清理

> 需求: `2026-09-28-data-dir-var-injection-and-hardcoded-path-cleanup.md`（Phase 3 审计通过）
> 来源: 用户指令（analysis-attribution 命令路径硬编码 → 全仓同类一次性清理）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|------|------|------|------|
| S1 | 插件注入（security-analysis.ts） | ☑ | envSection:364 / shell.env:1248 / debugLog:1296；bun build 零错误 |
| S2 | 插件消息常量（env-check.ts） | ☑ | import + 2 处替换；字面量 0；bun build 零错误 |
| S3 | 运行时文档批次一（commands） | ☑ | commands/ 字面量 0；行数不变（55/75/7） |
| S4 | 运行时文档批次二（rules + evolve prompt） | ☑ | 仅剩 evolve 权限行（例外）；展开 428/449/407/416/320 不变 |
| S5 | 知识库批次（含退役机制修正） | ☑ | KB 字面量 0；IPC 冒烟预实测 HTTP 200 |
| S6 | 代码批次（tools + console + wrapper） | ☑ | py_compile 通过；沙箱/回退/模板渲染三测通过；test_control 87 passed（1 既有 collection error） |
| S7 | 端到端验证（插件 + 命令回归） | ☑ | 测试①：新进程 evolve 会话 bash `DATA_DIR=[...]` + 环境信息段行逐字验证；测试②：命令完整产出归因报告 |
| S8 | 全仓复扫与文档同步 | ☑ | 命令草稿==文件 True；复扫仅剩 §2.4 例外；add-new-agent 注记；旧文档 v3 |

## as-built 记录

- Phase 3 审计：2 轮修复（计数/措辞/遗漏项 C8、test/** 分类）+ 1 轮纯审计（发现 §4 计数陈旧 → 修复后新周期 2 轮 + 纯审计零问题）通过。
- Phase 5/6：S1-S8 全部完成；23 处替换落地；插件 `bun build` 零错误；Python `py_compile` 通过；`test_control.py` 87 passed（1 既有 collection error，见需求 §5）。
- 端到端（新进程加载新插件）：
  - 测试①（`--agent security-analysis-evolve`）：bash 输出 `DATA_DIR=[/Users/aserlili/bw-security-analysis]`、`AGENT_DIR=[.../security-analysis-evolve]`；环境信息段新增行逐字吻合设计文案。
  - 测试②（`/analysis-attribution` 对 `20260927_160838_e8ba_web-analysis`）：完整归因报告产出（机制贡献表/消费明细/没有-错过/结论/候选线索），输出 87,996B。
- 复扫终态：运行时文档（agents/commands/rules/KB）= 仅权限行例外；plugins = 仅 constants 默认值定义与测试守卫；tools/mcp-servers/control = env 优先回退行与规范默认值/标签。
- 观察：测试②报告正文用 `~/bw-security-analysis/...` 简写指代已解析路径（生成文本，非文档硬编码；源文档零残留）。
