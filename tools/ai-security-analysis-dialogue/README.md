# AI Security Analysis Dialogue

通过 OpenCode serve API 与目标模型进行多轮对话的 CLI 工具，用于 AI 安全分析中的攻防交互。

## 前置条件

OpenCode serve 需要在本地运行（默认 `127.0.0.1:4096`）。当你在 OpenCode 中使用此工具时，它已经在运行。

## 命令

所有命令输出 JSON 到 stdout。

### create — 创建会话

```bash
python3 tools/ai-security-analysis-dialogue/main.py create -t <模型ID> --provider opencode-go --title "会话标题"
```

返回 `session_id`，后续用同一个 ID 多次 `send` 即为多轮对话。

### send — 发送消息（多轮对话核心）

```bash
python3 tools/ai-security-analysis-dialogue/main.py send -s <session_id> -p "消息内容"
```

同一个 `session_id` 多次调用，OpenCode 自动维护上下文。

### chat — 一次性对话

```bash
python3 tools/ai-security-analysis-dialogue/main.py chat -t <模型ID> --provider opencode-go -p "消息"
```

自动创建会话、发送消息、删除会话。适合单次测试。

### list — 列出会话

```bash
python3 tools/ai-security-analysis-dialogue/main.py list
```

### messages — 查看会话历史

```bash
python3 tools/ai-security-analysis-dialogue/main.py messages -s <session_id>
```

### summarize — 压缩上下文

```bash
python3 tools/ai-security-analysis-dialogue/main.py summarize -s <session_id>
```

对话轮次较多时使用，防止 token 超限。

### delete — 删除会话

```bash
python3 tools/ai-security-analysis-dialogue/main.py delete -s <session_id>
```

## 多轮攻防工作流

```
1. create -t kimi-k2.6 --title "注入实验"      → 拿到 session_id
2. send -s <id> -p "正常输入"                    → 建立基线
3. send -s <id> -p "轻微注入试探"                → 试探边界
4. send -s <id> -p "加强注入"                    → 逐步引诱
5. send -s <id> -p "最终 payload"               → 发起攻击
6. summarize -s <id>                            → 上下文过长时压缩
7. delete -s <id>                               → 清理会话
```

## 通用参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `127.0.0.1` | OpenCode serve 地址 |
| `--port` | `4096` | OpenCode serve 端口 |

## 可用模型

### opencode-go 供应商

| 模型 ID | 名称 | API 格式 |
|---------|------|----------|
| `deepseek-v4-flash` | DeepSeek V4 Flash | OpenAI |
| `deepseek-v4-pro` | DeepSeek V4 Pro | OpenAI |
| `glm-5` | GLM-5 | OpenAI |
| `glm-5.1` | GLM-5.1 | OpenAI |
| `kimi-k2.5` | Kimi K2.5 | OpenAI |
| `kimi-k2.6` | Kimi K2.6 | OpenAI |
| `mimo-v2.5` | MiMo V2.5 | OpenAI |
| `mimo-v2.5-pro` | MiMo V2.5 Pro | OpenAI |
| `minimax-m2.5` | MiniMax M2.5 | Anthropic |
| `minimax-m2.7` | MiniMax M2.7 | Anthropic |
| `qwen3.6-plus` | Qwen3.6 Plus | Anthropic |
| `qwen3.7-max` | Qwen3.7 Max | Anthropic |

使用方式：`-t <模型ID> --provider opencode-go`
