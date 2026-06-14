# -*- coding: utf-8 -*-
"""summary: 以非交互模式调用 OpenCode 执行提示词

description:
  通过 subprocess 调用 `opencode run [提示词]`，以非交互模式运行 OpenCode。
  检测命令执行成功或失败，返回结构化结果。

  使用方式：

    # 命令行调用
    python ai/opencode.py "解释这个函数的作用"

    # 作为模块导入
    from ai.opencode import run_opencode
    result = run_opencode("解释这个函数的作用")
    # result = {"success": True, "message": "..."}

level: beginner
"""

import json
import subprocess
import sys


def run_opencode(prompt):
    """以非交互模式运行 OpenCode。

    Args:
        prompt: 传给 opencode run 的提示词字符串。

    Returns:
        dict: 结构化结果，包含以下字段：
            - success (bool): 命令是否执行成功（返回码为 0）。
            - message (str): 命令的标准输出；失败时包含标准错误信息。
    """
    cmd = ["opencode", "run", prompt]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "message": "opencode 命令未找到，请确认已安装并加入 PATH",
        }
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "message": "opencode 执行超时（300秒）",
        }

    if result.returncode == 0:
        return {
            "success": True,
            "message": result.stdout.strip(),
        }

    error_parts = []
    if result.stdout.strip():
        error_parts.append(result.stdout.strip())
    if result.stderr.strip():
        error_parts.append(result.stderr.strip())

    return {
        "success": False,
        "message": "\n".join(error_parts) if error_parts else f"opencode 退出码: {result.returncode}",
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "message": "用法: python ai/opencode.py <提示词>",
        }, ensure_ascii=False, indent=2))
        sys.exit(1)

    prompt_text = sys.argv[1]
    output = run_opencode(prompt_text)
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if not output["success"]:
        sys.exit(1)
