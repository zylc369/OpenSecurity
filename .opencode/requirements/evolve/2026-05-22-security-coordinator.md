# 需求文档: 创建 security-coordinator Agent（复合任务编排）

## §1 背景与目标

### 背景

用户在 `docs/需求/需求-解决复合问题.md` 中提出：分析一个 APP 可能同时需要二进制逆向和网络抓包，这是一个跨领域的复合任务。当前架构中每个 Agent 独立运行，无法自动协调多领域分析。

参考 `C:\Codes\oh-my-openagent` 的实现：Sisyphus 作为主编排器，通过 `delegate-task` 工具将任务分发到子 Agent。其核心机制是 OpenCode SDK 的 `client.session.create()` + `client.session.prompt({ agent })` 能力——可以在 Plugin 工具中创建子会话并指定任意已注册 Agent。

### 目标

创建 `security-coordinator` Agent，实现复合安全分析任务的自动编排：

1. 分析用户的复合需求，拆分为子任务
2. 通过 Plugin 工具 `delegate_analysis` 分发到专业 Agent（binary/mobile/web）
3. 子 Agent 在父任务目录的子目录中工作
4. 收集子 Agent 的结构化摘要，汇总为最终报告

### 预期收益

- 轮次: 复合任务从"手动切换 Agent × N + 重新输入上下文"→ "1 次输入 + 自动分发"
- 准确度: Coordinator 理解全局上下文，避免子 Agent 因缺乏上下文而误判
- 速度: 顺序分发避免用户在 Agent 间手动切换的等待

### 约束

- **初版只支持同步顺序执行**（逐个子任务等待完成），不做异步并行
- 子 Agent 返回结构化摘要（≤1000 字），详细报告写磁盘，避免撑爆 Coordinator 上下文
- 子 Agent 的行为与独立运行时保持一致，仅任务目录路径不同

---

## §2 技术方案

### 2.1 架构中的位置

```
.opencode/
├── agents/
│   ├── binary-analysis.md           # 已有
│   ├── mobile-analysis.md           # 已有
│   ├── web-analysis.md              # 已有
│   ├── security-analysis-evolve.md  # 已有
│   └── security-coordinator.md      # ← 新增（Coordinator prompt）
├── agents-rules/                    # 已有（Coordinator 不复用分析片段）
├── plugins/
│   └── security-analysis.ts         # 修改：+delegate_analysis tool + 注册 coordinator
├── binary-analysis/                 # 已有（$SHARED_DIR，不做改动）
├── mobile-analysis/                 # 已有（不做改动）
└── web-analysis/                    # 已有（不做改动）
```

**新增文件**: 仅 `agents/security-coordinator.md`（Agent prompt）

**修改文件**: 仅 `plugins/security-analysis.ts`（+1 tool + 注册常量）

**不改动**: 所有现有 Agent prompt、create_task_dir.py、agents-rules/ 片段

### 2.2 子会话机制

参考 oh-my-openagent 的 `delegate-task` 工具实现。核心 API 调用链：

```
delegate_analysis tool (Plugin tool)
│
├── 1. mkdir: 创建 parent_task_dir/subdir_name 子目录
│
├── 2. client.session.create({ parentID, title, permission, query })
│      → 返回子会话 sessionID
│
├── 3. client.session.prompt({
│        path: { id: subSessionID },
│        body: {
│          agent: "binary-analysis",    ← 指定目标 Agent
│          system: subSessionSystem,    ← 注入环境信息 + 子会话模式指令
│          parts: [{ type: "text", text: taskPrompt }]
│        }
│      })
│      → 同步阻塞，等待子 Agent 完成全部工作
│      → 返回最终 AssistantMessage + Parts
│
└── 4. 提取 Parts 中的文本 → 返回给 Coordinator
```

