# 知识管理闭环：让领域 agent 充分使用 searcher 和知识库

## §1 背景与目标

### 来源痛点

searcher 和 memorist 已从 PentAGI 复刻完成，knowledge/events MCP 已实现，但领域 agent 实际上**没有有效使用它们**：

| 检查项 | 结果 |
|--------|------|
| 领域 agent prompt 引导"何时委派 searcher 查知识"？ | ❌ 没有 |
| 领域 agent prompt 引导"何时存储分析结论"？ | ❌ 没有 |
| knowledge 向量库实际数据量 | 16 条（全部是测试数据） |
| coordinator 委派表提到 searcher？ | ❌ 没有 |

**核心问题**：基础设施建好了（library + librarian），但研究员（领域 agent）不知道何时去图书馆、何时把新发现存进图书馆。

### PentAGI 的做法（已学习源码）

PentAGI pentester 的 prompt 里有强制的知识管理协议：

```xml
<memory_protocol>
<guide_search>Use "search_guide" to check for reusable methodologies</guide_search>
<guide_storage>ONLY use "store_guide" when discovering valuable techniques</guide_storage>
<persistence>Store any successful methodologies to build institutional knowledge</persistence>
</memory_protocol>

<when_to_search>
ALWAYS search BEFORE attempting any significant action:
- Before running reconnaissance → Check what was already discovered
- Before exploitation → Find similar successful exploits
- When encountering errors → See how similar errors were resolved
</when_to_search>
```

### 改造目标

1. 创建共享知识管理片段 `knowledge-management.md`，所有领域 agent 引用
2. 5 个领域 agent 的 prompt 加 `{{buwai-rule:knowledge-management}}`
3. coordinator 分发时提醒领域 agent 先查知识

### 设计原则

- **搜索统一走 searcher**：领域 agent 不直接调 knowledge/events MCP 读取工具，通过委派 searcher 查
- **存储领域 agent 直接做**：存储不是搜索，领域 agent 直接调 `store_answer`/`store_guide`/`store_code`（MCP 工具内置匿名化）
- **相信 LLM 的自觉性**：prompt 引导即可，不写死代码自动提取知识

### 预期收益

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 知识库积累 | 0 条实际数据 | 每次 analysis 后自动积累 |
| 知识复用 | 无 | 同类目标复用已有结论 |
| 分析速度 | 每次从零开始 | 有知识可复用时加速 |
| 跨任务记忆 | 无 | knowledge 向量库全局共享 |

---

## §2 技术方案

### 2.1 创建共享片段 `knowledge-management.md`

位置：`.opencode/agents-rules/knowledge-management.md`

内容（精确版，避免模糊表述）：

```markdown
## 知识管理（强制）

### 接到新分析任务的第一步

委派 searcher（Task 工具，subagent_type=searcher），要求"查是否已有同类目标/漏洞/技术的分析记录"。把目标的关键信息传给 searcher（文件类型、架构、框架、漏洞特征等）。
- 查到相关知识 → 复用已有结论，避免重复研究
- 查不到 → 正常分析

### 遇到不熟悉的技术时

委派 searcher 查外部资料（CVE 详情、漏洞利用方案、工具文档）。searcher 有 websearch/webfetch 能力。

### 得出明确分析结论后

**必须**存储知识到向量库（存储时自动匿名化，不需要手动清洗）：
- `mcp__knowledge__store_answer`：存分析结论（漏洞描述 + 利用方法 + 验证结果）。question 用"未来谁会查这条知识、他会怎么问"的角度表述（例如：发现栈溢出后存储时，question 写成 `"Windows x64 栈溢出漏洞的利用方法"`）
- `mcp__knowledge__store_guide`：存可复用的操作步骤/配置方法（如果有）
- `mcp__knowledge__store_code`：存可复用的 PoC/脚本（如果有）
```

### 2.2 5 个领域 agent prompt 加引用

在每个 agent 的"分析执行框架"**之前**插入：

```
{{buwai-rule:knowledge-management}}
```

插入位置（每个 agent 的"分析执行框架"标题前）：

