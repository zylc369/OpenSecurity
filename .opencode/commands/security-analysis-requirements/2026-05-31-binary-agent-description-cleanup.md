# 需求：binary-analysis Agent 描述清理

## §1 背景与目标

**来源**: 用户直接反馈。Tab 切换到 binary-analysis 后，Agent 自我介绍说"我是 IDA Pro 二进制逆向分析 Agent"，但实际能力远超 IDA Pro（Frida、Unicorn、GUI 自动化、Playwright、进程 Patch 等）。

**痛点**: Agent 按主要工具（IDA Pro）而非领域（二进制逆向分析）命名自身，与 mobile-analysis、web-analysis 的命名惯例不一致，导致角色定位误导。

**预期收益**: 自我描述更准确，减少首次交互的角色混淆。

## §2 技术方案

原定 4 处文本替换，实施中发现 AGENTS.md 和 security-analysis-evolve.md 存在 agent/目录遗漏，实际执行 6 处：

| # | 文件 | 改动前 | 改动后 |
|---|------|--------|--------|
| 1 | `AGENTS.md` L3 | `IDA Pro 二进制逆向 + 移动端应用分析` | `二进制逆向分析 + 移动端应用分析 + Web 安全分析 + AI 安全分析` |
| 2 | `AGENTS.md` L9 | `IDA Pro 二进制逆向（PC 端 exe/dll/so）` | `二进制逆向分析（PC 端 exe/dll/so）` |
| 3 | `binary-analysis.md` L2 | `二进制逆向分析 — 输入 IDA 数据库路径和分析需求，自动完成逆向分析` | `二进制逆向分析 — 输入目标文件和分析需求，自动编排工具链完成逆向分析` |
| 4 | `binary-analysis.md` L16 | `你是 IDA Pro 逆向分析编排器。` | `你是二进制逆向分析编排器。` |
| 5 | `AGENTS.md` 目录结构 | 缺少 `web-analysis/`、`ai-security-analysis/` | 补全两个目录条目 |
| 6 | `AGENTS.md` Agent 索引 | 缺少 `security-coordinator`、`web-analysis`、`ai-security-analysis` | 补全全部 6 个 agent |
| 7 | `security-analysis-evolve.md` 架构图 | 缺少 `security-coordinator.md`、`ai-security-analysis.md` | 补全全部 6 个 agent；`binary-analysis.md` 注释同步更新 |

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 修改 AGENTS.md（2 处）**
- 文件: `AGENTS.md`
- 预估行数: 2 行修改
- 验证点: `grep -n "IDA Pro" AGENTS.md` 应返回 0 结果；确认 L3 涵盖三个 Agent；确认 L9 描述正确
- 依赖: 无

**步骤 2. 修改 binary-analysis.md（2 处）**
- 文件: `.opencode/agents/binary-analysis.md`
- 预估行数: 2 行修改
- 验证点: `grep -n "IDA Pro" .opencode/agents/binary-analysis.md` 应返回 0 结果；frontmatter description 和角色定义使用领域命名
- 依赖: 无

## §4 验收标准

### 功能验收
- [x] AGENTS.md 中不再包含 "IDA Pro" 的过时角色描述
- [x] AGENTS.md L3 标题涵盖四个 Agent 领域（二进制逆向 + 移动端 + Web + AI 安全）
- [x] AGENTS.md Agent 索引表完整列出全部 6 个 agent
- [x] security-analysis-evolve.md 架构图完整列出全部 6 个 agent 文件
- [x] binary-analysis.md frontmatter description 使用 "目标文件" 而非 "IDA 数据库路径"
- [x] binary-analysis.md 角色定义使用 "二进制逆向分析编排器"

> 注：§2 改动 5 中新增的目录结构条目已在后续需求 `2026-05-31-agents-md-simplify-and-log-ms.md` 中随整个目录结构节删除。

### 回归验收
- [x] binary-analysis.md 中 IDA 作为工具的正常提及不受影响（如工具脚本清单、知识库索引中的 IDAPython 等）

### 架构验收
- [x] 命名惯例与 mobile-analysis、web-analysis 保持一致（按领域命名）

## §5 与现有需求文档的关系

独立需求，不依赖其他需求文档。
