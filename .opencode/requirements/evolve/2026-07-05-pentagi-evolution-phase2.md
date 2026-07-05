# PentAGI 进化 — 阶段 2：完整多 Agent 协作栈

## §1 背景与目标

### 1.1 来源

阶段 1 完成了基础进化（detach 模式、授权框架、多 agent 协作规则、渗透工具检测、Sploitus 集成、浏览器自动化服务）。阶段 2 解决多 agent 协作的**基础设施缺失**——当前 agent 之间只能通过 Task 工具传递文本，无法共享记忆、保持持久状态、或自动避免走错方向。

### 1.2 核心约束（不可变更）

> **OpenSecurity 面向真实安全分析场景，不是 CTF 工具。** CTF 只是训练和验证 agent 能力的手段。所有决策必须以"真实场景下是否必要"为标尺。

### 1.3 阶段 2 的 6 项改动概览

| # | 能力 | 类型 | 解决的问题 |
|---|------|------|-----------|
| 1 | Embedding 基础设施 | 新脚本 | vector store 的文本向量化基础 |
| 2 | Vector store（sqlite-vec） | 新脚本 + 新规则 | 子 agent 之间的知识共享 |
| 3 | Graphiti 时序图谱 | `.opencode/tools/Graphiti/` + Plugin 生命周期管理 | 长任务事件不丢失 + 实体关系查询 |
| 4 | 持久化子 agent | 新脚本 + Plugin 改动 | 多轮迭代不浪费 token |
| 5 | 条件触发的 Adviser | Plugin 改动 | 避免走错反而省 token |
| 6 | 进程清理（信号处理器） | Plugin 改动 | opencode 退出时自动 kill 子进程 |

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
- `init` → 连接 Neo4j（从环境变量读 NEO4J_URL/NEO4J_USER/NEO4J_PASSWORD）+ 初始化 Graphiti（配置 LLM provider 和 embedder）+ 保存实例到全局
- `close` → 关闭 Graphiti driver 连接
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
| `binary-analysis/scripts/detect_env.py` | 修改（加 graphiti-core/sqlite-vec 包 + Neo4j 配置 + agents=["all"] 统一） | 步骤 5 |
| `binary-analysis/scripts/registry.json` | 修改（注册新脚本） | 步骤 1-4 |
| `plugins/lib/process-registry.ts` | 新建 | 步骤 6 |
| `plugins/security-analysis.ts` | 修改（Graphiti 生命周期 + 信号处理器 + Adviser + PID 注册） | 步骤 7-9 |
| `agents-rules/sub-agent-orchestration.md` | 修改（工种 Task prompt 模板 + memorist 三层检索） | 步骤 10 |
| `agents-rules/cross-agent-delegation.md` | 修改（委派策略加 vector store / Graphiti 使用说明） | 步骤 10 |
| `agents/*.md`（5 个分析 agent） | 可能修改（引用更新） | 步骤 10 |
| `test/embedding_client/` | 新建（单元测试） | 步骤 11 |
| `test/vector_store/` | 新建（单元测试 + 集成测试） | 步骤 11 |
| `test/graphiti_tool/` | 新建（单元测试） | 步骤 11 |
| `test/sub_agent_manager/` | 新建（单元测试） | 步骤 11 |

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
    - `init` → 连接 Neo4j（从 NEO4J_URL/NEO4J_USER/NEO4J_PASSWORD）+ 初始化 Graphiti（配置 LLM/embedder）+ 保存实例
    - `close` → 关闭 Graphiti driver
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
  - Neo4j 不可用时 `health` 返回不可用（不崩溃）
  - Neo4j 可用时 `init` → `add` → `search` 端到端测试
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
  - Neo4j 连接配置从 .ai_env 读取（NEO4J_URL/NEO4J_USER/NEO4J_PASSWORD），可选
  - .ai_env 模板增加 Neo4j + Graphiti LLM 配置占位符（NEO4J_URL=、NEO4J_USER=、NEO4J_PASSWORD=、GRAPHITI_LLM_MODEL=、GRAPHITI_LLM_BASE_URL= 等）
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
- **预估行数**: ~40 行
- **改动内容**:
  - Plugin 初始化时调 `$PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_manager.py init`（Neo4j 不可用时跳过，不阻塞启动）
  - Plugin 退出时的 Graphiti close 合并到步骤 8 的信号处理器（统一 cleanup 路径）
  - 用 debugLog 记录 init 结果
  - Neo4j 不可用时 init 失败不阻塞 Plugin 启动（Graphiti 功能降级，其他功能不受影响）
- **验证点**:
  - 语法检查通过
  - Neo4j 可用时 init 成功（debugLog 记录）
  - Neo4j 不可用时 init 跳过（debugLog 记录，不崩溃）
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

### 步骤 10. 更新 agents-rules + agent prompt

