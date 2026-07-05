# -*- coding: utf-8 -*-
"""gui_capture.py 测试共享 fixture。

gui_capture.py 位于 .opencode/binary-analysis/scripts/，非包结构，
用 importlib 按文件路径加载为模块。模块级会 from image_optimize import optimize_for_mcp，
加载前需确保 PIL 已安装（.venv_test 已装 Pillow）。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# gui_capture.py 绝对路径
_CAPTURE_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "gui_capture.py"
)


@pytest.fixture(scope="session")
def cap_mod():
    """加载 gui_capture.py 为模块（session 级共享）。

    模块级代码执行 sys.path.insert + from image_optimize import optimize_for_mcp，
    无副作用（仅导入函数引用）。
    """
    spec = importlib.util.spec_from_file_location("gui_capture", _CAPTURE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def fake_pyautogui(monkeypatch):
    """注入假的 pyautogui 模块到 sys.modules，供 main() 中 `import pyautogui` 使用。

    返回一个 namespace 对象，测试中可设置 screenshot/size 的返回值。
    """
    from types import SimpleNamespace
    from PIL import Image

    fake = SimpleNamespace(
        # 默认返回 100x100 纯色图
        screenshot=lambda: Image.new("RGB", (100, 100), (200, 50, 80)),
        # pyautogui.size() 是函数，返回 (width, height)
        size=lambda: (1920, 1080),
    )
    monkeypatch.setitem(sys.modules, "pyautogui", fake)
    return fake
