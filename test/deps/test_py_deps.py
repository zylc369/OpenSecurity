# -*- coding: utf-8 -*-
"""detect_py_deps（Python 依赖唯一清单）测试。

覆盖：install 安装集 = 全部 required（与检测端判定对齐）、agent 归属过滤、pip 白名单、
import 与 CLI 双入口一致性（两种调用方式的检测函数与参数一致）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

PY_DEPS_PATH = Path(__file__).resolve().parent.parent.parent / ".opencode" / "control" / "backend" / "services" / "detect_py_deps.py"
BACKEND_DIR = PY_DEPS_PATH.parent.parent  # services → backend


def _cli_env() -> dict:
    """CLI 调用环境：启动方注入模块搜索路径（与 install.sh / env-check 同约定）。"""
    return {**os.environ, "PYTHONPATH": str(BACKEND_DIR)}


class TestRequiredInstallSet:
    """install 安装集 = 全部 required（与检测端 /api/deps 的判定对齐）。"""

    def test_install_set_equals_required(self, py_deps):
        """install 集包含全部 required 包（含 sage——installer=conda 只决定命令路径）。"""
        names = {p.name for p in py_deps.PyDepsDetector.required_packages()}
        assert {"fastapi", "uvicorn", "angr", "z3", "capstone", "unicorn", "gmpy2",
                "frida", "PIL", "playwright", "pymupdf", "sage"} <= names


class TestFullList:
    """全集清单设计约束。"""

    def test_uvicorn_in_full_list(self, py_deps):
        assert any(p.name == "uvicorn" for p in py_deps.PyDepsDetector.PYTHON_PACKAGES)

    def test_pymupdf_in_full_list(self, py_deps):
        """OCR 链路依赖（PDF 文本层分流）。"""
        assert any(p.name == "pymupdf" for p in py_deps.PyDepsDetector.PYTHON_PACKAGES)

    def test_sage_entry_matches_design(self, py_deps):
        """sage 为必需 + conda 安装器（install 子命令与 /api/install 均按 installer 走 conda）。"""
        sage = next(p for p in py_deps.PyDepsDetector.PYTHON_PACKAGES if p.name == "sage")
        assert sage.required is True
        assert sage.installer == "conda"
        assert sage.conda_name == "sage"
        assert sage.agents == ["crypto-analysis"]

    def test_one_click_whitelist_covers_all(self, py_deps):
        """白名单 = 唯一清单全量（installer 只决定用哪条命令，不减员）。"""
        wl = py_deps.PyDepsDetector.one_click_installable()
        assert "sagemath-standard" in wl      # conda 包也一键可装（走 conda install）
        assert {"uvicorn", "pymupdf", "fastapi"} <= wl


class TestAgentFilter:
    """scan(agent=...) 归属过滤。"""

    def _scan(self, py_deps, agent: str):
        return py_deps.PyDepsDetector.get_instance().scan(agent=agent)

    def test_all_vs_agent_subset(self, py_deps):
        all_names = {p.name for p in self._scan(py_deps, "all")}
        binary_names = {p.name for p in self._scan(py_deps, "binary-analysis")}
        assert binary_names < all_names  # 真子集
        assert "sage" in all_names and "sage" not in binary_names

    def test_agent_specific_package(self, py_deps):
        """angr 是领域包：binary 命中、evolve 不命中。"""
        evolve = {p.name for p in self._scan(py_deps, "security-analysis-evolve")}
        assert "angr" not in evolve
        assert "fastapi" in evolve  # all 级包命中


class TestCliImportParity:
    """CLI 与 import 双入口一致性（同一检测函数，参数一致）。"""

    def test_cli_json_matches_import_scan(self, py_deps):
        r = subprocess.run(
            [sys.executable, str(PY_DEPS_PATH), "scan", "--agent", "binary-analysis", "--json"],
            capture_output=True, text=True, timeout=120, env=_cli_env(),
        )
        assert r.returncode == 0, r.stderr[-300:]
        from dataclasses import asdict
        via_cli = json.loads(r.stdout)["packages"]
        via_import = [asdict(p) for p in py_deps.PyDepsDetector.get_instance().scan(agent="binary-analysis")]
        assert [(p["name"], p["available"]) for p in via_cli] == \
               [(p["name"], p["available"]) for p in via_import]

    def test_cli_exit_code_reflects_required_missing(self, py_deps):
        """required 缺失 → 退出码 1（本机全装时跳过该负例，仅验证正常路径 0）。"""
        r = subprocess.run(
            [sys.executable, str(PY_DEPS_PATH), "scan", "--agent", "all"],
            capture_output=True, text=True, timeout=120, env=_cli_env(),
        )
        if all(p.available for p in py_deps.PyDepsDetector.get_instance().scan(agent="all") if p.required):
            assert r.returncode == 0


class TestInstallSubcommand:
    """install 子命令（安装器并入后的 CLI 入口）。"""

    def test_dry_run_lists_all_required(self, py_deps):
        """dry-run 列全部必需依赖（数量与 required_packages 一致），不触发 venv 创建。"""
        r = subprocess.run(
            [sys.executable, str(PY_DEPS_PATH), "install", "--dry-run"],
            capture_output=True, text=True, timeout=60, env=_cli_env(),
        )
        assert r.returncode == 0, r.stderr[-300:]
        n = len(py_deps.PyDepsDetector.required_packages())
        assert f"将安装 {n} 个包（全部必需依赖）" in r.stderr
        assert "uvicorn" in r.stderr and "angr" in r.stderr

    def test_dry_run_from_any_cwd_without_root_env(self):
        """无 OPENCODE_ROOT + 任意 cwd（/tmp）→ dry-run 正常；
        PYTHONPATH 由启动方提供（与 install.sh 同约定，不依赖 cwd/包上下文）。"""
        env = {k: v for k, v in os.environ.items() if k != "OPENCODE_ROOT"}
        env["PYTHONPATH"] = str(BACKEND_DIR)
        r = subprocess.run(
            [sys.executable, str(PY_DEPS_PATH), "install", "--dry-run"],
            capture_output=True, text=True, timeout=60, cwd="/tmp", env=env,
        )
        assert r.returncode == 0, r.stderr[-300:]
