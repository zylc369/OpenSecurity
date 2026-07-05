# -*- coding: utf-8 -*-
"""mobile_screenshot.py 测试共享 fixture。

mobile_screenshot.py 位于 .opencode/mobile-analysis/scripts/，非包结构，
用 importlib 按文件路径加载为模块。

模块级会 from library import adb + from image_optimize import optimize_for_mcp，
加载前需确保 PIL 已安装（.venv_test 已装 Pillow）+ library 包可导入。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# mobile_screenshot.py 绝对路径
_SCREEN_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "mobile-analysis" / "scripts" / "mobile_screenshot.py"
)


@pytest.fixture(scope="session")
def shot_mod():
    """加载 mobile_screenshot.py 为模块（session 级共享）。

    模块级代码执行 sys.path.insert + from library import adb + from image_optimize import ...，
    无副作用（仅导入函数引用）。
    """
    spec = importlib.util.spec_from_file_location("mobile_screenshot", _SCREEN_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
