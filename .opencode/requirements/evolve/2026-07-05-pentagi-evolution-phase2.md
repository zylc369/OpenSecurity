# PentAGI 进化 — 阶段 2：完整多 Agent 协作栈

## §1 背景与目标

### 1.1 来源

阶段 1 完成了基础进化（detach 模式、授权框架、多 agent 协作规则、渗透工具检测、Sploitus 集成、浏览器自动化服务）。阶段 2 解决多 agent 协作的**基础设施缺失**——当前 agent 之间只能通过 Task 工具传递文本，无法共享记忆、保持持久状态、或自动避免走错方向。

### 1.2 核心约束（不可变更）

> **OpenSecurity 面向真实安全分析场景，不是 CTF 工具。** CTF 只是训练和验证 agent 能力的手段。所有决策必须以"真实场景下是否必要"为标尺。

### 1.3 阶段 2 的 7 项改动概览

| # | 能力 | 类型 | 解决的问题 |
|---|------|------|-----------|
| 1 | Embedding 基础设施 | 新脚本 | vector store 的文本向量化基础 |
| 2 | Vector store（sqlite-vec） | 新脚本 + 新规则 | 子 agent 之间的知识共享 |
| 3 | Graphiti 时序图谱 | `.opencode/tools/Graphiti/` + Plugin 生命周期管理 | 长任务事件不丢失 + 实体关系查询 |
| 4 | 持久化子 agent | 新脚本 + Plugin 改动 | 多轮迭代不浪费 token |
| 5 | 条件触发的 Adviser | Plugin 改动 | 避免走错反而省 token |
| 6 | 进程清理（信号处理器） | Plugin 改动 | opencode 退出时自动 kill 子进程 |
| 7 | 工种 Agent 架构 | 新 agent .md + 领域 agent 改 + Plugin 改 | 6 工种独立 agent + 三层 Task 嵌套 + 领域 agent 互相委派 |

### 1.4 后续阶段

| 阶段 | 内容 |
|------|------|
| 阶段 3 | Docker 沙箱隔离 |

### 1.5 不做的事项

同阶段 1（Langfuse / OpenTelemetry / OAuth / GraphQL / React / coordinator 进化）。

---

## §2 技术方案

### 2.1 Embedding 基础设施

**问题**：vector store 需要将文本转为向量进行语义搜索，当前没有 embedding 能力。

**方案**：新增 `embedding_client.py` 脚本，调用智谱 embedding-3 API。

**注意**：Graphiti 自己管理 embedding（初始化时配置 embedder），不需要 embedding_client.py。embedding_client.py 只给 vector_store 用。

**设计**：
- 输入：文本字符串
- 输出：float 数组（1024 维）
- API：智谱 `https://open.bigmodel.cn/api/paas/v4/embeddings`，模型 `embedding-3`
- API key：从环境变量 `ZHIPU_API_KEY` 读取（用户配置）
- 缓存：同一文本的 embedding 缓存到 `$TASK_DIR/embedding_cache.json`（无 $TASK_DIR 时 fallback 到系统临时目录）
- 批量：支持一次 embedding 多段文本（减少 API 调用）

**DeepSeek 没有 embedding API**（已确认官方文档），所以用智谱。

### 2.2 Vector store（sqlite-vec）

**问题**：子 agent 之间是知识孤岛。binary-analysis 试了 5 种方法，crypto-analysis 接手时看不到探索细节，可能重复探索。

**方案**：基于 sqlite + sqlite-vec 的轻量向量存储。

**设计**：
- 新增 `vector_store.py` 脚本：
  - `store(text, metadata, type)` → embedding → 存入 sqlite-vec（type 区分 guide/code/answer 等）
  - `search(query_text, limit, type)` → embedding → 余弦相似度搜索 → 返回匹配结果
- 数据库文件：`$TASK_DIR/vectors.db`（每个任务独立）
- agent 通过 bash 调用：`$PYTHON_CMD vector_store.py store --text "..." --type guide`
- agent 通过 bash 调用：`$PYTHON_CMD vector_store.py search --query "..." --limit 5`

**更新 agents-rules/sub-agent-orchestration.md**：
- memorist 工种改为用 vector_store 而非纯知识库文件
- searcher/pentester/coder 完成后可选存入 vector store

### 2.3 Graphiti 时序图谱

**问题**：长任务（几小时）经历多次上下文压缩，早期发现丢失。无法查询"过去 N 小时的事件"和"实体关系链"。

**方案**：用 Graphiti Python 库（`graphiti-core`）直接集成。Graphiti 是 OpenSecurity 系统的一部分，不是外部可选服务。

**为什么用 Python 库而非 HTTP 服务**：
- Graphiti 本身就是 Python 框架（`pip install graphiti-core`，28.4k stars 开源项目）
- PentAGI 用 HTTP 服务模式是因为它是 Go 项目——Go 不能直接调 Python 库
- OpenSecurity 是 Python 项目——直接用 Python API，零损失，不需要独立 Graphiti 服务
- Graphiti 自己管理 embedding（初始化时配置 embedder）

**代码位置**：`.opencode/tools/Graphiti/`

```
.opencode/tools/Graphiti/
├── graphiti_manager.py    # 生命周期管理（init/close/health）
├── graphiti_tool.py       # 命令行工具（agent 通过 bash 调用）
└── README.md
```

