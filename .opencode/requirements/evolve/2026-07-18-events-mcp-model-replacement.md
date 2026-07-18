# events MCP 模型替换与 Flow ID 贯通

## §1 背景与目标

### 来源痛点

events MCP 当前配置无法实际使用，存在 6 个问题：

| # | 问题 | 根因 | 影响 |
|---|------|------|------|
| 1 | 实体提取不可用 | `graphiti_config.py` 用 `OpenAIClient` 直连 ZhipuAI（Responses API），coding plan key 不支持直连 | 写路径 0% 可用 |
| 2 | cross-encoder 崩溃 | `OpenAIRerankerClient` 依赖 logprobs + logit_bias，ZhipuAI 不支持 | diverse_results_search 崩溃 |
| 3 | embedding 写入失败 | `BgeM3Embedder.create` 是同步方法，graphiti 写路径调 `await embedder.create()` 报错 | 写路径 embedding 失败 |
| 4 | API key 配置过时 | 用户已将 `.ai_env` 的 `ZHIPU_API_KEY` 改为 `DEEPSEEK_API_KEY`，但 `detect_env.py` 和 `graphiti_config.py` 仍读旧变量 | 门控逻辑失效 |
| 5 | 父子 session 数据隔离 | `fireAndForgetEvent` 用当前 session ID 做 group_id，子 session 有独立 ID | 跨 agent 数据不共享 |
| 6 | 搜索跨所有 group | `server.py` 搜索不传 `group_ids` | 搜索结果含无关 session 数据 |

### 预期收益

| 维度 | 改进前 | 改进后 |
|------|--------|--------|
| 写路径可用性 | 0% | 100%（DeepSeek API 实体提取 + BGE-M3 embedding） |
| diverse_results_search | 崩溃 | 可用（BgeReranker 本地重排序） |
| 父子 session 数据共享 | 隔离 | 共享（flow_id 贯通） |
| 搜索精度 | 跨所有 group 噪音 | 限定当前 flow |
| session 删除清理 | 孤儿数据残留 | 自动清理 |

### 模型选型决策

| 场景 | PentAGI 用 | 我们用 | 理由 |
|------|-----------|--------|------|
| 核心提取（medium） | gpt-5-mini | **deepseek-v4-pro**（可切 flash） | pro 等效 ~37B 活跃参数，实体提取质量 ≥ gpt-5-mini。通过 `.ai_env` 的 `DEEPSEEK_MODEL` 变量切换 |
| 时间戳推断（small） | gpt-4.1-nano | **deepseek-v4-flash** | 轻量任务，flash 够用且更快 |
| Embedding | text-embedding-3-small | **BGE-M3 本地** | 1024 维，MTEB top 5，零成本 |
| CrossEncoder | gpt-4.1-nano logprobs | **bge-reranker-v2-m3 本地** | 专用 cross-encoder，MTEB reranking top 3，≥ LLM logprobs hack |

思考模式处理：DeepSeek 默认启用思考模式，但 graphiti 需要 `temperature=0` 保证确定性输出（同一文本每次提取结果一致），思考模式会忽略 temperature。因此 `DeepSeekLLMClient` 显式关闭思考模式（`extra_body={"thinking": {"type": "disabled"}}`）。

---

## §2 技术方案

### 2.1 新建文件

#### `mcp-servers/events/llm_client.py` — DeepSeekLLMClient

自定义 LLM 客户端，继承 graphiti-core 的 `LLMClient` 基类。

