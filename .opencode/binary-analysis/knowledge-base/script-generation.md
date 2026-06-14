# 脚本生成与沉淀规则

> AI 编排器在需要生成新脚本时通过 Read 工具按需加载。

## 何时生成新脚本

当你发现现有 query.py / update.py 无法满足需求时：

1. 先检查沉淀脚本注册表中是否已有可用的脚本
2. 如果没有，生成新的 IDAPython 脚本，遵循以下骨架：

## 脚本骨架

```python
# -*- coding: utf-8 -*-
"""summary: 一句话描述脚本功能

description:
  详细说明用途、参数、调用方式。

level: intermediate
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from _base import env_str, log, run_headless

import ida_funcs
import ida_kernwin
# ... 其他 ida_xxx 模块

def _main():
    # 从环境变量读取参数
    # 执行业务逻辑
    # 返回结果字典
    return {"success": True, "data": {...}, "error": None}

run_headless(_main)
```

> **注意**：沉淀脚本保存在 `scripts/` 子目录，`sys.path.insert` 必须使用 `os.path.dirname(os.path.dirname(...))` 上溯两层到 `_base.py` 所在目录。

## 沉淀流程

新脚本执行成功后，保存到 `scripts/` 目录并更新 `registry.json`：

```json
{
  "name": "<功能名>",
  "file": "<功能名>.py",
  "description": "<功能描述>",
  "params": ["<参数列表>"],
  "example_call": "<示例调用命令>",
  "added_at": "<日期>",
  "verified": true
}
```

## 编码规则（强制）

| 规则 | 正确 | 错误 |
|------|------|------|
| 禁止 `import idc` | `import ida_nalt` | `import idc` |
| 禁止 `import idaapi` | `import ida_funcs` | `import idaapi` |
| 禁止 `from ida_xxx import` | `ida_kernwin.msg("hi")` | `from ida_kernwin import msg` |
| 允许 `from _base import` | `from _base import run_headless` | 自己实现 headless 入口 |
| 字符串用双引号 | `"hello"` | `'hello'` |
| headless 入口在模块级 | `run_headless(_main)` | `if __name__ == "__main__": ...` |
| 日志使用中文 | `log("[*] 正在分析函数: xxx\n")` | `log("analyzing\n")` |
| 输出为 JSON | 写入 `IDA_OUTPUT` 文件 | `print()` |

## 脚本质量保障

沉淀前必须：
1. 基于 `_base.py` 骨架
2. 通过语法检查：`$PYTHON_CMD -c "compile(open('<脚本>').read(), '<脚本>', 'exec')"`
3. 输出符合 `{"success": bool, "data": ..., "error": ...}` 格式
4. 有完整的 docstring
5. 包含中文日志