**生命周期管理**：
- Plugin 启动时调用 `graphiti_manager.py init`（连接 Neo4j + 初始化 Graphiti 实例 + 配置 LLM/embedder）
- Plugin 退出时调用 `graphiti_manager.py close`（关闭 Neo4j 连接）
- Graphiti 是嵌入式 Python 库——不是独立进程，不需要 detach 模式

**graphiti_manager.py 设计**：
- 配置读取：`os.environ.get` 带默认值（NEO4J_URL=`bolt://localhost:17687`、NEO4J_USER=`opensecurity`、NEO4J_PASSWORD=`opensecurity_pwd`），用户可在 .ai_env 覆盖
- `init` → 检测 Neo4j 是否运行（`neo4j status`），没运行则自动 `neo4j start` + 等待就绪 → 连接 Neo4j + 初始化 Graphiti（配置 LLM provider 和 embedder）+ 保存实例到全局。**输出 JSON `{"url": "bolt://localhost:17687"}` 到 stdout**（供 Plugin 读取实际 URL——端口可能因冲突自动调整）。失败时退出码非零（供 Plugin reportErrorAndAbort 判断）
- `close` → 关闭 Graphiti driver 连接（不 stop Neo4j，让它继续跑供下次使用）
- `health` → 检查 Graphiti + Neo4j 是否可用

**graphiti_tool.py 设计**（agent 通过 bash 调用）：
- `add --name "..." --content "..." --source "..."` → 添加事件到图谱
- `search --query "..." --num-results 10` → 混合搜索（语义 + 关键词 + 图遍历）
- `search-recent --query "..." --hours 6` → 时序窗口搜索
- 内部用 asyncio.run() 执行 Graphiti 异步 API

**Graphiti 的 LLM/embedder 配置**：
- LLM：可以用 OpenAI-compatible 端点接智谱/DeepSeek/Ollama
- Embedder：同上
- 从环境变量读取配置（`GRAPHITI_LLM_MODEL`、`GRAPHITI_LLM_BASE_URL` 等）

**detect_env.py 检测**：
- `graphiti-core` Python 包 → PYTHON_PACKAGES（`agents=["all"]`，所有 agent 都需要）
- Neo4j 连接 → 环境变量配置（NEO4J_URL/NEO4J_USER/NEO4J_PASSWORD，在 .ai_env 配置）
- 不检测 GRAPHITI_URL（没有独立 Graphiti 服务）

**更新 agents-rules/sub-agent-orchestration.md**：
- memorist 工种增加 Graphiti 查询能力

### 2.4 持久化子 agent

**问题**：Task 工具创建一次性子 agent——改代码要新建子 agent、重建上下文，token 爆炸。

**方案**：用 OpenCode 的 session API 实现持久化子 agent。

**设计**：
- 新增 `sub_agent_manager.py` 脚本：
  - `create(role, prompt)` → 用 ai-dialogue.py 的 `create` 创建子 session → 返回 session_id
  - `send(session_id, message)` → 向已有 session 发消息（复用上下文）
  - `list()` → 列出活跃子 agent
  - `delete(session_id)` → 清理子 agent
- 注册表：`$TASK_DIR/sub_agents.json`（记录 session_id + role + status）
- agent 通过 bash 调用 sub_agent_manager

**更新 agents-rules/sub-agent-orchestration.md**：
- 委派策略改为"优先复用已有子 agent，不存在时新建"

### 2.5 条件触发的 Adviser

**问题**：agent 可能在错误方向上浪费大量 token。PentAGI 的 Adviser 在每次工具调用后追加分析——成本太高。

**方案**：条件触发的 Adviser——仅在特定条件下调用外部 LLM 给建议。

**触发条件**（在 Plugin 的 `tool.execute.after` 钩子检测）：
- 同一方向连续失败 2 次（loop-control 已检测）
- 工具输出超过 5000 字符（结果复杂，需要二次分析）
- 任务执行超过 20 步（可能走偏）

**设计**：
- 触发时调用 ai-dialogue.py 的 `chat` 子命令，prompt 包含当前上下文摘要
- 返回建议追加到 agent 的下一轮上下文
- 用 debugLog 记录每次触发

### 2.6 进程清理（信号处理器）

**问题**：opencode 退出时 detach 进程不会自动清理（setsid 脱离了进程树）。

**方案**：基于调研文档（`docs/进化/进化-opencode退出时机清理子进程调研.md`），注册信号处理器。

**设计**：
- 新增 `plugins/lib/process-registry.ts`：
  - `registerProcess(pid, name)` → 注册到 PID 注册表
  - `killAll()` → SIGTERM 所有注册的进程，超时后 SIGKILL
- Plugin 注册信号处理器：
  - `process.on("SIGINT")` / `process.on("SIGTERM")` → 异步 cleanup（killAll + 6 秒超时）
  - `process.on("exit")` → 同步兜底（process.kill SIGKILL）
- `tool.execute.before` 钩子检测后台命令的 PID（从 `echo $! > pid` 文件读取）→ 注册到 process-registry
- 与现有 `timeline.ts` 的 `process.on("exit")` 合并到统一的 cleanup 模块

### 2.7 工种 Agent 架构

**问题**：当前"工种"（searcher/pentester/coder/adviser/memorist/installer）只是 `agents-rules/sub-agent-orchestration.md` 里的 prompt 模板，不是独立的 agent。这导致：
- 工种没有独立的 model 配置（searcher 应该用便宜模型，coder 用强模型）
- 工种没有独立的工具集（adviser 应该无工具，pentester 有终端工具）
- LLM 调 Task 时不传 `subagent_type`，子 session 的 agentName 可能是 `general` → Plugin 的现有 `requireSecurityAgent` 过滤掉 → 环境变量不注入

