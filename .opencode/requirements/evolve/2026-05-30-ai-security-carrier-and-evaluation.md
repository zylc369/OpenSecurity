# 需求：AI 安全分析 Agent — 载体构造指南 + 真实性评估方法论

## §1 背景与目标

**来源**: 复盘 Ultimate Essay Grader AI 安全挑战（`docs/分析/AI安全/挑战-Ultimate-Essay-Grader.md`），对照 ai-security-analysis Agent 的现有能力进行能力覆盖分析。

**痛点**:

1. **无载体生成能力**（高严重度）: 渐进式攻击需要高质量载体（论文/文章/报告），当前 Agent 完全没有载体构造指导。知识库只说"用高质量载体"，不说"怎么构造"。用户必须自行准备载体材料。

2. **无真实性评估方法论**（高严重度）: "满分 + 真实感"是 LLM 注入类任务的核心挑战（writeup 核心发现："满分容易，真实满分难"），但知识库完全没有覆盖如何评估注入效果的真实性。Agent 不知道怎么判断"LLM 的回复是否看起来像正常评分"。

**预期收益**:
- 减少对话轮次: 改进前需要 2-3 轮请求用户准备载体 + 手动调试真实性 → 改进后 0 轮（Agent 自主构造载体 + 自主评估真实性）
- 提升准确度: 解决"注入成功但报告不真实"的误判问题

**改动范围**: 新增 2 个知识库文件 + Agent prompt 知识库索引增加 2 行

## §2 技术方案

### 2.1 新增文件

| 文件 | 路径 | 定位 |
|------|------|------|
| 载体构造指南 | `$AGENT_DIR/knowledge-base/carrier-construction-guide.md` | 教 Agent 如何为 LLM 注入攻击构造高质量载体 |
| 真实性评估方法论 | `$AGENT_DIR/knowledge-base/payload-effectiveness-evaluation.md` | 教 Agent 如何评估注入效果的真实性 |

### 2.2 修改文件

| 文件 | 改动内容 |
|------|---------|
| `$OPENCODE_ROOT/agents/ai-security-analysis.md` | 知识库索引表（`### AI 安全知识库` 段）增加 2 行 |

### 2.3 不修改的文件

- `llm-attack-methodology.md` — 不修改。载体构造指南引用其中 §3.1（载体选择原则）的结论，不修改其内容
- `prompt-injection-patterns.md` — 不修改
- `ai-security-defense.md` — 不修改
- `llm_sim.py` / `deepseek_client.py` — 不修改。新能力通过知识库（AI 编排指导）而非脚本实现

### 2.4 文件间关系

```
carrier-construction-guide.md（新）
  └── 引用 llm-attack-methodology.md §3.1 的载体选择原则

payload-effectiveness-evaluation.md（新）
  └── 引用 llm-attack-methodology.md §2.3 的结果分析维度
  └── 引用 carrier-construction-guide.md 的载体质量标准
```

## §3 实现规范

### 3.0 总体原则

- 两个文件都遵循知识编写规范（`$SHARED_DIR/knowledge-base/knowledge-writing-guide.md`）
- 写"什么场景、怎么检查、怎么利用"，不写"经验来源"
- 每条知识必须通过质量检查清单（准确性、完整性、一致性、可操作性）
- 知识库文件必须自包含（不依赖主 prompt 上下文即可理解）
- 使用 `$AGENT_DIR` 引用跨文件路径

### 3.1 实施步骤拆分

```
步骤 1. 创建 carrier-construction-guide.md
  - 文件: .opencode/ai-security-analysis/knowledge-base/carrier-construction-guide.md（新建）
  - 预估行数: ~100-130 行
  - 验证点:
    1. 人工通读，确认自包含性（不依赖主 prompt 即可理解）
    2. 确认覆盖以下主题:
       a. 载体质量标准（无注入基线分数阈值、载体长度和结构要求）
       b. 按目标应用类型的构造策略（论文评分、内容审核、对话系统）
       c. 载体验证方法（用模拟器测试无注入基线）
       d. 注入位置选择（载体中最佳注入位置，不影响载体连贯性）
    3. 确认引用路径使用 $AGENT_DIR 变量
  - 依赖: 无

步骤 2. 创建 payload-effectiveness-evaluation.md
  - 文件: .opencode/ai-security-analysis/knowledge-base/payload-effectiveness-evaluation.md（新建）
  - 预估行数: ~100-130 行
  - 验证点:
    1. 人工通读，确认自包含性
    2. 确认覆盖以下主题:
       a. 真实性评估维度（格式完整性、评价与载体质量匹配、改进建议存在性、语气自然度）
       b. 每个维度的具体检查方法（从 LLM 回复中提取和判断）
       c. 常见失败模式（差载体 + 满分 = 不真实、无改进建议的纯赞美等）
       d. 真实性评分卡（简单的评级标准）
    3. 确认引用路径使用 $AGENT_DIR 变量
    4. 确认与 carrier-construction-guide.md 的引用关系正确
  - 依赖: 步骤 1（因为步骤 2 引用步骤 1 的载体质量标准）

步骤 3. 更新 Agent prompt 知识库索引
  - 文件: .opencode/agents/ai-security-analysis.md
  - 预估行数: 新增 2 行
  - 改动内容: 在知识库索引表（`### AI 安全知识库` 段）增加 2 行:
    ```
    | `carrier-construction-guide.md` | 构造注入载体时。高质量载体构造方法、质量标准、验证方法 |
    | `payload-effectiveness-evaluation.md` | 评估注入效果时。真实性评估维度、检查方法、常见失败模式 |
    ```
  - 验证点:
    1. `python -c "compile(open(...).read(), ...)"` 无报错（语法上不出错，因为只改了表格行）
    2. 人工确认新行格式与现有行一致
    3. 人工确认触发条件描述准确
  - 依赖: 步骤 1、2
```

## §4 验收标准

### 功能验收

- [ ] `carrier-construction-guide.md` 存在且内容覆盖 §3.1 步骤 1 验证点中列出的 4 个主题
- [ ] `payload-effectiveness-evaluation.md` 存在且内容覆盖 §3.1 步骤 2 验证点中列出的 4 个主题
- [ ] Agent prompt 知识库索引表包含 2 个新文件的条目
- [ ] 两个新文件的引用路径均使用 `$AGENT_DIR` 变量
- [ ] 两个新文件均通过知识编写规范质量检查清单（§3.1-3.4）

### 回归验收

- [ ] Agent prompt 展开后总行数 < 450 行（当前 377 行，新增 2 行表格行 → 预计 379 行）
- [ ] 现有 3 个知识库文件无改动
- [ ] 现有 2 个脚本无改动

### 架构验收

- [ ] 新文件位于 `$AGENT_DIR/knowledge-base/`（正确的归属位置）
- [ ] 无循环依赖（新文件引用旧文件，旧文件不引用新文件）
- [ ] 无与现有知识库的矛盾或重复

## §5 与现有需求文档的关系

- 独立于 `2026-05-30-ai-security-analysis-agent.md`（Agent 创建需求）。本次是 Agent 创建后的首次能力进化
- 不依赖其他未完成的需求文档
