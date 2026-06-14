# 需求文档: 数据目录重命名 + 插件重命名 + 动态 Agent 名

## §1 背景与目标

**来源**: 进化文档 v1（`docs/进化/进化-目录名规范化支持多平台-v1.md`）。当前数据目录名 `bw-ida-pro-analysis` 绑定了 IDA Pro，不适用于未来多平台（PC/Mobile/Web）安全分析场景。插件名 `binary-analysis` 同理。

**目标**:
1. 数据目录: `~/bw-ida-pro-analysis` → `~/bw-security-analysis`（全局替换，不改漏）
2. 插件文件: `binary-analysis.ts` → `security-analysis.ts`，导出名 `BinaryAnalysisPlugin` → `SecurityAnalysisPlugin`
3. 插件输出: 从硬编码 "BinaryAnalysis" 改为动态获取当前 agent 名字

**预期收益**: v2 多平台支持的必要前置步骤，使命名与多端安全分析定位对齐。

**不改动的部分**（v2 再处理）:
- Agent prompt 文件名 `binary-analysis.md` 不改
- `.opencode/binary-analysis/` 目录名不改
- Agent display name（二进制逆向分析）不改

## §2 技术方案

### 2.1 数据目录路径替换

`bw-ida-pro-analysis` → `bw-security-analysis`，影响 19 个文件、~71 处引用:

| 分类 | 文件 | 引用数 |
|------|------|--------|
| 运行时代码 | `plugins/binary-analysis.ts` | 1 |
| 运行时代码 | `scripts/create_task_dir.py` | 2 |
| 运行时代码 | `scripts/detect_env.py` | 2 |
| Agent prompt | `agents/binary-analysis.md` | 15 |
| 活跃文档 | `binary-analysis/README.md` | 1 |
| 活跃文档 | `binary-analysis/environment-setup.md` | ~13 |
| 活跃文档 | `binary-analysis/context-persistence.md` | 3 |
| 活跃文档 | `knowledge-base/templates.md` | 1 |
| 活跃文档 | `knowledge-base/gui-automation.md` | 3 |
| 活跃文档 | `knowledge-base/opencode-plugin-debugging.md` | 5 |
| 命令文档 | `commands/gui-interact-pc.md` | 1 |
| 命令文档 | `commands/security-analysis-docs/setup-guide.md` | ~13 |
| 命令文档 | `commands/security-analysis-evolve.md` | 1 |
| 需求历史 | `requirements/2026-04-22-comprehensive-review-fixes.md` | 2 |
| 需求历史 | `requirements/2026-04-22-environment-dependency-hardening.md` | 6 |
| 需求历史 | `requirements/2026-04-24-gui-visual-automation.md` | 1 |
| 需求历史 | `requirements/2026-04-27-ecdlp-compression-parallel.md` | 1 |
| 需求历史 | `requirements/2026-04-28-task-dir-persistence.md` | 1 |
| 项目文档 | `README.md` | 2 |

### 2.2 插件重命名

**文件操作**: `.opencode/plugins/binary-analysis.ts` → `.opencode/plugins/security-analysis.ts`

**导出名**: `BinaryAnalysisPlugin` → `SecurityAnalysisPlugin`

**需同步更新引用的文件**（引用了旧插件文件名或导出名）:

| 文件 | 需替换内容 |
|------|-----------|
| `knowledge-base/opencode-plugin-debugging.md` | `BinaryAnalysisPlugin` → `SecurityAnalysisPlugin`（~5 处）, `binary-analysis.ts` → `security-analysis.ts` |
| `commands/security-analysis-evolve.md` | `binary-analysis.mjs` → `security-analysis.ts`（架构图 + 验证表，~10 处）, `BinaryAnalysis` agent 引用保留 |
| `binary-analysis/context-persistence.md` | `binary-analysis.mjs` → `security-analysis.ts`（1 处） |
| `binary-analysis/knowledge-base/opencode-agent-format.md` | `binary-analysis.mjs` → `security-analysis.ts`（1 处，line 133） |
| `README.md` | `binary-analysis.ts` → `security-analysis.ts`（如有） |
| 6 个需求历史文档 | `binary-analysis.mjs` → `security-analysis.ts` |

### 2.3 动态 Agent 名获取