**方案**：为 6 个工种创建独立 agent .md 文件，让领域 agent 能创建三层 Task 嵌套。

#### 架构总览

```
用户直接选领域 agent（根 session，天然有 task 权限）
├── 跨领域委派：Task(binary-analysis/crypto-analysis/...)
│   └── 被委派的领域 agent（子 session，有 task:allow → 可继续委派）
│       └── 领域内工种：Task(searcher/pentester/coder/adviser/memorist/installer)
└── 领域内工种：Task(searcher/pentester/coder/...)
    └── 工种（叶子节点，无 task 权限，不能递归）
```

- 用户直接选领域 agent 开始（不需要 coordinator 作为必须入口）
- 领域 agent 之间可跨领域委派（web-analysis → Task(binary-analysis)）
- 领域 agent 创建工种子 session（binary-analysis → Task(searcher)）
- 工种是叶子节点，不能再创建子 session（opencode 原生权限阻止）

#### 6 个工种 agent .md 文件

每个工种 `.opencode/agents/<name>.md`：

| 工种 | model 策略 | mode | 工具能力 |
|------|-----------|------|---------|
| searcher | 便宜模型（快速搜索） | subagent + hidden | browser + search 脚本 |
| pentester | 强模型（攻击决策） | subagent + hidden | terminal + browser |
| coder | 强模型（代码质量） | subagent + hidden | terminal + file |
| adviser | 强模型（策略分析） | subagent + hidden | 无工具（纯文本咨询） |
| memorist | 便宜模型（检索任务） | subagent + hidden | file + graphiti/vector_store |
| installer | 便宜模型（环境配置） | subagent + hidden | terminal + file |

每个工种的 frontmatter：
- `mode: subagent`（不在 @ 菜单显示，只能被 Task 调用）
- `hidden: true`
- **不加 `permission: { task: { "*": "allow" } }`** → 工种永远是叶子节点
- system prompt 包含工种角色定义 + vector store / Graphiti 使用规则

#### 领域 agent 加 task:allow

5 个领域 agent（binary-analysis / web-analysis / mobile-analysis / ai-security-analysis / crypto-analysis）的 frontmatter 加：

```yaml
permission:
  task:
    "*": allow
```

这让领域 agent 作为子 session 时不会被注入 `task: deny`，可以继续创建工种子 session。

> **注意**：`canTask` 判断用 `rule.permission === "task"` 精确匹配（`subagent-permissions.ts:18`），`*: allow` 不算数。必须显式写 `task: allow`。

#### Plugin 改造

1. **新增 `WORKER_AGENTS` map**（`constants.ts`）：独立于 `SECURITY_AGENTS`，key 是工种名，value 是配置对象（含 compactionContext 等字段）

2. **`requireSecurityAgent` 改为 `requireAgent`**（`session-manager.ts`）：同时匹配 `SECURITY_AGENTS` 和 `WORKER_AGENTS`，返回值标识 agent 类型（security / worker）

3. **各 hook 适配**：
   - `shell.env`：工种通过过滤 → 正常注入环境变量（$AGENT_DIR 因 `getScriptDir` 返回 undefined 而不注入——工种没有自己的目录，用 $SHARED_DIR）
   - `compacting`：工种用 `WORKER_AGENTS[name].compactionContext`（不混入 `getCompactionContext` 的领域 agent 逻辑）
   - `system.transform`：工种通过过滤 → 正常注入环境信息
   - `tool.execute`：工种通过过滤 → 正常记录 timeline

4. **`getTaskDir` 父链回溯**（`shell.env` + `compacting`）：子 session 的 `getTaskDir(sessionID)` 返回 null 时，沿 `parentSessionID` 链回溯查父 session 的 taskDir，确保工种子 session 能拿到 `$TASK_DIR`

---

## §3 实施规范

### 改动范围表