- **文件**: `agents-rules/sub-agent-orchestration.md`（修改）+ `agents-rules/cross-agent-delegation.md`（修改）+ 可能的 agent prompt 更新
- **预估行数**: ~120 行修改
- **改动内容**:

  **(A) 工种 Task prompt 模板更新**——所有工种加 vector store / Graphiti 使用指引：

  #### searcher（信息收集）
  - **开始前**：查 vector store 获取已有发现（避免重复收集）
    ```bash
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py search --query "[目标关键词]" --limit 5
    ```
  - **完成后**：把新发现存入 vector store（供后续子 agent 检索）
    ```bash
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py store --text "[发现描述]" --type guide --metadata '{"source":"searcher","target":"[目标]"}'
    ```
  - **同时**：记录到 Graphiti（供时序查询）
    ```bash
    $PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_tool.py add --name "[事件名]" --content "[详细内容]" --source searcher
    ```
  - **更新后的 Task prompt 模板**：
    ```
    "你是信息收集专家。收集目标 [目标描述] 的 [收集内容]。
    开始前先查 vector store 获取已有发现：
      $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py search --query \"[相关关键词]\" --limit 5
    完成后把新发现存入 vector store：
      $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py store --text \"[发现]\" --type guide
    返回结构化摘要。"
    ```

  #### pentester（渗透测试）
  - **开始前**：查 vector store 获取 searcher 存的发现 + Graphiti 查历史
    ```bash
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py search --query "[目标漏洞关键词]" --limit 5
    $PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_tool.py search-recent --query "[目标]" --hours 6
    ```
  - **完成后**：记录攻击结果到 Graphiti（供后续时序查询和关系分析）
    ```bash
    $PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_tool.py add --name "[攻击事件]" --content "[攻击过程+结果]" --source pentester
    ```
  - **更新后的 Task prompt 模板**：
    ```
    "你是渗透测试专家。对目标 [目标] 执行 [测试类型]。
    开始前查已有发现：
      vector_store.py search --query \"[目标漏洞]\"
      graphiti_tool.py search-recent --query \"[目标]\" --hours 6
    完成后记录到 Graphiti：
      graphiti_tool.py add --name \"[攻击事件]\" --content \"[结果]\" --source pentester
    返回攻击结果 + 证据。"
    ```

  #### coder（代码开发）
  - **开始前**：查 vector store 获取已有发现和代码片段
    ```bash
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py search --query "[漏洞/目标关键词]" --limit 5
    ```
  - **完成后**：把可用代码存入 vector store（供后续复用）
    ```bash
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py store --text "[代码内容]" --type code --metadata '{"description":"[用途]","language":"python"}'
    ```
  - **更新后的 Task prompt 模板**：
    ```
    "你是代码开发专家。基于 [上下文] 编写 [脚本/payload]。
    开始前查已有发现和代码：
      vector_store.py search --query \"[关键词]\"
    完成后把代码存入 vector store：
      vector_store.py store --text \"[代码]\" --type code
    返回完整可用代码 + 使用说明。"
    ```

  #### adviser（策略咨询）
  - **开始前**：查 Graphiti 历史（之前是否遇到过类似障碍）+ vector store（相关方法论）
    ```bash
    $PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_tool.py search --query "[障碍关键词]" --num-results 10
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py search --query "[障碍关键词]" --limit 5
    ```
  - **更新后的 Task prompt 模板**：
    ```
    "你是策略顾问。当前遇到 [障碍描述]。已有信息 [上下文]。
    先查历史是否遇到过类似障碍：
      graphiti_tool.py search --query \"[障碍关键词]\"
      vector_store.py search --query \"[障碍关键词]\"
    基于历史经验和当前信息，推荐解决方案和下一步。"
    ```

  #### memorist（记忆检索）
  - **完全更新**：不再只读 markdown 知识库，改为三层检索
    ```bash
    # 1. vector store（碎片化即时记忆）
    $PYTHON_CMD $SHARED_DIR/scripts/vector_store.py search --query "[主题]" --limit 10
    # 2. Graphiti（时序事件 + 关系查询）
    $PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_tool.py search --query "[主题]" --num-results 10
    $PYTHON_CMD $OPENCODE_ROOT/tools/Graphiti/graphiti_tool.py search-recent --query "[主题]" --hours 24
    # 3. 知识库文件（结构化方法论，不变）
    Read $AGENT_DIR/knowledge-base/[相关文件].md
    ```
  - **更新后的 Task prompt 模板**：
    ```
    "你是记忆检索专家。检索关于 [主题] 的历史信息。
    依次查三层记忆：
      1. vector_store.py search --query \"[主题]\"
      2. graphiti_tool.py search --query \"[主题]\"
      3. Read $AGENT_DIR/knowledge-base/[相关文件].md
    返回相关方法和结论。"
    ```

  #### installer（环境维护）
  - 不变（不涉及知识存储/检索）

  **(B) cross-agent-delegation.md 更新**：
  - 领域内委派策略增加："子 agent 完成后自动存入 vector store，后续子 agent 开始前自动查询"
  - 典型例子更新：增加 vector store / Graphiti 的使用说明

  **(C) 持久化子 agent 引用更新**：
  - sub-agent-orchestration.md 的调度规则增加："优先复用已有持久化子 agent（通过 sub_agent_manager），不存在时新建"

- **验证点**:
  - 人工读一遍确认每个工种都有明确的 vector store / Graphiti bash 命令
  - Task prompt 模板包含完整的"开始前查询 + 完成后存储"流程
  - memorist 有三层检索（vector store + Graphiti + 知识库文件）
  - 各 agent prompt 展开后行数可接受
  - 无开发过程信息（"照抄 PentAGI"等字样）
- **依赖**: 步骤 1-4

### 步骤 11. 新增单元测试 + 集成测试

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
- **依赖**: 步骤 1-4

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
| 7 | 单元测试 + 集成测试 | `pytest test/embedding_client/ test/vector_store/ test/graphiti_tool/ test/sub_agent_manager/ -v` | 全部通过 |

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
| 可选依赖 | Neo4j/ZHIPU_API_KEY 缺失时不崩溃，对应功能降级 |

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
