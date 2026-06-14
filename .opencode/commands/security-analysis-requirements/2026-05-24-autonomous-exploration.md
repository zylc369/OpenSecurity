# 需求文档: 分析执行中的自主探索规则

## §1 背景与目标

### 背景

用户在使用安全分析 agent（binary-analysis、mobile-analysis、web-analysis）时，AI 经常在执行过程中遇到技术困难后停下来向用户提问，例如：
- "不确定这个函数是不是加密函数，你觉得呢？"
- "工具执行失败了，要重试还是换个方向？"
- "这个漏洞似乎无法利用，你有其他想法吗？"

用户是技术小白，无法提供技术指导。AI 应该自己探索找答案，而不是问用户。

### 目标

在执行纪律中增加"自主探索"规则，明确界定：
1. 什么情况下**禁止问用户**（技术判断、方向选择、工具失败处理）
2. 什么情况下**可以问用户**（只有用户知道的事实信息）
3. 遇到困难时的**自主行为规范**（如何自行探索、切换方向、利用知识库）

### 预期收益

- 轮次: 执行过程中减少 50%+ 的等待用户回复轮次
- 速度: AI 不再中断等待，持续探索直到找到答案
- 准确度: 无负面影响（规则鼓励多方向探索，而非盲目坚持）

### 约束

- 不改变现有的"方案确认"流程（analysis-planning-rules 第 4-5 条保留）
- 不改变现有的"失败快速切换"等已有纪律
- 只增加规则，不修改已有规则

---

## §2 技术方案

### 2.1 改动内容

**改动**: `agents-rules/execution-discipline.md` — 增加"自主探索"纪律行

这是 3 个分析 agent（binary/mobile/web）共享的片段，改一处全局生效。通过 coordinator 调度的子 agent 同样生效——子会话注册到 sessions Map 后，`system.transform` hook 会展开 `{{buwai-rule:execution-discipline}}` 占位符，不需要在 `buildSubSessionSystem` 中重复注入。

### 2.2 规则定义

**可以问用户的问题**（只有用户知道）：
- 目标文件/URL/路径
- 授权信息（token、cookie、账号）
- 用户的需求澄清（"你想要什么类型的分析？"）
- 环境配置（工具路径、设备连接等）

**禁止问用户的问题**（AI 必须自己解决）：
- 技术判断（"这个函数是不是 X？"）
- 方向选择（"要不要换个方向？"）
- 工具失败处理（"失败了怎么办？"）
- 分析结论确认（"这个结果对吗？"）
- 漏洞利用方式（"怎么利用这个漏洞？"）
- 任何可以通过阅读代码、查文档、做实验得出答案的问题

**遇到困难时的自主行为**：
- 读取知识库寻找方法论
- 用工具做实验验证假设
- 按失败模式表切换方向
- 多方向并行尝试
- 记录失败原因避免重复

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 操作 | 预估行数 | 说明 |
|------|------|---------|------|
| `agents-rules/execution-discipline.md` | 修改 | +17 行 | 增加自主探索规则 |

**总改动**: ~17 行，1 个文件

说明：不需要修改 `buildSubSessionSystem`。子会话注册到 sessions Map 后，`system.transform` hook 会展开 agent prompt 中的 `{{buwai-rule:execution-discipline}}` 占位符，自主探索规则自动生效。

### 3.1 实施步骤拆分

**步骤 1. 修改 execution-discipline.md 共享片段**
  - 文件: `agents-rules/execution-discipline.md`
  - 预估行数: +17 行
  - 验证点: 文件内容包含"自主探索"行；包含"可以问"和"禁止问"的清晰定义；3 个 agent 的展开后 prompt 中能看到这条规则
  - 依赖: 无

**步骤 2. 端到端验证**
  - 文件: 所有修改文件
  - 预估行数: 0 行（验证步骤）
  - 验证点:
    - execution-discipline.md 内容正确
    - Plugin 语法通过
    - 现有文件（agent prompt、其他片段）无改动
  - 依赖: 步骤 1

---

## §4 验收标准

### 功能验收

- [ ] `execution-discipline.md` 包含"自主探索"纪律行
- [ ] "自主探索"规则清晰定义了"可以问"和"禁止问"的边界
- [ ] "自主探索"规则描述了遇到困难时的自主行为（读知识库、做实验、切换方向）
- [ ] 子 agent 通过 `{{buwai-rule:execution-discipline}}` 占位符展开自动获得自主探索规则（不需要在 buildSubSessionSystem 中额外注入）

### 回归验收

- [ ] binary-analysis.md 无改动
- [ ] mobile-analysis.md 无改动
- [ ] web-analysis.md 无改动
- [ ] security-coordinator.md 无改动
- [ ] agents-rules/ 下其他片段文件无改动

### 架构验收

- [ ] 规则放在共享片段（agents-rules/），3 个 agent 自动生效
- [ ] 子 agent 通过占位符展开自动获得规则，不需要在 plugin 中重复注入

---

## §5 与现有需求文档的关系

- 独立于所有已有需求文档
- 与 `2026-05-03-agent-prompt-snippets.md`（共享片段机制）一致：规则放在共享片段中，agent 通过 `{{buwai-rule:execution-discipline}}` 引用
- 与 `2026-05-22-security-coordinator.md`（coordinator）互补：子会话也遵守自主探索规则