| 文件 | 改动类型 | 步骤 |
|------|---------|------|
| `binary-analysis/scripts/embedding_client.py` | 新建 | 步骤 1 |
| `binary-analysis/scripts/vector_store.py` | 新建 | 步骤 2 |
| `.opencode/tools/Graphiti/graphiti_manager.py` | 新建 | 步骤 3 |
| `.opencode/tools/Graphiti/graphiti_tool.py` | 新建 | 步骤 3 |
| `.opencode/tools/Graphiti/README.md` | 新建 | 步骤 3 |
| `binary-analysis/scripts/sub_agent_manager.py` | 新建 | 步骤 4 |
| `binary-analysis/scripts/detect_env.py` | 修改（加 graphiti-core/sqlite-vec 包 + agents=["all"] 统一） | 步骤 5 |
| `binary-analysis/scripts/registry.json` | 修改（注册新脚本） | 步骤 1-4 |
| `plugins/lib/process-registry.ts` | 新建 | 步骤 6 |
| `plugins/security-analysis.ts` | 修改（Graphiti 生命周期 + 信号处理器 + Adviser + PID 注册 + WORKER_AGENTS + requireAgent + getTaskDir 回溯） | 步骤 7-9、12 |
| `plugins/lib/constants.ts` | 修改（新增 WORKER_AGENTS map） | 步骤 12 |
| `plugins/lib/session-manager.ts` | 修改（requireSecurityAgent → requireAgent） | 步骤 12 |
| `agents/searcher.md` | 新建 | 步骤 10 |
| `agents/pentester.md` | 新建 | 步骤 10 |
| `agents/coder.md` | 新建 | 步骤 10 |
| `agents/adviser.md` | 新建 | 步骤 10 |
| `agents/memorist.md` | 新建 | 步骤 10 |
| `agents/installer.md` | 新建 | 步骤 10 |
| `agents/binary-analysis.md` | 修改（frontmatter 加 task:allow） | 步骤 11 |
| `agents/web-analysis.md` | 修改（frontmatter 加 task:allow） | 步骤 11 |
| `agents/mobile-analysis.md` | 修改（frontmatter 加 task:allow） | 步骤 11 |
| `agents/ai-security-analysis.md` | 修改（frontmatter 加 task:allow） | 步骤 11 |
| `agents/crypto-analysis.md` | 修改（frontmatter 加 task:allow） | 步骤 11 |
| `agents-rules/sub-agent-orchestration.md` | 修改（防递归约束 + 工种 Task 调用格式规范 + vector store / Graphiti 使用指引） | 步骤 13 |
| `agents-rules/cross-agent-delegation.md` | 修改（委派策略加 vector store / Graphiti 使用说明） | 步骤 13 |
| `test/embedding_client/` | 新建（单元测试） | 步骤 14 |
| `test/vector_store/` | 新建（单元测试 + 集成测试） | 步骤 14 |
| `test/graphiti_tool/` | 新建（单元测试） | 步骤 14 |
| `test/sub_agent_manager/` | 新建（单元测试） | 步骤 14 |

### 编码规则

1. 所有新脚本用 importlib 加载方式（与阶段 1 一致）
2. API key 从环境变量读取，不硬编码
3. 进程清理代码必须充分打日志（规则 9）
4. 信号处理器里的同步操作只能用 `process.kill`（不能 await）

---

## §3.1 实施步骤拆分

### 步骤 1. 新增 embedding_client.py

- **文件**: `binary-analysis/scripts/embedding_client.py`（新建）
- **预估行数**: ~80 行
- **改动内容**:
  - 调用智谱 embedding-3 API
  - `embed(text)` → 返回向量
  - `embed_batch(texts)` → 批量 embedding
  - 缓存到 `$TASK_DIR/embedding_cache.json`
  - API key 从 `ZHIPU_API_KEY` 环境变量读取
  - 命令行入口：`--text "..."` / `--batch file.json` / `--output vectors.json`
- **验证点**:
  - 语法检查通过
  - `--help` 显示用法
  - 无 API key 时报错（不崩溃）
  - 有 API key 时返回 1024 维向量
  - `registry.json` 有 `embedding_client` 条目
- **依赖**: 无

### 步骤 2. 新增 vector_store.py

- **文件**: `binary-analysis/scripts/vector_store.py`（新建）
- **预估行数**: ~120 行
- **改动内容**:
  - 基于 sqlite + sqlite-vec
  - `store(text, metadata, type)` → embedding → 存入
  - `search(query, limit, type)` → embedding → 余弦相似度搜索
  - 数据库文件：`$TASK_DIR/vectors.db`
  - 命令行入口：`store --text "..." --type guide` / `search --query "..." --limit 5`
- **验证点**:
  - 语法检查通过
  - store + search 端到端测试（存入文本 → 搜索 → 返回匹配）
  - `registry.json` 有 `vector_store` 条目
- **依赖**: 步骤 1（embedding_client）

### 步骤 3. 新增 .opencode/tools/Graphiti/ 目录

- **文件**: `.opencode/tools/Graphiti/graphiti_manager.py` + `graphiti_tool.py` + `README.md`（新建）
- **预估行数**: graphiti_manager.py ~100 行 + graphiti_tool.py ~80 行 + README ~30 行
- **改动内容**:
  - graphiti_manager.py：
    - 配置读取：`NEO4J_URL = os.environ.get('NEO4J_URL', 'bolt://localhost:17687')`，USER/PASSWORD 同理带默认值（`opensecurity` / `opensecurity_pwd`）
    - `init` 流程：
      1. `subprocess.run(['neo4j', 'status'])` 检测是否在运行
      2. 没运行 → `subprocess.run(['neo4j', 'start'])` 自动拉起 + 等待就绪（轮询端口或重试连接，最多 10 秒）
      3. 连接 Neo4j + 初始化 Graphiti（配置 LLM/embedder）+ 保存实例
      4. 退出码非零 → Plugin 的 checkEnvironment 调 reportErrorAndAbort
    - `close` → 关闭 Graphiti driver（不 stop Neo4j，让它继续跑供下次使用）
    - `health` → 检查 Graphiti + Neo4j 可用性
  - graphiti_tool.py（agent 通过 bash 调用）：
    - `add --name "..." --content "..." --source "..."` → 添加事件
    - `search --query "..." --num-results 10` → 混合搜索
    - `search-recent --query "..." --hours 6` → 时序搜索
    - 内部用 asyncio.run() 执行 Graphiti 异步 API
    - **注意 asyncio 事件循环**：graphiti_manager.py 的 init 在一个事件循环里创建 Graphiti 实例，graphiti_tool.py 的每次调用用 asyncio.run() 创建新的事件循环——Graphiti 实例可能不支持跨事件循环使用。解决方案：graphiti_tool.py 每次调用时在同一个 asyncio.run() 内完成 init（如果未初始化）+ 操作，或用线程内持续运行的事件循环
  - README.md：使用说明 + 配置要求
