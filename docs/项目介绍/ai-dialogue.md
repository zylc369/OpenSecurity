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

`--agent` 必传，指定目标模型运行的 agent 上下文（如 `ai-security-analysis`、`build`）。

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
| `ai-security-analysis` | AI 安全分析编排器（编程约束、安全分析工具链） | 测试模型在 AI 安全分析 agent 部署下的行为 |
| `build` | 通用构建 agent（无特定约束） | 测试模型在通用 agent 部署下的行为 |
| 其他自定义 agent | 对应 agent 的上下文 | 测试特定 agent 部署场景 |

## 多轮攻防工作流

```
1. create -t deepseek-v4-pro --agent ai-security-analysis --title "实验"  → 拿到 session_id
2. send -s <id> -p "正常输入"                    → 建立基线
3. send -s <id> -p "轻微注入试探"                → 试探边界
4. send -s <id> -p "加强注入"                    → 逐步引诱
5. send -s <id> -p "最终 payload"               → 发起攻击
6. summarize -s <id>                            → 上下文过长时压缩
7. delete -s <id>                               → 清理会话
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
