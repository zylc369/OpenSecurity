"""共享 fixture — 加载 ai-dialogue.py 模块（文件名含连字符，需 importlib 加载）"""
import importlib.util
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent.parent / ".opencode" / "binary-analysis" / "scripts" / "ai-dialogue.py"


@pytest.fixture(scope="session")
def dialogue():
    """加载 ai-dialogue.py 为模块对象"""
    spec = importlib.util.spec_from_file_location("ai_dialogue", str(_SCRIPT))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _skip_if_no_serve(host="127.0.0.1", port=4096):
    """opencode serve 不可用时跳过测试"""
    import socket
    try:
        with socket.create_connection((host, port), timeout=2):
            pass
    except (ConnectionRefusedError, socket.timeout, OSError):
        pytest.skip(f"opencode serve 不可用 ({host}:{port})")


@pytest.fixture
def serve(dialogue):
    """返回 (module, host, port)，serve 不可用时跳过"""
    _skip_if_no_serve()
    return dialogue, "127.0.0.1", 4096


# 集成测试用的常量
TEST_MODEL = "deepseek-v4-flash"
TEST_PROVIDER = "opencode-go"
TEST_AGENT = "ai-security-analysis"