- **验证点**:
  - 语法检查通过
  - `init` 流程正确：Neo4j 未运行时自动 `neo4j start` + 等待就绪 → 连接成功
  - Neo4j 已运行时 `init` 跳过启动直接连接
  - `init` 失败时退出码非零（供 Plugin 的 reportErrorAndAbort 判断）
  - `init` → `add` → `search` 端到端测试
  - `registry.json` 有 `graphiti_tool` 条目
- **依赖**: 无（graphiti-core Python 包由 detect_env 检测安装）

### 步骤 4. 新增 sub_agent_manager.py

- **文件**: `binary-analysis/scripts/sub_agent_manager.py`（新建）
- **预估行数**: ~100 行
- **改动内容**:
  - 基于 ai-dialogue.py 的 session API
  - `create(role, prompt)` → 创建子 session → 注册到 sub_agents.json
  - `send(session_id, message)` → 向已有 session 发消息
  - `list()` → 列出活跃子 agent
  - `delete(session_id)` → 清理
  - 命令行入口：`create --role searcher --prompt "..."` / `send --session abc --msg "..."` / `list` / `delete --session abc`
- **验证点**:
  - 语法检查通过
  - create → list → send → delete 端到端测试
  - sub_agents.json 正确更新
  - `registry.json` 有 `sub_agent_manager` 条目
- **依赖**: 无（依赖 ai-dialogue.py 已有）

### 步骤 5. 扩充 detect_env.py

- **文件**: `binary-analysis/scripts/detect_env.py`（修改）
- **预估行数**: ~40 行新增/修改
- **改动内容**:
  - PYTHON_PACKAGES 加 `graphiti-core`（`agents=["all"]`，所有 agent 都需要，多 agent 协作基础组件）
  - PYTHON_PACKAGES 加 `sqlite-vec`（`agents=["all"]`，同上）
  - **统一 agents 逻辑**：将所有 `agents=[]`（空列表=所有 agent）改为 `agents=["all"]`，`_agent_matches` 函数加 `"all"` 判断，统一语义
  - 不检测 GRAPHITI_URL（没有独立 Graphiti 服务）
  - **不检测 Neo4j**：Neo4j 是 Graphiti 的硬依赖，由 Plugin 的 checkEnvironment 检测（`neo4j --version`），不归 detect_env 管
  - **Neo4j 配置不放 .ai_env**：连接配置（NEO4J_URL/NEO4J_USER/NEO4J_PASSWORD）是 Python 脚本层的事，graphiti_manager.py / graphiti_tool.py 内部用 `os.environ.get` 带默认值（`bolt://localhost:17687` / `opensecurity` / `opensecurity_pwd`），用户想改时在 .ai_env 里加对应变量覆盖即可（可选）
- **验证点**:
  - 语法检查通过
  - `--check-preinstall all` 检测到 graphiti-core 和 sqlite-vec（已安装时）或提示安装（未安装时）
  - `--check-preinstall` 不因缺少 Neo4j 配置报错（required=False）
  - `agents=["all"]` 统一后所有 agent 都检测到这两个包
- **依赖**: 无

### 步骤 6. 新增 plugins/lib/process-registry.ts

- **文件**: `plugins/lib/process-registry.ts`（新建）
- **预估行数**: ~80 行
- **改动内容**:
  - `registerProcess(pid, name)` → 注册 PID
  - `unregisterProcess(pid)` → 注销 PID
  - `killAll()` → SIGTERM 所有注册进程 → 3 秒超时 → SIGKILL
  - `killAllSync()` → 同步 SIGKILL（process.on("exit") 用）
  - 用 `descendants(pid)` 获取子孙进程（参考 opencode MCP kill 逻辑）
- **验证点**:
  - 注册 + killAll 测试（注册假 PID → killAll 不崩溃）
  - `node --check` 语法通过
- **依赖**: 无

### 步骤 7. 修改 Plugin — Graphiti 生命周期管理

- **文件**: `plugins/security-analysis.ts`（修改）
- **预估行数**: ~50 行
- **改动内容**:
  - **checkEnvironment 增加 Neo4j 硬依赖检测**：
    - `spawnSync('neo4j', ['--version'])` 检测是否安装
    - 失败 → `reportErrorAndAbort("Neo4j 未安装，请运行 brew install neo4j")`
    - 成功 → 继续（Neo4j 是否在运行由 graphiti_manager.py init 内部自动拉起，Plugin 不管）
  - Plugin 初始化时调 `$PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_manager.py init`
    - 读取 stdout 的 JSON `{"url": "bolt://localhost:17687"}`，保存到 sessionData 或全局变量（graphiti_tool.py 从同一配置读 URL，不需要 Plugin 传递）
    - init 退出码非零 → `reportErrorAndAbort("Graphiti 初始化失败: <stderr 内容>")`
    - init 成功 → 用 debugLog 记录（含实际 URL）
  - Plugin 退出时的 Graphiti close 合并到步骤 8 的信号处理器（统一 cleanup 路径）
  - 用 debugLog 记录每个关键节点（neo4j 检测结果、init 调用、init 结果）
- **验证点**:
  - 语法检查通过
  - `neo4j --version` 检测正确（neo4j 在 PATH 里时通过，不在时报错 abort）
  - Neo4j 可用时 init 成功（debugLog 记录）
  - Neo4j 不可用时 init 失败 → reportErrorAndAbort 触发（debugLog 记录错误信息）