| Agent | 插入行（当前） |
|-------|-------------|
| binary-analysis.md | 第 47 行 `## 分析执行框架（强制）` 之前 |
| mobile-analysis.md | 第 46 行 `## 分析执行框架（强制）` 之前 |
| web-analysis.md | 第 59 行 `## 分析执行框架（强制）` 之前 |
| crypto-analysis.md | 第 36 行 `## 分析执行框架（强制）` 之前 |
| ai-security-analysis.md | 第 40 行 `## 分析执行框架（强制）` 之前 |

### 2.3 coordinator 分发提示

coordinator 的"阶段 1.3 逐个分发"段落，在 Task 工具调用示例的 prompt 里加一句提醒：

```
每个子任务的委派 prompt 里加上："分析前先委派 searcher 查已有知识（subagent_type=searcher），分析结论用 mcp__knowledge__store_answer 存储"
```

### 2.4 不改动的部分

- `searcher.md`：已有详细的 search/store 工具使用指引，不变
- `memorist.md`：不变
- `knowledge/server.py` / `events/server.py`：MCP 工具实现不变
- `security-analysis.ts`：plugin 不变

---

## §3 实现规范

### 改动范围表

| 文件 | 改动类型 | 行数估计 |
|------|---------|---------|
| `.opencode/agents-rules/knowledge-management.md` | 新建共享片段 | ~20 行 |
| `.opencode/agents/binary-analysis.md` | 加 1 行占位符引用 | +1 行 |
| `.opencode/agents/mobile-analysis.md` | 加 1 行占位符引用 | +1 行 |
| `.opencode/agents/web-analysis.md` | 加 1 行占位符引用 | +1 行 |
| `.opencode/agents/crypto-analysis.md` | 加 1 行占位符引用 | +1 行 |
| `.opencode/agents/ai-security-analysis.md` | 加 1 行占位符引用 | +1 行 |
| `.opencode/agents/security-coordinator.md` | 分发提示 | +3 行 |

### §3.1 实施步骤拆分

#### 步骤 1：创建 knowledge-management.md 共享片段

- 文件：新建 `.opencode/agents-rules/knowledge-management.md`
- 改动：写知识管理文案（§2.1 的内容）
- 预估行数：~20 行
- 验证点：文件存在且内容完整
- 依赖：无

#### 步骤 2：5 个领域 agent prompt 加引用

- 文件：binary/mobile/web/crypto/ai-security-analysis.md
- 改动：在"分析执行框架"之前加 `{{buwai-rule:knowledge-management}}`
- 预估行数：5 × 1 行
- 验证点：
  - 每个文件 grep `knowledge-management` 有匹配
  - 占位符在"分析执行框架"之前
- 依赖：步骤 1

#### 步骤 3：coordinator 分发提示

- 文件：security-coordinator.md
- 改动：在分发流程加提醒
- 预估行数：~3 行
- 验证点：grep `searcher` 有匹配
- 依赖：无

#### 步骤 4：验证占位符展开

- 文件：无（启动 OpenCode 验证）
- 验证方式：启动 opencode serve → 发消息触发 binary-analysis → 检查 system prompt 是否含知识管理段落
- 验证点：system prompt 含"知识管理"标题
- 依赖：步骤 1+2

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | knowledge-management.md 存在且内容完整 | 文件存在 |
| F2 | 5 个领域 agent 含 `{{buwai-rule:knowledge-management}}` | grep 匹配 5 处 |
| F3 | coordinator 分发提示提到 searcher | grep 匹配 |
| F4 | 占位符展开后 system prompt 含"知识管理" | opencode serve 验证 |

### 回归验收

| # | 验收项 |
|---|--------|
| R1 | searcher.md 不受影响 |
| R2 | 现有分析执行框架不变（只是前面多了一段知识管理） |
| R3 | 工具清单不变 |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | 知识管理文案是共享片段（单一事实源） |
| A2 | 搜索统一走 searcher（领域 agent 不直接调 search 类 MCP 工具） |
| A3 | 存储领域 agent 直接调（store_answer/store_guide/store_code） |
| A4 | 文案表述精确（"接到新任务的第一步"而非"分析前"） |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-09-searcher-agent.md` | **直接前置**——searcher/memorist 已实现，本需求让领域 agent 充分使用它们 |
| `2026-07-19-knowledge-mcp-align-pentagi.md` | **直接前置**——knowledge MCP 已对齐 PentAGI（4 类别 + 匿名化 + memory 自动写入） |
| `2026-07-19-mcp-infra-separation.md` | 独立——MCP 基础设施职责分离已完成 |