```python
class DeepSeekLLMClient(LLMClient):
    """通过 DeepSeek API 调用 LLM（json_object 模式，思考模式关闭）。

    graphiti 基类 LLMClient.generate_response 已将 response_model 的 JSON schema
    拼到消息文本末尾（"Respond with a JSON object in the following format: {schema}"）。
    本客户端忽略 response_model 参数，直接用 json_object response_format 发送消息，
    LLM 按 prompt 里的 schema 要求输出 JSON。
    """
    def __init__(self, config: LLMConfig):
        super().__init__(config, cache=False)
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,   # "https://api.deepseek.com"
        )

    async def _generate_response(self, messages, response_model, max_tokens, model_size):
        # 1. 转换消息格式（Message → OpenAI dict）
        # 2. 选模型（medium → config.model, small → config.small_model）
        # 3. 调 API: chat.completions.create(
        #        model=selected_model,
        #        messages=openai_messages,
        #        temperature=0,                        ← 固定 0，保证确定性
        #        max_tokens=max_tokens,
        #        response_format={"type": "json_object"},
        #        extra_body={"thinking": {"type": "disabled"}},
        #    )
        # 4. 解析 JSON 响应：json.loads(response.choices[0].message.content)
        # 5. 返回 parsed_dict（dict[str, Any]，不是 tuple）
```

关键设计：
- **继承 LLMClient（不是 BaseOpenAIClient）**：BaseOpenAIClient 要求实现 `_create_completion` + `_create_structured_completion`（用 Responses API），DeepSeek 不支持。继承 LLMClient 只需实现一个 `_generate_response`
- **返回 dict（不是 tuple）**：LLMClient 基类的 `_generate_response_with_retry` 期望返回 `dict[str, Any]`（解析后的 JSON dict）。token 计数通过 `self.token_tracker.record()` 记录（可选）
- **忽略 response_model 参数**：基类 `generate_response` 已将 JSON schema 拼到消息文本，不需要 structured output API
- **关闭思考模式**：`extra_body={"thinking": {"type": "disabled"}}`，确保 temperature=0 生效
- **json_object 模式**：保证输出是有效 JSON
- **temperature 固定 0**：graphiti 需要确定性输出（同文本每次提取结果一致）。LLMConfig 里设 `temperature=0`
- **错误处理**：DeepSeek 的 `openai.RateLimitError` 直接抛出（graphiti 基类的 retry 逻辑会重试）；其他 API 错误也直接抛（基类 retry 处理 server errors）

#### `mcp-servers/events/reranker.py` — BgeRerankerClient

```python
class BgeRerankerClient(CrossEncoderClient):
    """使用 bge-reranker-v2-m3 本地模型实现 CrossEncoderClient 接口。

    替代 OpenAIRerankerClient（依赖 logprobs + logit_bias，DeepSeek 不支持 logit_bias）。
    bge-reranker-v2-m3 是专用 cross-encoder，MTEB reranking top 3，质量 ≥ gpt-4.1-nano logprobs。
    """
    def __init__(self):
        from sentence_transformers import CrossEncoder
        self._model = None  # 延迟加载

    @property
    def model(self):
        """延迟加载（首次 rank 调用时加载，约 3 秒）"""
        if self._model is None:
            from sentence_transformers import CrossEncoder
            self._model = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
        return self._model

    async def rank(self, query: str, passages: list[str]) -> list[tuple[str, float]]:
        # 1. 构造 [(query, passage1), (query, passage2), ...] 列表
        # 2. model.predict(pairs) → numpy array of scores（同步调用包 asyncio.to_thread）
        # 3. 按 score 降序排列 → 返回 [(passage, score), ...]
```

延迟加载理由：MCP server 首次搜索可能不需要 cross-encoder（只有 diverse_results_search 用），避免启动时就加载 2GB 模型。daemon 启动时也不阻塞——首次 rank 时才加载。

### 2.2 修改文件

#### `mcp-servers/events/graphiti_config.py`