- **依赖**: 步骤 3

### 步骤 8. 修改 Plugin — 信号处理器 + PID 注册

- **文件**: `plugins/security-analysis.ts`（修改）
- **预估行数**: ~60 行
- **改动内容**:
  - import process-registry
  - 注册 SIGINT/SIGTERM/beforeExit/exit 信号处理器
  - SIGINT/SIGTERM: 调 Graphiti close（`$PYTHON_CMD graphiti_manager.py close`）+ killAll() → 6 秒超时 → process.exit()
  - exit: 调 killAllSync()
  - tool.execute.after: 从 PID 文件读取后台进程 PID → 注册
  - 与现有 timeline.ts 的 process.on("exit") 合并
- **验证点**:
  - 语法检查通过
  - 现有功能不破坏（timeline 记录、env 注入等）
  - 信号处理器注册但不干扰正常退出
- **依赖**: 步骤 6、步骤 7

### 步骤 9. 修改 Plugin — 条件触发的 Adviser

- **文件**: `plugins/security-analysis.ts`（修改）
- **预估行数**: ~50 行
- **改动内容**:
  - tool.execute.after 钩子增加 Adviser 触发条件检测
  - 条件：连续失败 2 次 / 输出超 5000 字符 / 超过 20 步
  - 触发时调 ai-dialogue.py chat 获取建议
  - 建议通过 session.prompt 注入到 agent 上下文
  - debugLog 记录每次触发
- **验证点**:
  - 语法检查通过
  - 不触发时不影响正常流程
  - 触发条件正确检测
- **依赖**: 无

### 步骤 10. 新建 6 个工种 agent .md 文件

- **文件**: `agents/searcher.md` + `agents/pentester.md` + `agents/coder.md` + `agents/adviser.md` + `agents/memorist.md` + `agents/installer.md`（新建）
- **预估行数**: 每个文件 ~30-50 行（frontmatter + system prompt），合计 ~200 行
- **改动内容**:
  - 每个工种的 frontmatter：
    ```yaml
    ---
    mode: subagent
    hidden: true
    buwai-extension-id: true
    ---
    ```
  - **不加 `permission: { task: { "*": "allow" } }`** → 工种永远是叶子节点
  - 每个工种的 system prompt 包含：
    - 工种角色定义（职责、适用场景）
    - vector store 使用规则（开始前查、完成后存）
    - Graphiti 使用规则（记录事件、查历史）
    - 子 agent 报告格式（`<result>` / `<discovered_surfaces>` / `<unsolved_challenges>`）
    - **路径引用用 `$SHARED_DIR` 而非 `$AGENT_DIR`**（工种没有自己的 AGENT_DIR，getScriptDir 返回 undefined → $AGENT_DIR 不注入）
  - 引用 `{{buwai-rule:execution-discipline}}` 等通用规则片段
- **验证点**:
  - 6 个文件语法正确（frontmatter 格式）
  - 每个工种 mode=subagent + hidden=true
  - 每个工种无 task:allow 权限
  - `node --check` 不报错（如有 ts 引用）
- **依赖**: 无

### 步骤 11. 修改 5 个领域 agent 的 frontmatter

- **文件**: `agents/binary-analysis.md` + `agents/web-analysis.md` + `agents/mobile-analysis.md` + `agents/ai-security-analysis.md` + `agents/crypto-analysis.md`（修改 frontmatter）
- **预估行数**: 每个文件 +3 行，合计 ~15 行
- **改动内容**:
  - 每个 agent 的 frontmatter 加：
    ```yaml
    permission:
      task:
        "*": allow
    ```
  - 如果 frontmatter 已有 permission 字段，合并进去（不覆盖已有规则）
  - security-analysis-evolve 和 security-coordinator **不改**（evolve 不做分析；coordinator 不进化）
- **验证点**:
  - 5 个文件的 frontmatter 格式正确
  - `task: allow` 显式写出（不能用 `*: allow` 替代）
  - 现有 frontmatter 字段不被破坏
- **依赖**: 无

### 步骤 12. 修改 Plugin — WORKER_AGENTS + requireAgent + getTaskDir 回溯

