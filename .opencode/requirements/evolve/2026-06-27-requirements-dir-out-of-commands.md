# 需求: 进化需求文档移出 commands 目录

## §1 背景与目标

**来源痛点**: `security-analysis-requirements/` 原位于 `.opencode/commands/` 下。审计发现 opencode 命令加载器（`config/command.ts`）用 glob `{command,commands}/**/*.md` **递归扫描** commands/ 子树，而命令 schema（`ConfigCommandV1.Info`）**只要求 `template` 字段**。需求文档无 frontmatter，但 `gray-matter` 解析不报错、`template` 由全文填充——导致 56 个需求文档全部被**误注册为 opencode 命令**。

**量化影响**:
- commands/ 子树 62 个 .md，真正命令仅 5 个，**57 个非命令 .md 被误加载为命令**（含本次的 56 需求文档）。
- 命令命名空间污染；启动多解析 57 个文件。
- **潜在致命风险**: `command.ts:36`——若任一需求文档未来被加了 frontmatter 但不符合 Info schema，`decodeInfo` 失败会 `throw InvalidError`，中断整个命令加载。当前仅因文档无 frontmatter 才"侥幸"不崩。

**根因**: `security-analysis-evolve.md` agent prompt 把需求文档路径硬编码为 `commands/security-analysis-requirements/`（设计时未意识到 commands/ 会被递归扫描）。

**预期收益**: 根除 56 个误注册命令 + 崩溃风险；commands/ 回归纯净。

## §2 技术方案

### 改动

| 文件/目录 | 改动 |
|-----------|------|
| `.opencode/commands/security-analysis-requirements/` → `.opencode/requirements/evolve/` | 整目录移动（git mv，保历史） |
| `.opencode/agents/security-analysis-evolve.md` | 架构树（67-69 行）+ Phase 2 路径（152 行）+ 规则 4 路径（402 行） |
| `.opencode/commands/security-analysis-evolve.md` | Phase 2 路径（90 行）+ 规则 4 路径（337 行） |

### 不改动（历史记录，按"不改写历史"原则保留）
- `docs/进化/进化-目录名规范化支持多平台-v2.md`（记录过往重命名）
- 6 个需求文档内部的历史绝对路径引用（进度/重命名类文档， recounts 过去事件）

## §3 验收

- [x] 56 文件移至 `.opencode/requirements/evolve/`，git 识别为 rename（保历史）
- [x] agent/command 的 4 处活动路径引用已更新，无残留
- [x] commands/ 子树无 frontmatter 的 .md 从 57 降至 1（剩余 `security-analysis-docs/setup-guide.md` 属另一目录，见下）

## §4 遗留（同类问题，待后续处理）

`commands/` 清理进展：
- ✅ `ida-pro-analysis-scripts/`（废弃空壳，仅 `__pycache__`）— 已删
- ✅ `security-analysis-evolve.md`（stale 旧版，与 agents/ 同名 agent 重复）— 已删
- ⬜ `security-analysis-docs/setup-guide.md`（无 frontmatter → 仍被误注册为 1 个命令）— 待处理

## §5 与现有需求文档的关系

独立需求。呼应 `2026-04-29-command-directory-rename-v2.md`（曾处理命令目录重命名，但未触及需求文档位置这个根因）。
