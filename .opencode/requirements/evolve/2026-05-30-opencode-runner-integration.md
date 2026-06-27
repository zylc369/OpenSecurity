# 需求：ai-security-analysis 集成 opencode-runner 靶场

## §1 背景与目标

**来源**：`docs/需求/需求-创建AI安全的大模型靶场.md` 已落地为 `tools/opencode-runner/`。但 `ai-security-analysis` agent 的 prompt 完全不知道 opencode-runner 的存在，靶场等于白建。

**痛点**：
- agent 只能通过 `deepseek_client.py` / `llm_sim.py` 调 DeepSeek，无法攻击其他模型
- 无法利用攻击/目标双角色分离的能力
- 无法进行多轮持续攻击实验

**预期收益**：
- 上下文：+约 45 行 prompt（252 → ~297 行，远低于 450 行阈值）
- 轮次：多轮攻击场景直接用 server 模式，不需要每次手动构造完整消息历史
- 准确度：攻击/目标双角色分离，攻击更精准；支持 12 种目标模型

---

## §2 技术方案

### 2.1 修改文件清单

| # | 文件 | 改动类型 | 说明 |
|---|------|---------|------|
| 1 | `.opencode/agents/ai-security-analysis.md` | 编辑 | 1) 工具表新增 opencode-runner 行 2) 新增"大模型靶场"子节 3) 新增工具选择指引 4) 安全规则新增单实例约束 |

### 2.2 不修改的文件

- `tools/opencode-runner/` — 靶场代码本身不变
- `ai-security-analysis/scripts/` — 现有 deepseek_client / llm_sim 不变，与新工具共存

### 2.3 opencode-runner 接口摘要

**位置**：`<项目根>/tools/opencode-runner/main.py`

**CLI 参数**：
- `-t / --target-model`（必需）：目标模型，格式 `opencode-go/<model-id>`
- `-a / --attack-model`（可选）：攻击模型，格式同上
- `-m / --mode`：`single`（一次性）| `multi`（HTTP 服务器）
- `-p / --prompt`：single 模式的提示词
- `--port`：multi 模式端口（默认 9876）
- `--host`：multi 模式地址（默认 127.0.0.1）

**可用模型**（12 种）：
`opencode-go/glm-5.1`, `opencode-go/glm-5`, `opencode-go/kimi-k2.5`, `opencode-go/kimi-k2.6`, `opencode-go/deepseek-v4-pro`, `opencode-go/deepseek-v4-flash`, `opencode-go/mimo-v2.5`, `opencode-go/mimo-v2.5-pro`, `opencode-go/minimax-m2.7`, `opencode-go/minimax-m2.5`, `opencode-go/qwen3.7-max`, `opencode-go/qwen3.6-plus`

**Multi 模式 HTTP API**（默认 `http://127.0.0.1:9876`）：
- `GET /health` → `{"status": "ok", "sessions": N, ...}`
- `POST /prompt` → `{"content": "...", "model": "target"|"attack"}` → `{"content": "...", "model": "..."}`
- `POST /attack` → `{"intent": "..."}` → `{"attack_prompt": "...", "target_response": "..."}`
- `POST /session/new` → `{"session_id": "..."}`
- `POST /shutdown` → `{"status": "ok"}`

**API Key**：自动从 `.privacy-data/privacy-data.json` 的 `apiKey.opencodeGo` 读取，无需手动传参。

---

## §3 实现规范

### §3.1 实施步骤拆分

**步骤 1. 工具表新增 opencode-runner + 新增"大模型靶场"子节**
  - 文件: `.opencode/agents/ai-security-analysis.md`
  - 位置: 在"AI 安全工具"表格（第 153-158 行）新增一行；在"AI 分析辅助库"小节（第 160 行）之前插入"大模型靶场 (opencode-runner)"子节
  - 预估行数: 新增约 45 行
  - 验证点: Read 文件确认内容正确，计算展开后行数 < 450
  - 依赖: 无

**步骤 2. 安全规则新增单实例约束**
  - 文件: `.opencode/agents/ai-security-analysis.md`
  - 位置: "安全规则"节（第 248 行起）
  - 预估行数: 新增约 5 行
  - 验证点: Read 文件确认安全规则完整
  - 依赖: 步骤 1

### §3.2 具体内容设计

**步骤 1 新增的工具表行**（插入第 158 行之后）：

```
| opencode-runner | 大模型靶场（攻击任意 LLM） | `$PYTHON_CMD tools/opencode-runner/main.py -t opencode-go/<model> -a opencode-go/<model> -m multi --port 9876 &` |
```

**步骤 1 新增的"大模型靶场"子节**（插入第 160 行之前，即"AI 分析辅助库"之前）：

内容包含：
1. opencode-runner 简介（一句话）
2. 工具选择指引表格（什么场景用什么工具）
3. 启动前检查（curl /health）
4. 常用命令示例（single/multi 启动/curl 调用各端点）
5. 多轮攻击流程示例

**步骤 2 新增的安全规则**：

```
- **opencode-runner 单实例约束**：启动前必须 `curl -sf http://127.0.0.1:9876/health` 检查是否已有实例。如果已存在则复用，绝对禁止启动多个实例导致内存泄漏
- **opencode-runner 使用完毕必须 shutdown**：分析结束后 `POST /shutdown` 关闭服务器，或由用户手动终止进程
```

---

## §4 验收标准

### 4.1 功能验收

- [ ] agent prompt 中包含 opencode-runner 工具表行
- [ ] agent prompt 中包含"大模型靶场"子节，含启动前检查、命令示例、工具选择指引
- [ ] agent prompt 安全规则中包含单实例约束
- [ ] agent prompt 展开后 < 450 行

### 4.2 回归验收

- [ ] 现有工具描述（deepseek_client / llm_sim / curl）无变化
- [ ] 现有知识库索引无变化
- [ ] 不影响其他 agent

### 4.3 架构验收

- [ ] opencode-runner 仍在 `tools/opencode-runner/`，不移动到 `.opencode/`
- [ ] prompt 中的路径引用使用 `$PYTHON_CMD tools/opencode-runner/main.py`（项目根相对路径）
- [ ] 不引入新的文件依赖

---

## §5 与现有需求文档的关系

本需求依赖 `2026-05-30-ai-security-analysis-agent.md`（创建了 ai-security-analysis agent）。本需求仅修改该 agent 的 prompt，不修改其脚本或知识库。