- **文件**: `plugins/lib/constants.ts`（修改）+ `plugins/lib/session-manager.ts`（修改）+ `plugins/security-analysis.ts`（修改）
- **预估行数**: constants.ts ~30 行新增 + session-manager.ts ~30 行修改 + security-analysis.ts ~40 行修改
- **改动内容**:

  **(A) constants.ts 新增 WORKER_AGENTS map**:
  ```typescript
  export const WORKER_AGENTS: Record<string, WorkerAgentConfig> = {
    "searcher":   { compactionContext: "### searcher 状态\n- 已搜索的关键词\n- 已收集的信息摘要" },
    "pentester":  { compactionContext: "### pentester 状态\n- 已执行的测试和结果\n- 已发现的漏洞" },
    "coder":      { compactionContext: "### coder 状态\n- 已开发的代码和用途\n- 当前迭代状态" },
    "adviser":    { compactionContext: "### adviser 状态\n- 已提供的建议\n- 当前分析的关键决策点" },
    "memorist":   { compactionContext: "### memorist 状态\n- 已检索的知识来源\n- 已返回的关键结论" },
    "installer":  { compactionContext: "### installer 状态\n- 已安装的工具\n- 已完成的配置变更" },
  };
  export function isWorkerAgent(agentName: string): boolean {
    return agentName in WORKER_AGENTS;
  }
  ```

  **(B) session-manager.ts 改造 requireSecurityAgent → requireAgent**:
  - 新增 `requireAgent(hookName, sessionID)` 方法：同时匹配 `SECURITY_AGENTS` 和 `WORKER_AGENTS`
  - 返回值增加 `agentType: "security" | "worker"` 字段
  - `isSecurityAgent()` 逻辑不变（只匹配 SECURITY_AGENTS）
  - 所有调用 `requireSecurityAgent` 的地方改为 `requireAgent`

  **(C) security-analysis.ts compacting 适配**:
  - `requireAgent` 返回 worker 类型时，用 `WORKER_AGENTS[name].compactionContext`（不调 `getCompactionContext`）

  **(D) getTaskDir 父链回溯**:
  - `shell.env` 和 `compacting` 的 `getTaskDir(sessionID)` 返回 null 时，沿 `parentSessionID` 链回溯查父 session 的 taskDir
  - 实现：
    ```typescript
    let taskDir = getTaskDir(sessionID);
    if (!taskDir) {
      let parent = session.parentSessionID;
      while (parent && !taskDir) {
        taskDir = getTaskDir(parent);
        parent = ctx.sessionManager.get(parent)?.parentSessionID;
      }
    }
    ```

- **验证点**:
  - 语法检查通过（`node --check`）
  - `requireAgent` 对工种返回有效 session（agentType="worker"）
  - `requireAgent` 对领域 agent 返回有效 session（agentType="security"）
  - `requireAgent` 对 general/非 agent 返回 undefined
  - compacting 对工种注入 WORKER_AGENTS 的 compactionContext
  - shell.env 对工种注入环境变量（$AGENT_DIR 不注入，其余正常）
  - 子 session 的 $TASK_DIR 通过父链回溯正确拿到
- **依赖**: 步骤 10（工种 agent .md 文件存在，requireAgent 才能识别）、步骤 9（security-analysis.ts 在步骤 7-9 已被修改，步骤 12 在其基础上继续改）

### 步骤 13. 更新 agents-rules（sub-agent-orchestration + cross-agent-delegation）

- **文件**: `agents-rules/sub-agent-orchestration.md`（修改）+ `agents-rules/cross-agent-delegation.md`（修改）
- **预估行数**: ~100 行修改
- **改动内容**:

  **(A) sub-agent-orchestration.md 更新**:
  - 调度规则新增：
    1. **Task 调用格式**：`Task(subagent_type: "<工种名>", description: "<工种-任务>", prompt: "<工种 prompt + 上下文>")`
    2. **防递归约束**："工种 agent 不应再创建子 session——工种间协作由领域 agent 编排"
    3. **持久化子 agent**：优先复用已有持久化子 agent（通过 sub_agent_manager），不存在时新建
  - 每个工种加 vector store / Graphiti 使用指引（开始前查 + 完成后存）
  - memorist 改为三层检索（vector store + Graphiti + 知识库文件）

  **(B) cross-agent-delegation.md 更新**:
  - 领域内委派的 Task 调用格式明确（`subagent_type: "<工种名>"`）
  - 子 agent 完成后自动存入 vector store 的说明

- **验证点**:
  - 人工读一遍确认每个工种有明确的 vector store / Graphiti bash 命令
  - Task 调用格式包含 subagent_type
  - 防递归约束清晰
  - memorist 有三层检索
  - 无开发过程信息
- **依赖**: 步骤 10（工种 agent 存在后，引用才有效）

### 步骤 14. 新增单元测试 + 集成测试

- **文件**: `test/embedding_client/` + `test/vector_store/` + `test/graphiti_tool/` + `test/sub_agent_manager/`（新建）
- **预估行数**: 每个目录 ~50-80 行测试代码
- **改动内容**:
  - `test/embedding_client/`: mock 智谱 API，测试 embed/embed_batch/缓存/错误处理/无 API key
  - `test/vector_store/`: 真实 sqlite-vec 端到端测试（store → search → 返回匹配），mock embedding_client
  - `test/graphiti_tool/`: mock Graphiti API（Neo4j 不可用时跳过），测试 add/search/search-recent 的参数校验和错误处理
  - `test/sub_agent_manager/`: mock ai-dialogue.py，测试 create/send/list/delete + sub_agents.json 更新
- **验证点**:
  - 全部测试通过
  - `pytest test/embedding_client/ test/vector_store/ test/graphiti_tool/ test/sub_agent_manager/ -v` 无失败
  - 阶段 1 的 93 个测试回归通过
- **依赖**: 步骤 1-4、步骤 10-12

---

## §4 验收标准

### 4.1 功能验收

