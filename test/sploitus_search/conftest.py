# -*- coding: utf-8 -*-
"""sploitus_search.py 测试共享 fixture。

用 importlib 按文件路径加载被测脚本。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "sploitus_search.py"
)


@pytest.fixture(scope="session")
def sploitus():
    """加载 sploitus_search.py 为模块并注册到 sys.modules。"""
    spec = importlib.util.spec_from_file_location("sploitus_search", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["sploitus_search"] = mod
    spec.loader.exec_module(mod)
    return mod