**关键设计决策**:

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 同步 vs 异步 | 同步（`session.prompt`） | 初版简化；`session.prompt` 阻塞等待完成，不需要 polling |
| 环境注入方式 | `system` 参数 + sessions Map 注册 | 子会话注册到 sessions Map 使 `system.transform` 展开占位符；`system` 参数注入子会话模式指令和环境信息（与 hook 注入冗余但无害） |
| 子 Agent 任务目录 | 父目录/子目录名 | Coordinator 先创建父目录，tool 创建子目录，注入为 $TASK_DIR |
| 权限控制 | 禁止 question 工具 | 子 Agent 在同步模式下运行，提问会阻塞且让用户困惑；通过 `session.create` 的 `permission` 参数禁止 |
| 占位符展开 | 注册到 sessions Map | 所有 agent prompt 使用 `{{buwai-rule:xxx}}` 占位符，必须由 `system.transform` hook 展开；子会话注册后 hook 可正常处理 |

### 2.3 子会话 system 注入内容

`delegate_analysis` tool 在 `session.prompt()` 的 `system` 参数中注入：

```
## 子会话运行模式

你正在以子 Agent 模式运行，由 security-coordinator 编排。

### 关键约束

1. **任务目录**: $TASK_DIR = ${parent_task_dir}/${subdir_name}
   - 此目录已存在，不需要创建
   - 所有中间文件、临时脚本、输出、报告写入此目录
2. **跳过阶段 0 的"创建任务目录"步骤**: 不要调用 create_task_dir.py
   - 环境检测仍需执行: `python3 "$SHARED_DIR/scripts/detect_env.py" --output "$TASK_DIR/env.json"`
   - $BA_PYTHON 初始化仍需执行
3. **结果格式要求**:
   - 详细分析报告写入 $TASK_DIR/report.md
   - 你返回的文本必须是结构化摘要，格式如下:

## 分析摘要
（一句话说明分析结论）

## 关键发现
- 发现 1: ...
- 发现 2: ...

## 报告路径
- 详细报告: $TASK_DIR/report.md
- 中间数据: $TASK_DIR/

## 执行统计
- 耗时: Xm Xs
- 工具调用: X 次

### 环境信息
（由 Plugin buildSubSessionSystem() 函数生成，复用 buildEnvSection() 逻辑:
  - $OPENCODE_ROOT: 配置根目录
  - $AGENT_DIR: 目标 Agent 的脚本目录（通过 getScriptDir(target_agent) 获取）
  - $SHARED_DIR: binary-analysis/（通用共享目录）
  - IDA Pro: config.json 中 ida_path 的值（如已配置；子 Agent 按自身片段规则构造 $IDAT）
  - 编译器/Python 包: 从 env_cache.json 读取
）
```

### 2.4 结果聚合策略

```
子 Agent 执行完成
├── 详细报告 → 磁盘: $TASK_DIR/binary-analysis/report.md
├── 中间数据 → 磁盘: $TASK_DIR/binary-analysis/
└── 返回给 Coordinator → 结构化摘要（≤1000 字）

Coordinator 收到摘要后:
├── 记录关键发现
├── 如需细节 → Read 工具读取 $TASK_DIR/xxx/report.md
└── 全部子任务完成后 → 写入汇总报告
```

### 2.5 Agent Prompt 设计（security-coordinator.md）

| 段落 | 内容 | 行数估计 |
|------|------|---------|
| frontmatter | description, mode: primary, buwai-extension-id: security-coordinator | ~8 |
| 角色 | 安全分析编排器职责 | ~10 |
| 可调用 Agent | 3 个专业 Agent 的能力描述 + 适用场景 | ~15 |
| 决策流程 | 单一 vs 复合判断 + 子任务拆分规则 | ~25 |
| 阶段 0 | 创建父任务目录（调用 create_task_dir.py） | ~15 |
| 阶段 1 | 分析需求 → 拆分子任务 → 确定顺序 → 逐个分发 | ~30 |
| delegate_analysis 使用说明 | 工具参数说明 + task_prompt 构造指引 | ~25 |
| 结果聚合 | 收集摘要 + 可选读取详细报告 + 汇总 | ~15 |
| 输出格式 | Coordinator 专属输出格式 | ~15 |
| 执行纪律 | 失败处理 + 超时 + 质量检查 | ~10 |
| **总计** | | **~183** |

