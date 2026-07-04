# -*- coding: utf-8 -*-
"""依赖声明与工具解析测试。

覆盖：Dependency dataclass（默认值/字段）、_build_install_cmd（pip/conda 命令生成）、
_resolve_tool（env_var 模式如 IDA + PATH which 模式如 apktool）。

_resolve_tool 的 env_var 模式用 tmp_path 创建模拟可执行文件；PATH 模式用 monkeypatch shutil.which。
"""
import pytest


class TestDependency:
    """Dependency dataclass 字段默认值。"""

    def test_python_defaults(self, env):
        dep = env.Dependency(name="capstone", kind="python")
        assert dep.required is True
        assert dep.preinstall is False
        assert dep.agents == []
        assert dep.pip_name is None
        assert dep.installer == "pip"
        assert dep.post_install is False
        assert dep.version_via is None
        assert dep.env_var == ""
        assert dep.executable == ""

    def test_tool_defaults(self, env):
        dep = env.Dependency(name="apktool", kind="tool")
        assert dep.version_cmd == []
        assert dep.env_var == ""
        assert dep.executable == ""
        assert dep.description == ""

    def test_full_fields(self, env):
        dep = env.Dependency(
            name="ida_pro", kind="tool", required=True, preinstall=True,
            agents=["binary-analysis"], description="IDA Pro",
            env_var="IDA_PRO_HOME", executable="idat", version_cmd=["--version"],
            install_hint="hint",
        )
        assert dep.executable == "idat"
        assert dep.env_var == "IDA_PRO_HOME"
        assert dep.agents == ["binary-analysis"]

    def test_sage_entry_matches_design(self, env):
        """验证 PYTHON_PACKAGES 中 sage 条目符合设计意图（可选/conda/crypto-analysis）。"""
        sage = next(d for d in env.PYTHON_PACKAGES if d.name == "sage")
        assert sage.required is False          # 可选，缺失不阻断
        assert sage.preinstall is True
        assert sage.installer == "conda"
        assert sage.agents == ["crypto-analysis"]
        assert sage.conda_name == "sage"


class TestBuildInstallCmd:
    """_build_install_cmd(dep) 根据 installer 字段生成安装命令。"""

    def test_pip_installer(self, env):
        dep = env.Dependency(name="capstone", kind="python", pip_name="capstone", installer="pip")
        cmd = env._build_install_cmd(dep)
        assert "pip install capstone" in cmd

    def test_conda_installer(self, env, monkeypatch):
        monkeypatch.setattr(env.sys, "prefix", "/fake/venv")
        dep = env.Dependency(
            name="sage", kind="python", pip_name="sagemath-standard",
            conda_name="sage", installer="conda",
        )
        cmd = env._build_install_cmd(dep)
        assert "conda install" in cmd
        assert "sage" in cmd
        assert "/fake/venv" in cmd

    def test_conda_uses_conda_name_over_pip_name(self, env, monkeypatch):
        """conda 模式优先用 conda_name 而非 pip_name。"""
        monkeypatch.setattr(env.sys, "prefix", "/fake")
        dep = env.Dependency(
            name="sage", kind="python", pip_name="sagemath-standard",
            conda_name="sage", installer="conda",
        )
        cmd = env._build_install_cmd(dep)
        assert " sage" in cmd
        assert "sagemath-standard" not in cmd

    def test_conda_cmd_env_var(self, env, monkeypatch):
        """CONDA_CMD 环境变量指定自定义 conda 路径。"""
        monkeypatch.setenv("CONDA_CMD", "/custom/conda/bin/conda")
        monkeypatch.setattr(env.sys, "prefix", "/fake")
        dep = env.Dependency(name="x", kind="python", pip_name="x", conda_name="x", installer="conda")
        cmd = env._build_install_cmd(dep)
        assert "/custom/conda/bin/conda" in cmd


class TestResolveTool:
    """_resolve_tool(dep) 工具路径解析（env_var 模式 + PATH which 模式）。"""

    def test_env_var_found(self, env, monkeypatch, tmp_path):
        """env_var 模式：目录存在 + 可执行文件存在 → 找到。"""
        idat = tmp_path / "idat"
        idat.write_text("")
        idat.chmod(0o755)
        monkeypatch.setenv("IDA_PRO_HOME", str(tmp_path))
        dep = env.Dependency(name="ida_pro", kind="tool", env_var="IDA_PRO_HOME", executable="idat")

        path, found = env._resolve_tool(dep)
        assert found is True
        assert str(idat) == path

    def test_env_var_executable_missing(self, env, monkeypatch, tmp_path):
        """env_var 模式：目录存在但可执行文件不存在 → 未找到。"""
        monkeypatch.setenv("IDA_PRO_HOME", str(tmp_path))
        dep = env.Dependency(name="ida_pro", kind="tool", env_var="IDA_PRO_HOME", executable="idat")

        path, found = env._resolve_tool(dep)
        assert found is False
        assert path == ""

    def test_env_var_empty(self, env, monkeypatch):
        """env_var 模式：环境变量未设 → 未找到。"""
        monkeypatch.delenv("IDA_PRO_HOME", raising=False)
        dep = env.Dependency(name="ida_pro", kind="tool", env_var="IDA_PRO_HOME", executable="idat")

        path, found = env._resolve_tool(dep)
        assert found is False

    def test_env_var_empty_executable_safe(self, env, monkeypatch, tmp_path):
        """env_var 模式：executable 为空时不误匹配目录本身（防御短路）。"""
        monkeypatch.setenv("IDA_PRO_HOME", str(tmp_path))
        dep = env.Dependency(name="ida_pro", kind="tool", env_var="IDA_PRO_HOME", executable="")

        path, found = env._resolve_tool(dep)
        assert found is False

    def test_path_which_found(self, env, monkeypatch):
        """PATH 模式：shutil.which 找到 → 返回解析路径。"""
        monkeypatch.setattr(env.shutil, "which", lambda n: f"/usr/bin/{n}" if n == "apktool" else None)
        dep = env.Dependency(name="apktool", kind="tool")

        path, found = env._resolve_tool(dep)
        assert found is True
        assert path == "/usr/bin/apktool"

    def test_path_which_not_found(self, env, monkeypatch):
        """PATH 模式：shutil.which 未找到 → 返回 name 本身 + found=False。"""
        monkeypatch.setattr(env.shutil, "which", lambda n: None)
        dep = env.Dependency(name="nonexistent_tool", kind="tool")

        path, found = env._resolve_tool(dep)
        assert found is False
        assert path == "nonexistent_tool"
