# 进度: 全面统一 DATA_DIR → OPENSECURITY_HOME

> 需求: `2026-09-28-opensecurity-home-full-rename.md`
> 来源: 用户指令（撤除兼容别名，全面统一）

## 步骤状态

| 步骤 | 内容 | 状态 | 验证 |
|------|------|------|------|
| S1 | 脚本替换（36 文件 179 处） | ☑ | 零残留 |
| S2 | 手工清理 6 处 | ☑ | 伪影扫描零 |
| S3 | 语法与沙箱 | ☑ | bun build ×5；py_compile ×31；新名生效/旧名忽略 |
| S4 | 测试套件 | ☑ | test_control 87 passed；test_integration 6 passed |
| S5 | 新进程端到端 | ☑ | 注入/环境段/控制台/4×MCP 全绿 |
| S6 | 终态复扫 | ☑ | 代码/测试/文档零残留；记录仅史实 |

## as-built 记录

- 替换方式：Python 脚本三形态正则替换（`DATA_DIR`→`OPENSECURITY_HOME`；`(?<![A-Za-z0-9])data_dir(?![A-Za-z0-9_])`→`opensecurity_home`；同理 camel），36 文件 179 处一次到位。
- 手工修复：constants 读链重写；config_manager 兼容常量和读取链删除、docstring×2；security-analysis 注释。
- 验证证据：`bun build`（security-analysis/control-manager/mcp-manager/test-control/constants）；`py_compile` 31 文件；沙箱实测（`OPENSECURITY_HOME=/tmp/oh2` 生效、`DATA_DIR=/tmp/dd` 被忽略回默认）；`test_control.py` 87 passed、`test_integration.py` 6 passed；新进程诊断会话（bash 注入 + 环境信息段逐字 + 控制台复用 + 4×MCP 注册）；全仓复扫零残留。
- 既有问题（非本变更）：`test_control.py:75` / `test_integration.py:48` 的 `def test(name)` 助手函数被 pytest 收集为用例（各 1 collection error）。
