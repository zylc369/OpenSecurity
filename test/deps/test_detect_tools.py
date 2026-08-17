# -*- coding: utf-8 -*-
"""detect_tools 测试（外部工具唯一清单 + 编译器检测）。

覆盖：编译器检测（自 detect_env 迁入）返回结构、EXTERNAL_TOOLS 清单完整性
（ida_pro 的 env_var 模式）、平台过滤。
"""
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parent.parent.parent / ".opencode" / "control" / "backend" / "services"


class TestDetectCompiler:
    """detect_compiler() 返回结构（开发机应有 clang/gcc）。"""

    def test_returns_shape(self):
        sys.path.insert(0, str(SERVICES_DIR.parent))
        from services import detect_tools
        c = detect_tools.detect_compiler()
        from services.detect_tools import CompilerInfo
        assert isinstance(c, CompilerInfo)
        assert isinstance(c.available, bool)

    def test_available_on_dev_machine(self):
        sys.path.insert(0, str(SERVICES_DIR.parent))
        from services import detect_tools
        c = detect_tools.detect_compiler()
        assert c.available is True
        assert c.type in ("clang", "gcc", "msvc")


class TestExternalToolsIntegrity:
    """EXTERNAL_TOOLS 清单设计约束。"""

    def test_ida_pro_uses_env_var_mode(self):
        sys.path.insert(0, str(SERVICES_DIR.parent))
        from services import detect_tools
        ida = next(t for t in detect_tools.EXTERNAL_TOOLS if t.name == "ida_pro")
        assert ida.env_var == "IDA_PRO_HOME"
        assert ida.executable == "idat"
        assert ida.required is True

    def test_optional_tools_exist(self):
        sys.path.insert(0, str(SERVICES_DIR.parent))
        from services import detect_tools
        names = {t.name for t in detect_tools.EXTERNAL_TOOLS}
        assert {"GoReSym", "ldid"} <= names  # optional 工具在列

    def test_detect_tools_has_no_python_pkg_role(self):
        """工具检测模块不得再承载 Python 包职能（防职能回流）。"""
        sys.path.insert(0, str(SERVICES_DIR.parent))
        import services.detect_tools as dt
        assert not hasattr(dt, "PYTHON_PACKAGES"), "PYTHON_PACKAGES 应只在 detect_py_deps"
        assert not hasattr(dt, "pip_installable_packages"), "白名单职能应只在 detect_py_deps"
