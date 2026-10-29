# -*- coding: utf-8 -*-
"""detect_tools 测试（外部工具唯一清单 + 编译器检测 + CLI 入口）。

覆盖：编译器检测（ToolsScanner）返回结构、EXTERNAL_TOOLS 清单完整性（ida_pro 的
env_var 模式）、平台过滤，以及 CLI 入口存在性（install.sh 第 2 步与知识库提示命令的消费链）。
"""
import os
import subprocess
import sys
from pathlib import Path

SERVICES_DIR = Path(__file__).resolve().parent.parent.parent / ".opencode" / "control" / "backend" / "services"
DETECT_TOOLS_PATH = SERVICES_DIR / "detect_tools.py"


def _import_detect_tools():
    sys.path.insert(0, str(SERVICES_DIR.parent))
    from services import detect_tools
    return detect_tools


class TestDetectCompiler:
    """编译器检测返回结构（开发机应有 clang/gcc）。"""

    def test_returns_shape(self):
        dt = _import_detect_tools()
        c = dt.ToolsScanner.get_instance().detect_compiler()
        assert isinstance(c, dt.CompilerInfo)
        assert isinstance(c.available, bool)

    def test_available_on_dev_machine(self):
        dt = _import_detect_tools()
        c = dt.ToolsScanner.get_instance().detect_compiler()
        assert c.available is True
        assert c.type in ("clang", "gcc", "msvc")


class TestExternalToolsIntegrity:
    """EXTERNAL_TOOLS 清单设计约束。"""

    def test_ida_pro_uses_env_var_mode(self):
        dt = _import_detect_tools()
        ida = next(t for t in dt.EXTERNAL_TOOLS if t.name == "ida_pro")
        assert ida.env_var == "IDA_PRO_HOME"
        assert ida.executable == "idat"
        assert ida.required is True

    def test_optional_tools_exist(self):
        dt = _import_detect_tools()
        names = {t.name for t in dt.EXTERNAL_TOOLS}
        assert {"GoReSym", "ldid"} <= names  # optional 工具在列

    def test_detect_tools_has_no_python_pkg_role(self):
        """工具检测模块不得再承载 Python 包职能（防职能回流）。"""
        dt = _import_detect_tools()
        assert not hasattr(dt, "PYTHON_PACKAGES"), "PYTHON_PACKAGES 应只在 detect_py_deps"
        assert not hasattr(dt, "pip_installable_packages"), "白名单职能应只在 detect_py_deps"


class TestCliEntry:
    """CLI 入口（install.sh 第 2 步 / 知识库提示命令）——防再次静默丢失。"""

    def _run(self, *args: str) -> subprocess.CompletedProcess:
        # 启动方注入模块搜索路径（与 install.sh / env-check 同约定；脚本内无自举）
        env = {**os.environ, "PYTHONPATH": str(SERVICES_DIR.parent)}
        return subprocess.run(
            [sys.executable, str(DETECT_TOOLS_PATH), *args],
            capture_output=True, text=True, timeout=120, env=env,
        )

    def test_help_lists_subcommands(self):
        r = self._run("--help")
        assert r.returncode == 0, r.stderr[-300:]
        assert "install" in r.stdout and "list-installable" in r.stdout

    def test_list_installable_nonempty(self):
        r = self._run("list-installable")
        assert r.returncode == 0, r.stderr[-300:]
        names = set(r.stdout.split())
        assert {"ffuf", "nuclei"} <= names

    def test_install_unknown_tool_fails(self):
        r = self._run("install", "--tool", "__no_such_tool__")
        assert r.returncode == 1
        assert "__no_such_tool__" in r.stdout
