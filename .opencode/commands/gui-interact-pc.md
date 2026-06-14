---
description: GUI 自动化交互 — 截图、视觉识别、键鼠操作
---

使用 Read 工具读取 `$AGENT_DIR/knowledge-base/gui-automation.md`，按照其中的规范执行用户的 GUI 操作请求。

如果 `$AGENT_DIR` 未设置，从 Plugin 注入的环境信息中提取（环境信息段含"Agent 目录 ($AGENT_DIR)"）。`$PYTHON_CMD` 由 Plugin 保证可用。如果 `$TASK_DIR` 未设置，创建 `~/bw-security-analysis/workspace/gui_<timestamp>/` 作为工作目录，截图放在其中的 `view/` 子目录下。
