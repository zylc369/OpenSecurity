# -*- coding: utf-8 -*-
"""detect_py_deps.py（唯一清单 + 检测 + 安装）测试共享 fixture。

detect_py_deps.py 位于 .opencode/control/backend/services/（依赖体系收口处）。
按文件路径加载（贴近 install.sh 的真实运行方式：无包上下文直接跑）。
"""
import importlib.util
import sys
from pathlib import Path

import pytest

# 工程根：本文件位于 test/deps/，往上两级
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DETECT_PY_DEPS_PATH = PROJECT_ROOT / ".opencode" / "control" / "backend" / "services" / "detect_py_deps.py"


@pytest.fixture(scope="session")
def py_deps():
    """detect_py_deps.py 模块（清单+检测+安装一体）。模块级仅算路径常量，无副作用。"""
    spec = importlib.util.spec_from_file_location("detect_py_deps_under_test", DETECT_PY_DEPS_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["detect_py_deps_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod
