# 需求文档: security-coordinator 改用内置 Task 工具

## §1 背景与目标

### 背景

当前 `security-coordinator` 通过 Plugin 自造的 `delegate_analysis` 工具调度子 Agent。该工具是 OMO `delegate-task` 的简化版，缺失 UI 集成层（metadata 发布、toast 通知、session 注册），导致：

1. **子 Agent 执行过程对用户完全不可见** — 用户无法点击查看子 Agent 在做什么
2. **稳定性差** — 首次调用直接返回 `父会话已取消当前操作，子任务被终止`
3. **维护成本高** — 自造了约 250 行轮询/会话管理代码，需要跟随 OMO 上游持续同步

### 代码证据

- OpenCode 内置 Task 工具（`vendor/opencode/packages/opencode/src/tool/task.ts`）天然支持 `ctx.metadata()` 发布 sessionId（第 175-178 行），子会话在 UI 中可见可点击
- 内置 Task 工具的 subagent_type 发现逻辑（`registry.ts` 第 302 行）过滤 `mode !== "primary"` 的 Agent
- 当前三个专业 Agent 都是 `mode: primary`，因此不出现在 Task 工具的可用列表中

### 目标

1. 删除 `delegate_analysis` 工具及其全部相关代码
2. 三个专业 Agent 改为 `mode: all`（既可 Tab 直接使用，也可被 Task 工具调度）
3. security-coordinator prompt 重写为使用内置 Task 工具调度子 Agent
4. 用户能看到子 Agent 执行过程（可点击查看）

### 预期收益

- 上下文: 不变
- 轮次: 不变
- 速度: 不变
- **准确度: 子 Agent 执行可见，用户能及时发现和纠正问题**
- **稳定性: 用框架原生能力替代自造轮子**

---

## §2 技术方案

### 2.1 架构影响

```
.opencode/
├── agents/
│   ├── binary-analysis.md           # 修改: mode: primary → mode: all
│   ├── mobile-analysis.md           # 修改: mode: primary → mode: all
│   ├── web-analysis.md              # 修改: mode: primary → mode: all
│   ├── security-coordinator.md      # 重写: 使用 Task 工具替代 delegate_analysis
│   └── security-analysis-evolve.md  # 不改
├── plugins/
│   └── security-analysis.ts         # 修改: 删除 delegate_analysis 及相关代码
└── 其他目录                         # 不改
```

### 2.2 删除范围（security-analysis.ts）

以下代码将从 `security-analysis.ts` 中删除：

| 代码段 | 行范围（约） | 行数 |
|--------|-------------|------|
| `VALID_SUB_AGENTS` 常量 | 488-492 | 5 |
| `buildSubSessionSystem()` 函数 | 494-540 | 47 |
| delegate_analysis 轮询常量和注释 | 542-560 | 19 |
| `SessionMessage` 接口 | 562-565 | 4 |
| `sleep()` 函数 | 567-569 | 3 |
| `fetchSessionMessages()` 函数 | 574-581 | 8 |
| `isSessionComplete()` 函数 | 587-611 | 25 |
| `pollSubSession()` 函数 | 618-695 | 78 |
| `abortSubSession()` 函数 | 700-708 | 9 |
| `fetchSubSessionResult()` 函数 | 713-735 | 23 |
| `delegate_analysis` tool 定义 | 1113-1253 | 141 |
| `tool.execute.after` 中 delegate_analysis 特殊处理 | 1525-1538 | 14 |
| **合计** | | **~376 行** |

同时可清理 `opencodeClient` 类型声明中仅被 `delegate_analysis` 使用的方法（`promptAsync`、`status`、`messages`、`abort`）。但 `promptAsync` 可能还被其他逻辑使用，需逐一确认。

### 2.3 新增范围

无新增文件。`security-coordinator.md` 是重写已有文件。

### 2.4 security-coordinator.md 重写要点

重写后的 prompt 核心变化：

| 之前 | 之后 |
|------|------|
| 通过 `delegate_analysis` 工具分发 | 通过内置 `task` 工具分发 |
| `target_agent` 参数指定 Agent | `subagent_type` 参数指定 Agent |
| 自造的 `task_prompt` 构造 | 标准 `prompt` 参数 |
| 子 Agent 在 `parent_task_dir/subdir_name/` 中工作 | 子 Agent 在内置 Task 工具创建的子会话中工作 |
| 自造轮询等待结果 | 内置 Task 工具同步等待结果 |
| 结果从子会话消息中提取 | Task 工具直接返回结果文本 |
| 需要手动创建子目录 | 仍需创建父任务目录（用于存放报告） |

保留的设计：
- 阶段 0 创建父任务目录（`create_task_dir.py`）
- 子任务按依赖顺序执行
- 结果聚合写入 `summary.md`

