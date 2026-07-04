# -*- coding: utf-8 -*-
"""detect_env.py 测试共享 fixture。

detect_env.py 位于 .opencode/binary-analysis/scripts/，非包结构，
用 importlib 按文件路径加载为模块，供各测试文件通过 ``env`` fixture 访问。
"""
import importlib.util
from pathlib import Path

import pytest

# detect_env.py 绝对路径：本文件位于 test/detect_env/，往上三级到工程根，再进 .opencode
_DETECT_ENV_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "detect_env.py"
)


@pytest.fixture(scope="session")
def env():
    """加载 detect_env.py 为模块（session 级共享，避免重复加载）。

    模块级代码仅计算路径常量（AI_ENV_FILE 等），无文件创建副作用，安全。
    测试中通过 ``env._warn`` / ``env._detect_package`` 等访问被测函数。
    若需改写模块级常量（如 AI_ENV_FILE 指向临时目录），用 monkeypatch.setattr(env, ...)。
    """
    spec = importlib.util.spec_from_file_location("detect_env", _DETECT_ENV_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