| # | 验收项 | 验证方法 | 通过标准 |
|---|--------|---------|---------|
| 1 | Embedding | `embedding_client.py --text "test"` | 返回 1024 维向量 |
| 2 | Vector store | `vector_store.py store --text "test"` 然后 `search --query "test"` | 搜索返回匹配结果 |
| 3 | Graphiti | `graphiti_manager.py init` → `graphiti_tool.py add` → `graphiti_tool.py search` | 事件记录到 Neo4j + 搜索返回结果 |
| 3a | Graphiti 生命周期 | Plugin 启动时 init → 退出时 close | init/close 在 debugLog 记录 |
| 4 | 持久化子 agent | `sub_agent_manager.py create` → `send` → `list` | session 复用，上下文保持 |
| 5 | Adviser 触发 | 模拟连续失败 | 触发建议注入 |
| 6 | 进程清理 | 启动 detach 进程 → 退出 opencode | 进程被自动 kill |
| 7 | 工种 agent 可见 | `Task(subagent_type: "searcher")` 创建子 session | 成功创建 searcher 子 session |
| 7a | 三层 Task 嵌套 | coordinator → binary-analysis → searcher | searcher 孙子 session 成功创建 |
| 7b | 工种环境变量 | searcher 子 session 执行 `echo $TASK_DIR` | 返回父 session 的 taskDir 路径 |
| 7c | 工种叶子限制 | searcher 子 session 尝试 `Task(...)` | task 工具不可见（被 deny） |
| 7d | 领域 agent task:allow | binary-analysis 子 session 创建 searcher | 成功（不被注入 task:deny） |
| 8 | 单元测试 + 集成测试 | `pytest test/embedding_client/ test/vector_store/ test/graphiti_tool/ test/sub_agent_manager/ -v` | 全部通过 |

### 4.2 回归验收

| 验收项 | 通过标准 |
|--------|---------|
| 阶段 1 的 93 个测试 | 全部通过 |
| 现有 Plugin 功能 | timeline 记录、env 注入、compacting 等不破坏 |
| 现有 agent prompt | 核心规则不被破坏 |

### 4.3 架构验收

| 验收项 | 通过标准 |
|--------|---------|
| 依赖方向 | 不违反现有架构 |
| 文件放置 | 新文件在正确位置 |
| 硬依赖阻断 | Neo4j 未安装时 Plugin abort 并提示安装；ZHIPU_API_KEY 缺失时 embedding 功能报错提示 |

---

## §5 与现有需求文档的关系

| 现有需求 | 关系 |
|---------|------|
| `2026-07-05-pentagi-evolution-phase1.md` | 阶段 1 基础上构建 |
| `docs/进化/进化-opencode退出时机清理子进程调研.md` | 步骤 6、8 的实现依据 |

---

## 附录：关键技术决策

### 为什么用 Python 库而非 HTTP 服务

Graphiti 本身就是 Python 框架（`getzep/graphiti`，28.4k stars）。PentAGI 用 HTTP 服务模式是因为它是 Go 项目——Go 不能直接调 Python 库，需要部署 Graphiti REST 服务 + 写 Go HTTP 客户端。OpenSecurity 是 Python 项目——直接 `from graphiti_core import Graphiti` 用 Python API，零损失，不需要独立服务，不需要 Go 依赖。

### 为什么 Graphiti 放在 .opencode/tools/Graphiti/

Graphiti 是 OpenSecurity 系统的一部分（不是外部可选工具）。放在 tools/ 目录下表明它是内置组件，由 Plugin 管理生命周期（启动时 init、退出时 close）。

### 为什么用 sqlite-vec 而非 pgvector

sqlite 是零运维的嵌入式数据库（单文件），与 OpenSecurity 的文件存储架构一致。pgvector 需要 PostgreSQL 服务——CUI 工具不应该要求用户装 DB。

### 为什么用智谱 embedding 而非本地模型

DeepSeek 没有 embedding API（已确认）。智谱 embedding-3 中文友好、便宜（¥0.5/1M tokens）、用户已有智谱 API key。注意：embedding_client.py 只给 vector_store 用，Graphiti 自己管理 embedding（初始化时配置 embedder）。

### 为什么 Adviser 是条件触发而非每次触发

PentAGI 的 Adviser 每次工具调用都触发——成本太高。条件触发（失败 2 次/复杂输出/长任务）在关键节点给建议，日常操作不打扰。

### 进程清理的信号处理器组合

参考 oh-my-openagent 的 process-cleanup.ts：
- SIGINT/SIGTERM → 异步 killAll + 6 秒超时
- exit → 同步 SIGKILL 兜底
- 与现有 timeline.ts 的 process.on("exit") 合并

### 为什么工种是独立 agent 而非 prompt 模板

每个工种有完全不同的能力边界：adviser 无工具（纯文本咨询）、pentester 有终端工具、searcher 用便宜模型。如果工种只是 prompt 模板（复用父 agent 配置），无法实现工具隔离和 model 优化。独立 agent .md 文件让每个工种有独立的 model、permission、system prompt。

### 为什么用三层 Task 嵌套

PentAGI 的工种可嵌套调用（pentester 调 coder），但 opencode 的子 session 默认被注入 `task: deny` 不能再创建子 session。给领域 agent 加 `permission: { task: { "*": "allow" } }` 后，领域 agent 作为子 session 不被注入 deny → 可以创建工种子 session → 三层架构（领域 agent → 工种）成立。工种不加 task:allow → 叶子节点 → 不能递归。

代码验证：`deriveSubagentSessionPermission`（`subagent-permissions.ts:18`）用 `rule.permission === "task"` 精确匹配判断是否注入 deny。领域 agent 有此规则 → 不注入；工种无此规则 → 注入 deny。

### 为什么不需要 coordinator 作为必须入口

领域 agent 有 `task:allow` + `cross-agent-delegation` 规则注入，能直接互相委派（web-analysis → Task(binary-analysis)）。用户直接选最相关的领域 agent 开始，中途需要其他领域能力时直接委派。coordinator 可保留为可选入口（不确定时用），但不是必须的。