### 2.5 Plugin 中 `AGENT_SECURITY_COORDINATOR` 的处理

`security-analysis.ts` 中 `AGENT_SECURITY_COORDINATOR` 常量用于：
- `system.transform` hook 中的环境信息注入
- `chat.message` hook 中的 primaryAgent 设置
- `compacting` hook 中的上下文保留

这些逻辑全部保留，只删除 `delegate_analysis` 工具定义和相关辅助函数。

---

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 修改三个专业 Agent 的 mode**

- 文件: `agents/binary-analysis.md`, `agents/mobile-analysis.md`, `agents/web-analysis.md`
- 改动: frontmatter 中 `mode: primary` → `mode: all`
- 预估行数: 每文件 1 行，共 3 行
- 验证点: 确认三个文件 frontmatter 的 mode 字段已改为 `all`

**步骤 2. 删除 Plugin 中 delegate_analysis 相关代码**

- 文件: `plugins/security-analysis.ts`
- 改动: 删除 §2.2 中列出的所有代码段
  - 常量/函数: `VALID_SUB_AGENTS`, `buildSubSessionSystem`, `POLL_INTERVAL_MS`, `DEFAULT_POLL_TIMEOUT_MS`, `getDelegateTimeoutMs`, `SessionMessage`, `sleep`, `fetchSessionMessages`, `isSessionComplete`, `pollSubSession`, `abortSubSession`, `fetchSubSessionResult`
  - tool 定义: `delegate_analysis: tool({...})` 整个块
  - `tool.execute.after` 中 `if (toolName === "delegate_analysis")` 分支
- 预估行数: ~376 行删除
- 验证点: `node --check security-analysis.ts` 语法检查通过；文件中不再包含 `delegate_analysis` 字符串
- 依赖: 无

**步骤 3. 清理 Plugin 中 opencodeClient 类型声明**

- 文件: `plugins/security-analysis.ts`
- 改动: 检查 `promptAsync`、`status`、`messages`、`abort` 是否还被其他代码使用。如果仅被 `delegate_analysis` 使用则从类型声明中删除
- 预估行数: ~20 行
- 验证点: `node --check security-analysis.ts` 语法检查通过
- 依赖: 步骤 2

**步骤 4. 重写 security-coordinator.md**

- 文件: `agents/security-coordinator.md`
- 改动: 重写整个文件，使用内置 Task 工具替代 `delegate_analysis`
- 预估行数: ~200 行（重写）
- 验证点:
  - 文件 frontmatter 正确（`mode: primary`, `buwai-extension-id: security-coordinator`）
  - prompt 中使用 `task` 工具的 `subagent_type` 参数
  - 可用的 subagent_type 列出: `binary-analysis`, `mobile-analysis`, `web-analysis`
  - 保留阶段 0 的任务目录创建
  - 保留结果聚合逻辑
- 依赖: 步骤 1（Agent mode 改完后 Task 工具才能发现它们）

---

## §4 验收标准

### 功能验收

- [ ] coordinator 通过内置 Task 工具成功调度 `binary-analysis` / `mobile-analysis` / `web-analysis`
- [ ] 子 Agent 执行过程在 UI 中可见（可点击查看）
- [ ] coordinator 能接收子 Agent 返回的结果并做下一步决策
- [ ] 多个子 Agent 可顺序执行（后一个依赖前一个的结果）
- [ ] 子 Agent 的报告仍写入任务目录

### 回归验收

- [ ] 直接 Tab 切换到 `binary-analysis` / `mobile-analysis` / `web-analysis` 仍能正常使用（`mode: all` 不影响 primary 行为）
- [ ] Plugin 其他功能不受影响（`system.transform`、`compacting`、`chat.message`、`tool.execute.before`）
- [ ] `security-analysis-evolve` Agent 不受影响
- [ ] `node --check security-analysis.ts` 语法检查通过

### 架构验收

- [ ] `security-analysis.ts` 中不再包含 `delegate_analysis` 相关代码
- [ ] 三个专业 Agent 的 mode 为 `all`
- [ ] 依赖方向正确：coordinator → Task 工具 → 子 Agent，无循环依赖

---

## §5 与现有需求文档的关系

- 替代 `2026-05-22-security-coordinator.md`（创建 coordinator + delegate_analysis）
- 替代 `2026-05-25-delegate-analysis-async.md`（delegate_analysis 异步支持）
- 替代 `2026-05-22-security-coordinator-verification.md`（coordinator 验证）
- 关联 `2026-05-26-coordinator-stability-and-web-knowledge-align.md`（coordinator 稳定性）— 本次改动直接解决了其中提到的稳定性问题
