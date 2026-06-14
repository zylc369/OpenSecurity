**Python 命令**：统一使用 `$PYTHON_CMD`（由 Plugin 在启动时检测并注入，值为 venv Python 绝对路径，含所有第三方包）。所有 Python 脚本调用和内联命令都使用 `$PYTHON_CMD`，不需要区分平台或手动赋值。
