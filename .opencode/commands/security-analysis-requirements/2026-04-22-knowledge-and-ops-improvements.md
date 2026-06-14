# BinaryAnalysis 知识沉淀与运维改进

## §1 背景与目标

**来源**: 用户提出 4 项改进中的前 3 项

**痛点**:
1. 每次进化 BinaryAnalysis Agent 都要重新读 oh-my-openagent 源码猜测 API（上次读了 10+ 文件，system.transform 就是猜错的）
2. Plugin 从未验证过是否能工作，出问题时没有排查手段
3. oh-my-openagent 作为参考代码散落在本地磁盘，没有纳入项目版本管理

**预期收益**:
- 方案 1: oh-my-openagent 代码随项目版本管理，团队成员无需手动 clone
- 方案 2: 进化时从"读 10 个源文件+猜测 API"变为"读 2-3 个知识文档"，减少试错
- 方案 3: 能确认 Plugin 是否正常工作，出问题时快速定位

## §2 技术方案

### 方案 1: 添加 oh-my-openagent 子模块

- 路径: `vendor/oh-my-openagent`
- 仓库: `https://github.com/code-yeongyu/oh-my-openagent.git`
- 与现有 `vendor/ida-sdk` 平级

### 方案 2: 提取 OpenCode Plugin/Agent 知识文档

从 oh-my-openagent 源码提取以下知识文档到 `knowledge-base/`:

**文档 1: `opencode-plugin-api.md`** — Plugin API 参考
- 可用 hooks 列表及签名（基于 oh-my-openagent `src/plugin-interface.ts` 和 `src/index.ts`）
- 每个 hook 的 output 类型（这是上次猜测错误的根源）
- hook 触发时机和用途
- 安全创建模式（safe hook creation）
- 标注: 基于 oh-my-openagent 当前版本，API 可能变化

**文档 2: `opencode-agent-format.md`** — Agent 格式规范
- Agent 文件格式（markdown frontmatter）
- mode 字段（primary/subagent/all）
- 搜索路径优先级
- 配置覆盖字段（model、tools、prompt 等）

### 方案 3: Plugin 测试排查指南

新建 `knowledge-base/opencode-plugin-debugging.md`:
- 测试方法: 如何验证 Plugin 是否被加载、hook 是否触发
- 排查流程: 环境注入失败 vs compaction 失败 vs Agent 未加载的区分方法
- 日志查看: OpenCode 日志位置、Plugin 错误输出
- 常见问题与解决

## §3 实现规范

### 改动范围表

| 方案 | 文件 | 改动类型 | 影响范围 |
|------|------|---------|---------|
| 1 | `vendor/oh-my-openagent` | git submodule add | 无代码影响 |
| 2 | `knowledge-base/opencode-plugin-api.md` | 新建 | 知识库 |
| 2 | `knowledge-base/opencode-agent-format.md` | 新建 | 知识库 |
| 3 | `knowledge-base/opencode-plugin-debugging.md` | 新建 | 知识库 |

### 编码规则
- 知识文档必须自包含（不依赖 Agent prompt 上下文）
- 必须标注来源版本和"API 可能变化"警告
- 路径使用相对路径

## §4 验收标准

### 功能验收
- [ ] `vendor/oh-my-openagent` 子模块存在且可访问
- [ ] 3 个知识文档内容完整且自包含
- [ ] 知识文档中的 API 签名与 oh-my-openagent 源码一致
- [ ] 知识文档标注了版本和变化警告

### 回归验收
- [ ] 现有 Python 文件语法检查通过
- [ ] Plugin 语法检查通过
- [ ] Agent prompt 无需改动

### 架构验收
- [ ] 知识文档路径使用 `$SCRIPTS_DIR/knowledge-base/<文件名>` 格式
- [ ] vendor/oh-my-openagent 不影响项目其他部分

## §5 与现有需求文档的关系

无前置依赖。与 `2026-04-22-plugin-and-architecture-improvements.md` 互补（那篇改代码，这篇沉淀知识）。
