# 需求: 补充 evolve agent 的文件归属判定规则

## §1 背景与目标

**来源**: mobile-analysis 进化 v1 的复盘。evolve agent 将通用知识（Frida 17.x API 变化速查）和通用脚本先放在 `mobile-analysis/` 下，经用户提醒后才沉淀到 `binary-analysis/`。

**痛点**: evolve agent 缺少"通用 vs 特定"的归属判定规则，导致：
- 通用知识/脚本放错位置 1 次
- 需要用户额外提醒 1 轮
- 额外执行 5 个文件的移动/引用调整

**预期收益**: 消除归属判断的模糊性，未来同类进化中不再需要用户提醒。

## §2 技术方案

### 改动文件

| 文件 | 改动类型 | 说明 |
|------|---------|------|
| `.opencode/agents/security-analysis-evolve.md` | 修改 | 补充架构图 + 归属判定规则 |

### 具体改动

#### 1. 架构图补充 mobile-analysis 完整结构

当前 `mobile-analysis/` 只有一行注释。补充为完整的子目录结构，与 `binary-analysis/` 同等详细程度。

#### 2. 规则 4 文件放置规则补充

在规则 4 的文件放置列表中：
- 补充 `mobile-analysis/scripts/` 作为移动端特有脚本的放置位置
- 新增"归属判定规则"，明确通用 vs 特定的判断标准

### 归属判定规则设计

核心判定逻辑：

```
知识/脚本是否只被一个 agent 使用？
├── 是 → 该 agent 专属的目录（mobile-analysis/ 或 binary-analysis/）
└── 否（或不确定） → binary-analysis/（通用层）
```

具体标准：
- **通用（放 `binary-analysis/`）**：PC 端和移动端都可能用到的知识/脚本/模式。例如：Frida API 变化、Hook 模板、密码学验证模式
- **移动端特有（放 `mobile-analysis/`）**：只在移动端场景才有意义的知识/脚本。例如：APK 反编译、DEX dump、Android 加固识别
- **PC 端特有（放 `binary-analysis/`）**：只在 PC 端场景才有意义的。例如：IDA 调试器策略、Win32 GUI 自动化
- **不确定时默认放 `binary-analysis/`**：binary-analysis 是最早存在的通用层，不确定归属时先放通用层

### mobile-analysis 依赖 binary-analysis 的关系

mobile-analysis agent 可以引用 binary-analysis 的知识库（通过 `$IDA_SCRIPTS_DIR` 变量），反之不可。这是一个单向依赖关系，类似于代码模块的 import 方向。

## §3 实现规范

### 改动范围表

| 文件 | 行数变化 | 风险 |
|------|---------|------|
| `security-analysis-evolve.md` | +18 行（架构图 +2, 规则 4 +16） | 低 |

### §3.1 实施步骤

```
步骤 1. 补充架构图中 mobile-analysis 的完整子目录结构
  - 文件: .opencode/agents/security-analysis-evolve.md
  - 预估行数: 新增 ~3 行（替换原有 1 行注释为 5 行结构）
  - 验证点: 架构图清晰展示 mobile-analysis/ 的 scripts/ 和 knowledge-base/ 子目录
  - 依赖: 无

步骤 2. 补充规则 4 的归属判定规则和 mobile-analysis/scripts/ 位置
  - 文件: .opencode/agents/security-analysis-evolve.md
  - 预估行数: 新增 ~15 行
  - 验证点: 
    1. 文件放置列表包含 mobile-analysis/scripts/
    2. 归属判定规则有明确的判断标准和默认行为
    3. 依赖方向说明清晰（mobile-analysis 可引用 binary-analysis，反之不可）
  - 依赖: 步骤 1

步骤 3. 语法检查 + 行数检查
  - 文件: .opencode/agents/security-analysis-evolve.md
  - 预估行数: 0 行（纯验证）
  - 验证点: 
    1. 文档行数确认（预估 ~450 行）
    2. 人工通读修改部分，确认无矛盾、无遗漏
  - 依赖: 步骤 2
```

## §4 验收标准

### 功能验收
- [ ] 架构图展示 mobile-analysis/ 的完整子目录（scripts/、knowledge-base/）
- [ ] 规则 4 文件放置列表包含 mobile-analysis/scripts/
- [ ] 归属判定规则有 4 种情况（通用、移动端特有、PC 端特有、不确定）的判断标准
- [ ] 默认行为明确（不确定时放 binary-analysis/）
- [ ] 依赖方向说明清晰

### 回归验收
- [ ] 规则 4 其他部分（IDAPython 脚本、Agent prompt、Plugin 等放置规则）未受影响
- [ ] 进化流程、四维度量、反模式等其他章节未受影响
- [ ] 文档行数 < 500 行（允许超过 450 行，但不应膨胀过多）

### 架构验收
- [ ] 新增规则不与现有架构图矛盾
- [ ] 归属判定规则与 binary-analysis agent 和 mobile-analysis agent 的知识库索引一致

## §5 与现有需求文档的关系

- 独立需求，不依赖其他需求文档
- 与 `mobile-analysis-evolve-v1.md` 有关联（本次修改正是为了解决该进化过程中暴露的问题）