基于 oh-my-openagent 源码分析，OpenCode Plugin 可通过以下方式获取当前 agent 名:

1. `chat.message` hook 的 `input.agent?: string` — 最直接
2. `event` hook 的 `message.updated` 事件中的 `UserMessage.agent` — 备选
3. `client.session.messages()` API — 最终回退

**实现方案**: 采用 oh-my-openagent 的已验证模式:
- 新增 `sessionAgentMap: Map<string, string>` 存储 sessionID → agentName 映射
- 在 `chat.message` hook 中捕获 `input.agent` 并存入 map
- 在 `system.transform` 和 `compacting` hook 中通过 sessionID 查询 agent 名
- 回退策略: map 中无记录时默认使用 `"SecurityAnalysis"`

**受影响的 plugin 输出字符串**:

| 当前字符串 | 改为 |
|-----------|------|
| `## BinaryAnalysis 环境信息` | `## ${agentName} 环境信息` |
| `## BinaryAnalysis 分析状态（压缩时必须保留）` | `## ${agentName} 分析状态（压缩时必须保留）` |
| `如果包含 BinaryAnalysis 相关内容` | `如果包含 ${agentName} 相关内容` |

**不受影响的字符串**（v1 不改）:

| 字符串 | 原因 |
|--------|------|
| `.opencode/agents/binary-analysis.md`（COMPACT_REMINDER 中） | agent prompt 文件名不改 |
| `.opencode/binary-analysis`（system.transform fallback 中） | 目录名不改 |

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 影响级别 |
|------|---------|---------|
| `plugins/security-analysis.ts`（原 binary-analysis.ts） | 重命名 + 重写 | 高 |
| `agents/binary-analysis.md` | 路径替换 | 高 |
| `scripts/create_task_dir.py` | 路径替换 | 中 |
| `scripts/detect_env.py` | 路径替换 | 中 |
| `knowledge-base/opencode-plugin-debugging.md` | 路径替换 + 插件名替换 | 低 |
| `knowledge-base/templates.md` | 路径替换 | 低 |
| `knowledge-base/gui-automation.md` | 路径替换 | 低 |
| `binary-analysis/README.md` | 路径替换 | 低 |
| `binary-analysis/environment-setup.md` | 路径替换 | 低 |
| `binary-analysis/context-persistence.md` | 路径替换 + 插件名替换 | 低 |
| `commands/gui-interact-pc.md` | 路径替换 | 低 |
| `commands/security-analysis-docs/setup-guide.md` | 路径替换 | 低 |
| `commands/security-analysis-evolve.md` | 路径替换 + 插件名替换 | 中 |
| `README.md` | 路径替换 | 低 |
| 6 个需求历史文档 | 路径替换 + 插件名替换 | 低 |

### §3.1 实施步骤拆分

**步骤 1. 全局替换数据目录路径 `bw-ida-pro-analysis` → `bw-security-analysis`**
  - 文件: 全部 19 个文件
  - 预估行数: ~71 行修改（纯字符串替换，无逻辑变更）
  - 验证点: `grep -r "bw-ida-pro-analysis" .opencode/ README.md --include='*.md' --include='*.py' --include='*.ts'` 返回 0 结果
  - 依赖: 无

**步骤 2. 重命名插件文件**
  - 文件: `.opencode/plugins/binary-analysis.ts` → `.opencode/plugins/security-analysis.ts`
  - 预估行数: 0（仅 git mv）
  - 验证点: 新文件存在 + 旧文件不存在
  - 依赖: 无

**步骤 3. 更新插件代码（导出名 + 动态 agent 名）**
  - 文件: `.opencode/plugins/security-analysis.ts`
  - 改动内容:
    1. 导出名 `BinaryAnalysisPlugin` → `SecurityAnalysisPlugin`
    2. 日志 `BinaryAnalysisPlugin loaded` → `SecurityAnalysisPlugin loaded`
    3. 新增 `sessionAgentMap: Map<string, string>`
    4. 新增 `chat.message` hook 捕获 `input.agent`
    5. `COMPACTION_CONTEXT_PROMPT` 中 "BinaryAnalysis" → 动态拼接（改为函数）
    6. `system.transform` 中 `## BinaryAnalysis 环境信息` → `## ${agentName} 环境信息`
    7. `debugLog` 中关键位置加入 agent 名输出
  - 预估行数: ~60 行修改/新增
  - 验证点:
    - 文件中无 `BinaryAnalysis` 字符串（grep 验证）
    - 新增 `chat.message` hook、`sessionAgentMap` 存在
    - TypeScript 基本结构完整（有 export、return hooks 对象）
  - 依赖: 步骤 2