| 改动 | 详情 |
|------|------|
| 读 API key | `get_zhipu_api_key()` → `get_deepseek_api_key()`，读 `DEEPSEEK_API_KEY` |
| 读模型名 | 新增：读 `DEEPSEEK_MODEL`（默认 `deepseek-v4-pro`）和 `DEEPSEEK_SMALL_MODEL`（默认 `deepseek-v4-flash`） |
| LLM 客户端 | `OpenAIClient(config=llm_config)` → `DeepSeekLLMClient(config=llm_config)` |
| LLMConfig | `base_url="https://open.bigmodel.cn/..."` → `"https://api.deepseek.com"`；`model` 从环境变量读 |
| CrossEncoder | `OpenAIRerankerClient(config=llm_config)` → `BgeRerankerClient()` |
| BgeM3Embedder | 加 `async def create`（同步 `model.encode` 包 `asyncio.to_thread`）+ `async def create_batch` |

BgeM3Embedder async 方法设计：
```python
async def create(self, input_data) -> list[float]:
    """async 版本——graphiti-core 写路径调 await embedder.create()"""
    if isinstance(input_data, str):
        vec = await asyncio.to_thread(self.model.encode, input_data, True)
        return np.asarray(vec).tolist()
    vecs = await asyncio.to_thread(self._encode_batch, list(input_data))
    return vecs

async def create_batch(self, input_data: list[str]) -> list[list[float]]:
    """批量 embedding"""
    vecs = await asyncio.to_thread(self._encode_batch, input_data)
    return vecs
```

保留原同步 `create` 方法（命名为 `create_sync`），以防 graphiti-core 内部有同步调用路径。

#### `binary-analysis/scripts/detect_env.py`

| 位置 | 改动 |
|------|------|
| `_AI_ENV_TEMPLATE` (L226) | 添加 `DEEPSEEK_API_KEY=` + `DEEPSEEK_MODEL=deepseek-v4-pro` + `DEEPSEEK_SMALL_MODEL=deepseek-v4-flash` |
| `_detect_mcp_deps` (L1044) | `os.environ.get("ZHIPU_API_KEY")` → `os.environ.get("DEEPSEEK_API_KEY")` |
| `_detect_mcp_deps` (L1050) | 提示文案 ZHIPU → DEEPSEEK |
| `_detect_mcp_deps` (L1112-1118) | `_zhipu_api_key` → `_deepseek_api_key`，提示文案更新 |
| install 输出 (L755-760) | ZHIPU → DEEPSEEK |
| check-preinstall (L886-900) | ZHIPU 门控 → DEEPSEEK 门控 |
| docstring (L1008) | ZHIPU → DEEPSEEK |

#### `mcp-servers/events/server.py`

| 改动 | 详情 |
|------|------|
| 7 个搜索工具加 `group_id` 参数 | 每个工具签名加 `group_id: str`（必填），`search_()` 调用传 `group_ids=[group_id]` |
| 新增 `delete_session_events` 工具 | 接收 `session_id`，调 `EntityNode.delete_by_group_id` + `EpisodicNode.delete_by_group_id` |

`group_id` 参数是必填（不是可选）——对齐 PentAGI 设计：每次搜索限定当前 flow。

#### `plugins/security-analysis.ts`

| 位置 | 改动 |
|------|------|
| `fireAndForgetEvent` (L1126) | 第 4 参数 `sid` → `session.flowId` |
| `fireAndForgetEvent` (L1156) | 第 4 参数 `sid` → `session.flowId` |
| `buildEnvSection` (L168 后) | 添加 OPENSECURITY_FLOW_ID 描述（见下方具体文本） |

buildEnvSection 里添加的具体文本：
```
- 事件库 Flow ID ($OPENSECURITY_FLOW_ID): ${session.flowId}。标识当前分析任务的事件库分区。主任务和它启动的所有子任务共享同一个 Flow ID——子 agent 写入的事件（工具执行记录、LLM 响应）和父 agent 写入的事件存在同一个分区里，互相可搜索。调用事件库 MCP 的搜索工具时，将此值作为 group_id 参数传入，限定搜索范围到当前任务的事件，避免搜到其他无关任务的数据。
```
| `shell.env` (L1016 后) | 添加 `output.env.OPENSECURITY_FLOW_ID = session.flowId` |
| `session.deleted` (L1196 后) | 添加 `deleteGraphitiEvents(rootFlowId)` 调用 |
| 新增 `deleteGraphitiEvents` 函数 | 通过 write_event_daemon stdin 发送 `{"action":"delete","group_id":flowId}` 消息，daemon 复用已有 Neo4j 连接执行删除 |