> 展开后行数 ≈ 183 行（不复用 {{buwai-rule:}} 片段，Coordinator 的流程与分析 Agent 不同），远低于 450 行阈值。

### 2.6 Plugin 修改（security-analysis.ts）

#### 2.6.1 新增常量

```typescript
const AGENT_SECURITY_COORDINATOR = "security-coordinator";
// PRIMARY_AGENTS 数组追加 AGENT_SECURITY_COORDINATOR
```

#### 2.6.2 新增 delegate_analysis tool

工具参数:

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| target_agent | string | 是 | binary-analysis / mobile-analysis / web-analysis |
| task_prompt | string | 是 | 详细任务描述（包含子 Agent 需要的所有上下文） |
| parent_task_dir | string | 是 | 父任务目录路径 |
| subdir_name | string | 是 | 子目录名（如 binary-analysis） |
| description | string | 否 | 简短任务描述（3-5 字） |

工具流程:
1. 校验 target_agent 是否合法
2. 创建子目录 `mkdir -p parent_task_dir/subdir_name`
3. 构造子会话 system 内容（环境信息 + 子会话模式指令）
4. 创建子会话 `client.session.create({ parentID, title, permission })`（permission 禁止 question 工具）
5. 注册子会话到 sessions Map（使 `system.transform` 展开占位符和注入环境信息）
6. 发送任务 `client.session.prompt({ agent, system, parts })`（同步阻塞）
7. 从响应 Parts 提取文本
8. 清理子会话的 sessions Map 条目
9. 返回文本给 Coordinator

#### 2.6.3 新增 coordinator 压缩保留

在 `getCompactionContext` 中增加 coordinator 分支，保留:
- 已完成的子任务摘要
- 待执行的子任务列表
- 父任务目录路径

### 2.7 归属判定

- `security-coordinator.md` → `agents/`（Agent prompt）
- `delegate_analysis` tool → `plugins/security-analysis.ts`（Plugin 工具）
- Coordinator 不需要专属目录（无脚本、无知识库）
- 所有文件在现有架构中，不散落到 .opencode/ 之外

---

## §3 实现规范

### 3.0 改动范围表

| 文件 | 操作 | 预估行数 | 说明 |
|------|------|---------|------|
| `agents/security-coordinator.md` | 新增 | ~183 | Coordinator Agent prompt |
| `plugins/security-analysis.ts` | 修改 | ~240 行改动 | +delegate_analysis tool（含 buildSubSessionSystem）+ 注册 coordinator |

**总改动**: ~423 行，2 个文件

### 3.1 实施步骤拆分

**步骤 1. 创建 security-coordinator Agent prompt**
  - 文件: `agents/security-coordinator.md`
  - 预估行数: ~183 行
  - 验证点: frontmatter 包含 `mode: primary` 和 `buwai-extension-id: security-coordinator`；包含角色、可调用 Agent 表、决策流程、阶段 0/1、delegate_analysis 使用说明、结果聚合、输出格式；展开后 < 450 行
  - 依赖: 无

**步骤 2. Plugin: 注册 security-coordinator 常量**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~5 行改动
  - 验证点: `node --check` 语法通过；`AGENT_SECURITY_COORDINATOR` 常量存在；`PRIMARY_AGENTS` 包含 `"security-coordinator"`
  - 依赖: 无

**步骤 3. Plugin: 实现 buildSubSessionSystem 函数**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~60 行
  - 验证点: `node --check` 语法通过；函数接受 targetAgent、subTaskDir、parentTaskDir 参数（camelCase）；输出包含环境信息 + 子会话模式指令 + 结果格式要求
  - 依赖: 无