**步骤 4. 更新文档中的插件引用**
  - 文件:
    - `knowledge-base/opencode-plugin-debugging.md`（~5 处 `BinaryAnalysisPlugin` → `SecurityAnalysisPlugin`）
    - `knowledge-base/opencode-agent-format.md`（1 处 `binary-analysis.mjs` → `security-analysis.ts`）
    - `commands/security-analysis-evolve.md`（~10 处 `binary-analysis.mjs` → `security-analysis.ts`，架构图 + 验证表）
    - `binary-analysis/context-persistence.md`（1 处 `binary-analysis.mjs` → `security-analysis.ts`）
    - 6 个需求历史文档中的 `binary-analysis.mjs` → `security-analysis.ts`
    - `README.md`（如有插件文件名引用）
  - 预估行数: ~30 行修改
  - 验证点:
    - `grep -r "BinaryAnalysisPlugin" .opencode/ --include='*.md'` 返回 0 结果
    - `grep -r "plugins/binary-analysis" .opencode/ --include='*.md'` 返回 0 结果（精确匹配插件文件路径引用）
    - `grep -r "binary-analysis\.mjs" .opencode/ --include='*.md'` 返回 0 结果
  - 依赖: 步骤 1, 步骤 3
  - **注意**: `binary-analysis.md`（agent prompt 文件名）和 `.opencode/binary-analysis/`（目录名）的引用**不替换**，这些在 v2 再改

**步骤 5. 最终验证**
  - 执行验证点:
    1. `grep -r "bw-ida-pro-analysis" . --include='*.md' --include='*.py' --include='*.ts' --include='*.json'` → 0 结果（排除 `docs/进化/` 和 `.git/`）
    2. `grep -r "BinaryAnalysisPlugin" . --include='*.md' --include='*.ts'` → 0 结果
    3. `python -c "compile(open('.opencode/binary-analysis/scripts/create_task_dir.py').read(), 'x', 'exec')"` 通过
    4. `python -c "compile(open('.opencode/binary-analysis/scripts/detect_env.py').read(), 'x', 'exec')"` 通过
    5. 插件文件存在且结构完整（export const SecurityAnalysisPlugin）
  - 依赖: 步骤 1-4

## §4 验收标准

### 功能验收
- [x] 全局无 `bw-ida-pro-analysis` 残留（排除 `docs/进化/`）
- [x] 全局无 `BinaryAnalysisPlugin` 残留
- [x] 全局无 `binary-analysis.ts` 或 `binary-analysis.mjs` 残留（排除 `docs/进化/`）
- [x] 插件文件成功重命名为 `security-analysis.ts`
- [x] 插件导出名为 `SecurityAnalysisPlugin`
- [x] 插件包含 `chat.message` hook 用于捕获 agent 名
- [x] `system.transform` 输出使用动态 agent 名而非硬编码 "BinaryAnalysis"
- [x] `compacting` hook 输出使用动态 agent 名
- [x] Agent prompt 中 `.opencode/binary-analysis` 路径引用未被误改

### 回归验收
- [x] Python 脚本语法检查全部通过（create_task_dir.py、detect_env.py）
- [x] TypeScript 插件语法检查通过
- [x] Agent prompt 行数未显著增长（< 450 行）

### 架构验收
- [x] 数据目录路径单一来源（仅 config.json 和常量定义处可修改）
- [x] 插件 agent 名获取模式与 oh-my-openagent 一致（sessionAgentMap + chat.message hook）
- [x] 未引入循环依赖

## §5 与现有需求文档的关系

- 本次改动是纯重命名 + 插件增强，不改变任何业务逻辑
- 与 `2026-04-22-environment-dependency-hardening.md` 有路径交叉（env_cache.json 路径变更）
- 与 `2026-04-28-task-dir-persistence.md` 有路径交叉（workspace 路径变更）
- 所有历史需求文档中的旧路径已在本需求中统一替换
