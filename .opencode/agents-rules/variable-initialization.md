环境信息由 Plugin 在每轮注入（见系统提示中的"环境信息"段）。在首次需要执行脚本的 bash 命令中，从环境信息提取路径赋值：

| 变量 | 来源 | 说明 |
|------|------|------|
| `$AGENT_DIR` | 环境信息"Agent 目录 ($AGENT_DIR)" | 本 Agent 的工具目录 |
| `$SHARED_DIR` | 环境信息"共享目录 ($SHARED_DIR)" | 共享分析能力目录 |
| `$IDAT` | 环境信息"IDA Pro"路径 + `/idat` | 需检查文件存在性 |

`$PYTHON_CMD` 由 Plugin 保证可用（venv Python 绝对路径，含所有第三方包），无需手动赋值。所有 Python 脚本和内联命令统一使用 `$PYTHON_CMD`。

**环境信息缺失时**：如果系统提示中未看到"环境信息"段（即找不到 `$OPENCODE_ROOT` 的值），**必须立即终止执行**，告知用户"分析环境初始化失败，请检查 Plugin 是否正常加载"。禁止猜测路径（如 `~/.config/opencode/` 或 `.opencode/`），猜测路径会导致使用错误的知识库和脚本。
