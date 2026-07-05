# ai-dialogue — 通用 AI 对话工具

通过 opencode serve 与目标模型进行多轮对话的 CLI 工具。

## 前置条件

opencode serve 需要在本地运行（默认 `127.0.0.1:4096`）。在 opencode 中使用时已在运行。

## 命令

所有命令输出 JSON 到 stdout。

### create — 创建会话

```bash
python ai-dialogue.py create -t <模型ID> --agent <agent> --provider opencode-go --title "会话标题"
```

返回 `session_id`，后续用同一个 ID 多次 `send` 即为多轮对话。

`--agent` 必传，指定目标模型运行的 agent 上下文（推荐 `build`；如 `ai-security-analysis`）。

### send — 发送消息（多轮对话核心）

```bash
python ai-dialogue.py send -s <session_id> -p "消息内容"
```

同一个 `session_id` 多次调用，opencode 自动维护上下文。

### chat — 一次性对话

```bash
python ai-dialogue.py chat -t <模型ID> --agent <agent> -p "消息"
```

自动创建会话、发送消息、删除会话。适合单次测试。

### list — 列出会话

```bash
python ai-dialogue.py list
```

### messages — 查看会话历史

```bash
python ai-dialogue.py messages -s <session_id>
```

### summarize — 压缩上下文

```bash
python ai-dialogue.py summarize -s <session_id>
```

对话轮次较多时使用，防止 token 超限。

### delete — 删除会话

```bash
python ai-dialogue.py delete -s <session_id>
```

### scan — 批量探测

按策略文件多轮对话，一次跑完返回聚合 JSON。适合基线探测、多向量初扫等可预先结构化的场景。

策略文件（JSON）：

```json
{
  "target_model": "deepseek-v4-pro",
  "provider": "opencode-go",
  "agent": "build",
  "stages": [
    {"name": "baseline", "prompts": ["正常问题1"]},
    {"name": "injection", "prompts": ["payload1"]}
  ]
}
```

```bash
python ai-dialogue.py scan --strategy <策略文件.json> [--output <结果.json>]
```

自动创建会话、按 stages 顺序发送、收集回复、删除会话，输出聚合 JSON（每条含 stage/prompt/reply）。

## 通用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | opencode serve 地址 |
| `--port` | `4096` | opencode serve 端口 |
| `--timeout` | `600` | HTTP 请求超时秒数（模型生成长内容时可调大） |

## --agent 参数说明

`--agent` 决定目标模型运行的 agent 上下文，包括 system prompt、工具链、规则。不同 agent 的行为差异：

| agent | 上下文 | 适用场景 |
|-------|--------|---------|
| `build`（推荐） | 通用 agent，无自定义 system prompt（裸模型基线） | 测模型本身的安全防线，不注入额外指令 |
| `ai-security-analysis` | AI 安全分析编排器（含越狱方法论、攻击工具链） | 测试模型部署为安全分析 agent 时的行为 |
| 其他自定义 agent | 对应 agent 的上下文 | 测试特定 agent 部署场景 |

## 多轮攻防工作流

根据攻击目标自主选择工具组合：

- **广度扫描**：`scan`（策略文件批量探测，适合基线/多向量初扫）
- **深度突破**：`create` + 多次 `send`（适合逐轮动态调整）

```
1. scan（基线 + 多向量初扫）→ 聚合 JSON，识别薄弱方向
2. create -t <模型> --agent build --title "实验"  → session_id
3. send -s <id> -p "渐进式注入"  → 突破防线
4. summarize -s <id>             → 上下文过长时压缩
5. delete -s <id>                → 清理会话
```

## 可用模型

### opencode-go 供应商

| 模型 ID | 名称 |
|---------|------|
| `deepseek-v4-flash` | DeepSeek V4 Flash |
| `deepseek-v4-pro` | DeepSeek V4 Pro |
| `glm-5` | GLM-5 |
| `glm-5.1` | GLM-5.1 |
| `kimi-k2.5` | Kimi K2.5 |
| `kimi-k2.6` | Kimi K2.6 |
| `mimo-v2.5` | MiMo V2.5 |
| `mimo-v2.5-pro` | MiMo V2.5 Pro |
| `minimax-m2.5` | MiniMax M2.5 |
| `minimax-m2.7` | MiniMax M2.7 |
| `qwen3.6-plus` | Qwen3.6 Plus |
| `qwen3.7-max` | Qwen3.7 Max |

使用方式：`-t <模型ID> --provider opencode-go`
