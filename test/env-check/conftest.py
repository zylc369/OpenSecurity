"""detect_env.py + venv.ts 环境检测共享 fixtures。

测试策略：尽量真实，不 mock。
- conda 搜索、venv 路径、编译器检测 → 真实环境
- Python 包检测 → 真实 import（venv 里已装好的包）
- check-preinstall → 真实 subprocess 调 detect_env.py
"""
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DETECT_ENV = PROJECT_ROOT / ".opencode" / "binary-analysis" / "scripts" / "detect_env.py"
SHARED_DIR = PROJECT_ROOT / ".opencode" / "binary-analysis"
VENV_PYTHON = Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python"

# 确保 detect_env.py 可 import
sys.path.insert(0, str(SHARED_DIR / "scripts"))


@pytest.fixture(scope="session")
def detect_env_module():
    """导入 detect_env 模块（session 级复用）。"""
    import detect_env
    return detect_env


@pytest.fixture(scope="session")
def venv_python():
    """venv Python 路径。"""
    if not VENV_PYTHON.exists():
        pytest.skip(f"venv Python 不存在: {VENV_PYTHON}")
    return str(VENV_PYTHON)