deleteGraphitiEvents 实现机制：复用 write_event_daemon 的 stdin 管道。daemon 的 worker 函数检查消息是否含 `action: "delete"` 字段：
- 含 action=delete → 调 `EntityNode.delete_by_group_id(driver, group_id)` + `EpisodicNode.delete_by_group_id(driver, group_id)`
- 不含 action → 正常 add_episode（现有逻辑不变）

避免为删除操作单独 spawn Python 进程或建 Neo4j 连接。session 删除是低频操作，但复用 daemon 连接更干净。

注意：`session.deleted` 事件传入的是被删除的 sessionID。需要取该 session 的 **flowId**（不是 sessionID 本身）作为 group_id 删除。通过 `sessionManager.get(sessionID)?.flowId` 获取。如果 session 已从内存 Map 删除（delete 调用在 get 之前），则跳过（无法获取 flowId）。

#### `test/env-check/test_subcommands.py`

| 改动 | 详情 |
|------|------|
| `TestZhipuGateLogic` → `TestDeepseekGateLogic` | 测试 DEEPSEEK_API_KEY 门控（未配置跳过 Docker / 已配置检查 Docker） |

---

## §3 实现规范

### 3.1 实施步骤拆分

#### 步骤 1：DeepSeekLLMClient（新建 llm_client.py）
- 文件：新建 `.opencode/mcp-servers/events/llm_client.py`
- 预估行数：~120 行
- 验证点：`python -c "from llm_client import DeepSeekLLMClient; print('OK')"` import 成功 + 语法检查
- 依赖：无

#### 步骤 2：BgeRerankerClient（新建 reranker.py）
- 文件：新建 `.opencode/mcp-servers/events/reranker.py`
- 预估行数：~60 行
- 验证点：`python -c "from reranker import BgeRerankerClient; print('OK')"` import 成功 + 语法检查
- 依赖：无

#### 步骤 3a：graphiti_config.py — API key + LLM 客户端替换
- 文件：改 `.opencode/mcp-servers/events/graphiti_config.py`
- 改动：`get_zhipu_api_key()` → `get_deepseek_api_key()`（读 DEEPSEEK_API_KEY）；新增读 `DEEPSEEK_MODEL`（默认 pro）+ `DEEPSEEK_SMALL_MODEL`（默认 flash）；`OpenAIClient` → `DeepSeekLLMClient`；`LLMConfig` base_url 改为 `https://api.deepseek.com`
- 预估行数：~30 行修改
- 验证点：`python -c "from graphiti_config import create_graphiti; g, err = create_graphiti(); print(err or 'graphiti created')"` — 缺 API key 时返回 err 字符串不报异常
- 依赖：步骤 1

#### 步骤 3b：graphiti_config.py — CrossEncoder 替换
- 文件：改 `.opencode/mcp-servers/events/graphiti_config.py`
- 改动：`OpenAIRerankerClient(config=llm_config)` → `BgeRerankerClient()`；删除 OpenAIRerankerClient import
- 预估行数：~10 行修改
- 验证点：同步骤 3a（create_graphiti 不报异常）
- 依赖：步骤 2

#### 步骤 3c：graphiti_config.py — BgeM3Embedder async
- 文件：改 `.opencode/mcp-servers/events/graphiti_config.py`
- 改动：BgeM3Embedder 的 `create` 改为 `async def create`（用 `asyncio.to_thread` 包装 `model.encode`）；新增 `async def create_batch`
- 预估行数：~25 行修改
- 验证点：`python -c "import inspect; from graphiti_config import BgeM3Embedder; print(inspect.iscoroutinefunction(BgeM3Embedder.create))"` 输出 True
- 依赖：无（与 3a/3b 同文件但独立改动，步骤 3 的三个子步骤按顺序执行）

