# 需求文档: 命令与目录重命名 v2

## §1 背景与目标

**来源**: 进化文档 v2（`docs/进化/进化-目录名规范化支持多平台-v2.md`）。v1 已完成数据目录和插件重命名，v2 继续重命名命令目录和文件，使命名与 `security-analysis` 体系对齐。
**目标**:
1. `ida-pro-analysis-requirements/` → `security-analysis-requirements/`
2. `ida-pro-analysis-docs/` → `security-analysis-docs/`
3. `gui-interact.md` → `gui-interact-pc.md`
4. `ida-pro-analysis-evolve.md` → `security-analysis-evolve.md`

## §2 技术方案

### 2.1 重命名清单

| 旧名 | 新名 | 类型 |
|------|------|------|
| `.opencode/commands/ida-pro-analysis-requirements/` | `.opencode/commands/security-analysis-requirements/` | 目录 |
| `.opencode/commands/ida-pro-analysis-docs/` | `.opencode/commands/security-analysis-docs/` | 目录 |
| `.opencode/commands/gui-interact.md` | `.opencode/commands/gui-interact-pc.md` | 文件 |
| `.opencode/commands/ida-pro-analysis-evolve.md` | `.opencode/commands/security-analysis-evolve.md` | 文件 |

### 2.2 引用更新

影响 10 个文件、~38 处引用:

| 文件 | 需替换内容 |
|------|-----------|
| `knowledge-base/gui-automation.md` | `gui-interact` → `gui-interact-pc`（1 处） |
| `security-analysis-evolve.md`（原 ida-pro-analysis-evolve.md） | `ida-pro-analysis-requirements` → `security-analysis-requirements`（2 处） |
| 3 个 requirements 历史文档 | `ida-pro-analysis-docs` → `security-analysis-docs`、`gui-interact` → `gui-interact-pc` |
| `2026-04-29-directory-and-plugin-rename.md` | 旧命令名 → 新命令名（7 处） |
| `docs/需求/需求-写技术文章-v1.md` | `ida-pro-analysis` 相关（1 处） |
| `docs/需求/需求-进化流程渐进式披露与Prompt瘦身.md` | `ida-pro-analysis-evolve` → `security-analysis-evolve`（5 处） |

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 全局替换字符串引用**
  - 文件: 全部 10 个文件
  - 替换: `ida-pro-analysis-requirements` → `security-analysis-requirements`、`ida-pro-analysis-docs` → `security-analysis-docs`、`gui-interact.md`/`gui-interact` 命令 → `gui-interact-pc`（仅命令引用，不含 `gui-interact-pc` 已有的）、`ida-pro-analysis-evolve` → `security-analysis-evolve`
  - 预估行数: ~38 行修改（纯字符串替换）
  - 验证点: grep 返回 0 结果（排除 `docs/进化/`）
  - 依赖: 无

**步骤 2. 重命名目录和文件**
  - 操作: mv 4 个目录/文件
  - 预估行数: 0
  - 验证点: 新路径存在 + 旧路径不存在
  - 依赖: 无（与步骤 1 可并行）

**步骤 3. 最终验证**
  - 验证点:
    1. `grep -r "ida-pro-analysis-requirements\|ida-pro-analysis-docs\|ida-pro-analysis-evolve" . --include='*.md'` → 0 结果（排除 `docs/进化/`）
    2. `grep -r "gui-interact[^-]" . --include='*.md'` → 0 结果（排除 `docs/进化/`，gui-interact-pc 不会匹配）
    3. 4 个新路径全部存在
  - 依赖: 步骤 1, 2

## §4 验收标准

### 功能验收
- [x] 全局无 `ida-pro-analysis-requirements` / `ida-pro-analysis-docs` / `ida-pro-analysis-evolve` 残留
- [x] `gui-interact` 命令引用全部改为 `gui-interact-pc`
- [x] 4 个目录/文件成功重命名

### 回归验收
- [x] 无代码逻辑变更，仅重命名

## §5 与现有需求文档的关系

- v1 的延续（`2026-04-29-directory-and-plugin-rename.md`）
- 不改变任何业务逻辑