**步骤 4. Plugin: 实现 delegate_analysis tool**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~120 行
  - 验证点: `node --check` 语法通过；tool 注册在 `tool` hook 中；参数校验正确（target_agent 必须是 3 个合法值之一）；创建子会话并发送 prompt；从响应提取文本；错误处理完善（session.create 失败、session.prompt 失败均返回错误文本）
  - 依赖: 步骤 3

**步骤 5. Plugin: 新增 coordinator 压缩保留**
  - 文件: `plugins/security-analysis.ts`
  - 预估行数: ~10 行改动
  - 验证点: `node --check` 语法通过；`getCompactionContext` 包含 security-coordinator 分支
  - 依赖: 步骤 2

**步骤 6. 端到端验证**
  - 文件: 所有新增/修改文件
  - 预估行数: 0 行（验证步骤）
  - 验证点:
    - agent prompt 展开后 < 450 行
    - Plugin `node --check` 通过
    - `PRIMARY_AGENTS` 包含全部 5 个 agent
    - `tool` hook 包含 `delegate_analysis`
    - `getCompactionContext` 包含 coordinator 分支
  - 依赖: 步骤 1-5 全部完成

---

## §4 验收标准

### 功能验收

- [ ] `security-coordinator.md` frontmatter 包含 `mode: primary` 和 `buwai-extension-id: security-coordinator`
- [ ] Agent prompt 包含: 角色、可调用 Agent 表、决策流程、阶段 0/1、delegate_analysis 使用说明、结果聚合、输出格式
- [ ] Coordinator 的阶段 0 调用 `$SHARED_DIR/scripts/create_task_dir.py` 创建父任务目录
- [ ] `delegate_analysis` tool 接受 4 个参数（target_agent, task_prompt, parent_task_dir, subdir_name）
- [ ] `delegate_analysis` 校验 target_agent 为合法值（binary-analysis / mobile-analysis / web-analysis）
- [ ] `delegate_analysis` 创建子会话时指定 `parentID` 为当前 sessionID
- [ ] `delegate_analysis` 通过 `system` 参数注入子会话模式指令（含 $TASK_DIR 覆盖、跳过任务目录创建、结果格式要求）
- [ ] `delegate_analysis` 通过 `system` 参数注入目标 Agent 的环境信息（$OPENCODE_ROOT, $AGENT_DIR, $SHARED_DIR 等）
- [ ] `getCompactionContext` 包含 security-coordinator 分支（保留已完成的子任务摘要 + 待执行子任务列表）

### 回归验收

- [ ] binary-analysis.md 无任何改动
- [ ] mobile-analysis.md 无任何改动
- [ ] web-analysis.md 无任何改动
- [ ] security-analysis-evolve.md 无任何改动
- [ ] create_task_dir.py 无任何改动
- [ ] agents-rules/ 下所有片段文件无任何改动
- [ ] Plugin 对现有 3 个分析 Agent 的行为不变（`PRIMARY_AGENTS` 扩展不影响已有逻辑；`system.transform` 对已注册 agent 的行为不变）

### 架构验收

- [ ] Coordinator 不引入对 mobile-analysis/ 或 web-analysis/ 的反向依赖
- [ ] `delegate_analysis` tool 在 Plugin 层实现，不在 Agent 层
- [ ] 子会话通过 OpenCode SDK API 创建，不绕过 OpenCode 的 session 管理
- [ ] 所有路径使用 $OPENCODE_ROOT 变量，不硬编码绝对路径
- [ ] Agent prompt 展开后 < 450 行

---

## §5 与现有需求文档的关系

- 本次需求独立于所有已有需求文档
- 不依赖任何未完成的进化任务
- 不改动现有 Agent prompt 和 create_task_dir.py，回归风险极低
- 与 `2026-05-03-agent-prompt-snippets.md`（共享片段机制）互补：Coordinator 不复用分析 Agent 的片段（流程差异大），但复用 Plugin 的环境注入能力
