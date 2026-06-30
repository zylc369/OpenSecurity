# 需求：writeup 知识进化能力（重做版）

> 创建: 2026-06-30
> 状态: Phase 2
> 来源: 多轮对话中用户的反馈和教训汇总
> 前置需求: 2026-06-30-writeup-knowledge-sourcing-and-evolution.md（已废弃，本文替代）

## §1 背景与目标

**需求**: 建立可复用的"writeup → 知识库"进化能力，支持三种触发：
- 用户要求搜索下载 writeup 学习
- 用户指定已有文件/目录
- 基于对话上下文进化

**前次实施的问题（用户反馈汇总）**:

| # | 问题 | 教训 |
|---|------|------|
| 1 | 知识库条目引用外部文件路径 | 违反 writing-guide，必须提取内容 |
| 2 | 写赛事名/作者名/"首创" | 违反 writing-guide，使用者不关心 |
| 3 | 只下载不提炼 | 下载的价值在于进化知识，不是数量 |
| 4 | 删引用后未确认内容是否已沉淀 | 删前必须验证目标位置有等效描述 |
| 5 | sourcing-guide 混入提炼流程（§4） | sourcing-guide 只管搜索下载 |
| 6 | sourcing-guide 定位与内容矛盾 | "搜索下载时读取"不应包含"指定文件"的说明 |
| 7 | 入口 C 和 A/B 格式不一致 | 每个入口一行简述，细节靠知识库文档 |
| 8 | ASCII art 中塞详细步骤/路径 | 流程图只做概览，细节用自然语言 |
| 9 | 用缩写"sourcing-guide" | 必须用完整路径变量 |
| 10 | 说"直接进入步骤5""不走Phase2-3" | 不应描述跳过什么，只描述做什么 |
| 11 | "详见流程图后的详细步骤" | 模糊引用，AI 不知道去哪找 |
| 12 | 删 §4 前未检查 evolve prompt 是否有等效描述 | 删前必须验证 |
| 13 | docs/ 下放 agent 脚本 | agent 脚本/知识库放 $AGENT_DIR |
| 14 | 索引表用统一路径说明 | 每条写全路径变量 |

**目标**: 一次性做对，不再返工。

## §2 技术方案

### 文件分工（三个文件各管一件事，不重叠）

| 文件 | 位置 | 职责 |
|------|------|------|
| `knowledge-sourcing-guide.md` | `$AGENT_DIR/knowledge-base/` | **搜索下载**: 去哪找、怎么下载、判断价值 |
| `knowledge-writing-guide.md` | `$SHARED_DIR/knowledge-base/` | **写作 + 提炼**: 怎么写好条目 + 从源文档提炼的方法 |
| `download_sources.py` | `$AGENT_DIR/scripts/` | **下载工具**: 支持 --url/--github 参数 |
| evolve prompt | `$AGENT_DIR` | **流程**: Phase 0-6 + 入口 C |

### 具体改动

| 文件 | 操作 | 内容 |
|------|------|------|
| `knowledge-sourcing-guide.md` | **确认现状** | §1-§3 已完成（渠道/下载/价值判断），102 行，无需修改 |
| `knowledge-writing-guide.md` | **增加 §6** | "从源文档提炼"：识别值得提炼的技术、转化为知识库格式、抄录完整内容、验证准确性 |
| `download_sources.py` | **确认现状** | 泛化版已完成，支持 --url/--github，无需修改 |
| evolve prompt | **确认现状** | 入口 C（一行）+ 操作指引 + 索引表 + 规则 10 已完成 |

### 关键设计原则

1. **sourcing-guide 只管搜索下载**，不包含提炼/写入/审计（那些是 evolve prompt 的 Phase 0-6 通用流程）
2. **writing-guide 增加"从源文档提炼"方法**，因为这是"怎么写好知识库条目"的自然延伸
3. **入口 C 和 A/B 格式一致**（一行简述），操作方法通过"入口 C 操作指引"引用 sourcing-guide
4. **不引用 docs/ 目录**（规则 10）
5. **所有引用用完整路径变量**

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 在 writing-guide 增加 §6"从源文档提炼"**
- 文件: `$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`
- 预估行数: ~25 行
- 验证点: 人工读一遍确认自包含；确认不与 §2-§5 重复；确认覆盖"识别技术/转化格式/抄录payload/验证准确性"
- 内容:
  - 识别值得提炼的技术（对照知识库找 gap，高价值 vs 低价值）
  - 转化为知识库格式（源文档按时间线叙述 → 知识库按场景→检查→利用组织）
  - 抄录完整内容（完整 payload 不写骨架，具体参数值/版本号）
  - 验证准确性（回溯源文档确认公式/步骤/payload 一致）

**步骤 2. 全面一致性验证**
- 文件: 全部相关文件
- 预估行数: 0（只验证不修改）
- 验证点:
  - sourcing-guide §1-§3 无提炼/写入/审计内容
  - evolve prompt 入口 C 一行，和 A/B 一致
  - evolve prompt 操作指引引用 sourcing-guide（完整路径）
  - evolve prompt 索引表 sourcing-guide 条目（完整路径）
  - evolve prompt 规则 10 存在
  - writing-guide §6 存在且自包含
  - download_sources.py 在 $AGENT_DIR/scripts/
  - 无任何文件引用 docs/ 目录（规则 10）

## §4 验收标准

### 功能验收
- [ ] writing-guide §6 覆盖: 识别技术、转化格式、抄录payload、验证准确性
- [ ] sourcing-guide 只有 §1-§3（搜索下载专用）
- [ ] evolve prompt 入口 C 和 A/B 格式一致（各一行）
- [ ] download_sources.py 支持 --url/--github

### 回归验收
- [ ] writing-guide §1-§5 未被修改（只增加 §6）
- [ ] sourcing-guide §1-§3 未被修改
- [ ] evolve prompt Phase 0-6 流程完整（不跳过任何 Phase）
- [ ] 规则 10（禁止引用 docs/）存在

### 架构验收
- [ ] sourcing-guide 在 $AGENT_DIR/knowledge-base/
- [ ] download_sources.py 在 $AGENT_DIR/scripts/
- [ ] 无文件引用 docs/ 目录（规则 10 的例外：download_sources.py 的 SOURCE_DIR 是写入目标不是依赖）

## §5 与现有需求文档的关系

- 替代 `2026-06-30-writeup-knowledge-sourcing-and-evolution.md`（该需求的实施有大量返工）
- 本次只新增 writing-guide §6 + 验证现有改动的一致性
