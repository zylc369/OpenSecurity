"""测试 detect_env.py 子命令端到端：install bootstrap + check-preinstall fail-fast。

不 mock——真实调用 detect_env.py 子进程。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DETECT_ENV = str(PROJECT_ROOT / ".opencode" / "binary-analysis" / "scripts" / "detect_env.py")
VENV_PYTHON = str(Path.home() / "bw-security-analysis" / ".venv" / "bin" / "python")


class TestSubcommandRouting:
    """测试子命令解析和路由。"""

    def test_install_help(self):
        """detect_env.py --help 显示子命令列表。"""
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV, "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "install" in result.stdout
        assert "check-preinstall" in result.stdout

    def test_no_subcommand_errors(self):
        """不带子命令应报错（argparse required subparser）。"""
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0

    def test_invalid_subcommand_errors(self):
        """无效子命令应报错。"""
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV, "foobar"],
            capture_output=True, text=True, timeout=10,
        )
        assert result.returncode != 0


class TestCheckPreinstall:
    """测试 check-preinstall 子命令（真实调用）。"""

    def test_security_analysis_evolve(self):
        """check-preinstall security-analysis-evolve 应返回 JSON。"""
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV, "check-preinstall", "security-analysis-evolve"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert "success" in data
        assert isinstance(data["success"], bool)

    def test_all_agent(self):
        """check-preinstall all 应检测全部依赖。"""
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV, "check-preinstall", "all"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        assert "success" in data
        assert "data" in data

    def test_output_flag(self, tmp_path):
        """--output 写 JSON 到文件。"""
        out_file = tmp_path / "env.json"
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV, "check-preinstall", "security-analysis-evolve",
             "--output", str(out_file)],
            capture_output=True, text=True, timeout=30,
        )
        assert out_file.exists()
        data = json.loads(out_file.read_text())
        assert "success" in data

    def test_fail_fast_returns_install_guide(self):
        """fail-fast 时返回 install_guide 字段。"""
        # 用一个不存在的 agent 测试——不会 fail-fast（无依赖匹配）
        # 改为检测有缺失依赖的 agent
        result = subprocess.run(
            [VENV_PYTHON, DETECT_ENV, "check-preinstall", "binary-analysis"],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        if not data["success"]:
            assert "install_guide" in data
            assert "install.sh" in data["install_guide"] or "install.ps1" in data["install_guide"]


class TestInstallBootstrap:
    """测试 install 子命令的 bootstrap 逻辑（不实际安装，只验证路由）。"""

    def test_install_in_venv_skips_bootstrap(self, detect_env_module):
        """已在 venv 内时 _bootstrap_venv 直接返回。"""
        # 当前测试运行在 venv Python 内
        detect_env_module._bootstrap_venv()  # 不抛异常 = 通过


class TestDeepseekGateLogic:
    """测试 DEEPSEEK_API_KEY 门控逻辑（通过 _detect_mcp_deps 行为）。"""

    def test_deepseek_not_configured_skips_docker(self, detect_env_module, monkeypatch):
        """DEEPSEEK_API_KEY 未配置时 _detect_mcp_deps 跳过 Docker 检查。"""
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
        result = detect_env_module._detect_mcp_deps()
        neo4j = result.get("_neo4j", {})
        assert neo4j.get("available") == False
        assert "DEEPSEEK_API_KEY" in neo4j.get("message", "")

    def test_deepseek_configured_checks_docker(self, detect_env_module, monkeypatch):
        """DEEPSEEK_API_KEY 已配置时 _detect_mcp_deps 检查 Docker。"""
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        result = detect_env_module._detect_mcp_deps()
        neo4j = result.get("_neo4j", {})
        # Docker 可能可用也可能不可用，但不应包含"DEEPSEEK_API_KEY 未配置"
        assert "DEEPSEEK_API_KEY 未配置" not in neo4j.get("message", "")


class TestVenvTs:
    """测试 venv.ts 的导出函数（通过 subprocess 调 bun）。"""

    def test_get_python_cmd_returns_path(self):
        """getPythonCmd 返回 venv Python 路径。"""
        # 通过 bun 执行 TS 代码验证
        bun_script = """
        const { getPythonCmd } = require("./.opencode/plugins/lib/venv");
        const cmd = getPythonCmd();
        if (cmd) { console.log(cmd); } else { console.log("null"); }
        """
        result = subprocess.run(
            ["bun", "-e", bun_script],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        output = result.stdout.strip()
        if output != "null":
            assert "python" in output
            assert ".venv" in output

    def test_get_install_hint_contains_script_path(self):
        """getInstallHint 包含安装脚本路径。"""
        bun_script = """
        const { getInstallHint } = require("./.opencode/plugins/lib/venv");
        console.log(getInstallHint());
        """
        result = subprocess.run(
            ["bun", "-e", bun_script],
            capture_output=True, text=True, timeout=10,
            cwd=str(PROJECT_ROOT),
        )
        hint = result.stdout.strip()
        assert "install" in hint
        assert "安装" in hint or "install" in hint.lower()
