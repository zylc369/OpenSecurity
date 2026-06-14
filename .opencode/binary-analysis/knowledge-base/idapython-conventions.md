# IDAPython 脚本编码规范

> 适用于 `.opencode/binary-analysis/` 下的所有 IDAPython 脚本（query.py、update.py、scripts/*.py）。
> 纯 Python 脚本（detect_env.py、gui_verify.py）和项目其他模块（ai/、test/）不受此限制。

## 导入规则

| 规则 | 说明 | 正确 | 错误 |
|------|------|------|------|
| 禁止 `import idc` | 语义模糊 | `import ida_nalt` | `import idc` |
| 禁止 `import idaapi` | 隐藏符号来源 | `import ida_funcs` | `import idaapi` |
| 禁止 `from ida_xxx import Y` | 必须通过模块前缀引用 | `ida_kernwin.msg("hi")` | `from ida_kernwin import msg` |
| `ida_idaapi` 仅引用常量 | 如 BADADDR | `ida_idaapi.BADADDR` | `ida_idaapi.get_inf_structure()` |
| 字符串用双引号 | 所有字符串字面量 | `"hello"` | `'hello'` |

**例外**：允许 `from _base import ...` 和 `from _utils import ...`。f-string 内嵌引号可用单引号。

## 日志规范

```python
ida_kernwin.msg(f"[*] 正在执行某操作: {detail}\n")   # 进行中
ida_kernwin.msg(f"[+] 操作成功: {result}\n")          # 成功
ida_kernwin.msg(f"[!] 警告或错误: {reason}\n")         # 警告/失败
```

**要求**：
- 每个关键步骤必须有 `[*]` 日志
- 成功和失败都要有对应日志（`[+]` / `[!]`）
- 日志内容使用中文，包含足够上下文（函数名、地址、路径等）
- 无头模式下日志是唯一排查手段，尤为重要

## 代码风格

- 内部辅助函数以 `_` 前缀标记
- 禁止空 `except` 块（`except: pass`）
- 捕获异常后必须处理：抛出 / 记录完整堆栈 / 返回清晰错误
- 函数返回 `True/False` 表示成功/失败
- 新脚本必须有 docstring 头部：`"""summary: ...\ndescription: ...\nlevel: ..."""`
- headless 入口逻辑必须在模块级执行（不能放在 `if __name__ == "__main__"` 内）
  - 原因：IDA 通过 `exec(code, g)` 执行 `-S` 指定的脚本，`__name__` 被设为脚本文件名而非 `"__main__"`
