# -*- coding: utf-8 -*-
"""start_browser_server.sh 测试共享 fixture。"""
import os
from pathlib import Path

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "start_browser_server.sh"
)


@pytest.fixture
def script_path():
    """返回 start_browser_server.sh 的绝对路径。"""
    return str(SCRIPT_PATH)


@pytest.fixture
def script_content():
    """返回脚本文件内容（用于静态检查）。"""
    with open(SCRIPT_PATH) as f:
        return f.read()