#### 步骤 4：detect_env.py ZHIPU → DEEPSEEK + .ai_env 模板
- 文件：改 `.opencode/binary-analysis/scripts/detect_env.py`
- 改动：`_AI_ENV_TEMPLATE` 加 DEEPSEEK_API_KEY/MODEL/SMALL_MODEL（~5 行）；`_detect_mcp_deps` 的 ZHIPU_API_KEY 门控改 DEEPSEEK_API_KEY（~10 行）；install/check-preinstall 输出文案 ZHIPU→DEEPSEEK（~10 行）
- 预估行数：~30 行修改
- 验证点：`python detect_env.py check-preinstall security-analysis-evolve` 运行不报错 + JSON 输出含 `_deepseek_api_key` 字段
- 依赖：无

#### 步骤 5：（已合并到步骤 4）

#### 步骤 6：server.py 搜索加 group_id + delete_session_events
- 文件：改 `.opencode/mcp-servers/events/server.py`
- 改动：7 个搜索工具签名加 `group_id: str`（必填，放在 query 之后），`search_()` 调用传 `group_ids=[group_id]`；新增 `delete_session_events` 工具
- 预估行数：~50 行修改
- 验证点：`python -c "import ast; ast.parse(open('server.py').read())"` 语法通过 + grep 确认每个工具签名含 `group_id: str`
- 依赖：无

#### 步骤 7：security-analysis.ts fireAndForgetEvent 用 flowId
- 文件：改 `.opencode/plugins/security-analysis.ts`
- 改动：L1126 和 L1156 的 fireAndForgetEvent 第 4 参数从 `sid` 改为 `session.flowId`
- 预估行数：~5 行修改
- 验证点：两处调用都传 `session.flowId` 而非 `sid`
- 依赖：无

#### 步骤 8：security-analysis.ts 环境注入（buildEnvSection + shell.env）
- 文件：改 `.opencode/plugins/security-analysis.ts`
- 改动：buildEnvSection 加 OPENSECURITY_FLOW_ID 描述（§2.2 具体文本）；shell.env 加 `output.env.OPENSECURITY_FLOW_ID = session.flowId`
- 预估行数：~15 行修改
- 验证点：buildEnvSection 返回值含 OPENSECURITY_FLOW_ID + shell.env 注入 OPENSECURITY_FLOW_ID
- 依赖：无

#### 步骤 9：write_event_daemon.py 支持 delete 消息 + security-analysis.ts session.deleted 清理
- 文件：改 `.opencode/mcp-servers/events/write_event_daemon.py` + `.opencode/plugins/security-analysis.ts`
- 改动：
  - daemon worker 函数：检查消息含 `action:"delete"` → import EntityNode + EpisodicNode → 调 `EntityNode.delete_by_group_id(driver, group_id)` + `EpisodicNode.delete_by_group_id(driver, group_id)`（~15 行）
  - security-analysis.ts：新增 `deleteGraphitiEvents(flowId)` 函数，写 `{"action":"delete","group_id":flowId}\n` 到 daemon stdin（~10 行）
  - security-analysis.ts session.deleted hook：在 `ctx.sessionManager.delete(sessionID)` **之前**取 `session.flowId`，然后调 `deleteGraphitiEvents(flowId)`（~5 行）
- 预估行数：~35 行修改
- 验证点：手动向 daemon stdin 写 `{"action":"delete","group_id":"test-flow"}` → daemon 日志显示删除操作
- 依赖：步骤 7（fireAndForgetEvent 用 flowId，daemon 已就绪）

注意时序：`session.deleted` hook 必须在 `ctx.sessionManager.delete(sessionID)` **之前**获取 flowId。因为 `sessionManager.delete()` 会从内存 Map 移除 SessionData，之后 `get(sessionID)` 返回 undefined。当前代码 `security-analysis.ts:1196` 先调 `ctx.sessionManager.delete(sessionID)` 再做其他清理——需要调整顺序：先取 flowId → 调 deleteGraphitiEvents → 再 sessionManager.delete。

#### 步骤 10：test 更新
- 文件：改 `test/env-check/test_subcommands.py`
- 改动：`TestZhipuGateLogic` → `TestDeepseekGateLogic`，测试 DEEPSEEK_API_KEY 门控
- 预估行数：~15 行修改
- 验证点：`pytest test/env-check/test_subcommands.py -v` 全部通过
- 依赖：步骤 4

### 3.2 编码规则

- Python 文件：`python -c "compile(open('<file>').read(), '<file>', 'exec')"` 语法检查
- TypeScript 文件：`node --check <file>` 或 bun typecheck
- 禁止硬编码 API key
- 环境变量统一从 `.ai_env` 读取（通过 `load_ai_env()` 或 `os.environ`）
- `graphiti_config.py` 的 `load_ai_env()` 保持不变（已正确读取 `.ai_env`）

---

## §4 验收标准

### 功能验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| F1 | DeepSeekLLMClient 能调 DeepSeek API | 手动调 `create_graphiti()` + `add_episode`，检查 Neo4j 里有数据 |
| F2 | BgeRerankerClient 能对 passages 排序 | 手动调 `rank(query, passages)`，返回非空排序结果 |
| F3 | BgeM3Embedder async 方法可 await | `await embedder.create("test")` 不报错 |
| F4 | detect_env.py 读 DEEPSEEK_API_KEY | `check-preinstall` 输出含 `_deepseek_api_key` |
| F5 | server.py 搜索传 group_id | 调搜索工具传 group_id，返回结果限定在该 group |
| F6 | fireAndForgetEvent 用 flowId | 子 session 工具执行后，事件写入根 session 的 group |
| F7 | shell.env 注入 OPENSECURITY_FLOW_ID | bash 命令 `echo $OPENSECURITY_FLOW_ID` 输出 flow ID |
| F8 | delete_session_events 清理数据 | 调用后 Neo4j 里该 group 的节点/边/episode 全部删除 |

### 回归验收

| # | 验收项 | 验证方法 |
|---|--------|---------|
| R1 | knowledge MCP 不受影响 | `pytest test/` 全部通过 |
| R2 | 环境检测脚本正常 | `python detect_env.py check-preinstall all` 正常输出 |
| R3 | env-check 单元测试 | `pytest test/env-check/ -v` 全部通过 |
| R4 | plugin 加载正常 | opencode 启动无报错 |

### 架构验收

| # | 验收项 |
|---|--------|
| A1 | 无循环依赖：llm_client.py ← graphiti_config.py ← server.py / write_event_daemon.py |
| A2 | 无硬编码 API key |
| A3 | 环境变量从 .ai_env 读取，支持运行时切换模型（改 .ai_env 即可） |
| A4 | OPENSECURITY_FLOW_ID 在 plugin（写）+ MCP（读）两端一致 |

---

## §5 与现有需求文档的关系

| 文档 | 关系 |
|------|------|
| `2026-07-17-events-writer-daemon.md` | 前置依赖。daemon 已实现，本需求改造 daemon 调用的 `create_graphiti()` |
| `2026-07-15-detect-env-subcommand-refactor.md` | 前置依赖。detect_env.py 子命令已实现，本需求修改其中的 ZHIPU → DEEPSEEK |
| `2026-07-17-install-architecture-simplify.md` | 无直接关系 |
| `2026-07-09-searcher-agent.md` | 间接相关。searcher agent 调 events MCP 搜索，搜索精度提升（group_id 限定）利好 searcher |
