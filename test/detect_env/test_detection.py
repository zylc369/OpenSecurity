# -*- coding: utf-8 -*-
"""检测逻辑测试（mock subprocess，不依赖真实环境）。

覆盖：_detect_package（Python 包检测）、_get_tool_version（工具版本）、
_detect_playwright_browser / _post_install_playwright（浏览器检测/安装）、
_install_package（pip 安装）、_check_playwright_post_install（编排）。

所有 subprocess.run 调用用 monkeypatch mock，返回 SimpleNamespace 模拟 CompletedProcess。
"""
from types import SimpleNamespace

import pytest


def _mock_run(returncode=0, stdout="", stderr=""):
    """生成 mock subprocess.run，返回固定结果的 CompletedProcess 模拟。"""
    def runner(cmd, **kwargs):
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)
    return runner


def _mock_timeout():
    """生成始终超时的 mock。"""
    def runner(cmd, **kwargs):
        timeout = kwargs.get("timeout", 10)
        raise __import__("subprocess").TimeoutExpired(cmd, timeout)
    return runner


def _mock_oserror(msg="io error"):
    """生成始终抛 OSError 的 mock。"""
    def runner(cmd, **kwargs):
        raise OSError(msg)
    return runner


class TestDetectPackage:
    """_detect_package(name, version_via) Python 包检测。"""

    def test_available_with_version(self, env, monkeypatch):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0, stdout="1.2.3\n"))
        result = env._detect_package("capstone")
        assert result == {"available": True, "version": "1.2.3"}

    def test_available_importlib_version_via(self, env, monkeypatch):
        """version_via='importlib:PKG' 路径也能正确解析版本。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0, stdout="2.0.0\n"))
        result = env._detect_package("playwright", version_via="importlib:playwright")
        assert result == {"available": True, "version": "2.0.0"}

    def test_returncode_nonzero_unavailable(self, env, monkeypatch):
        """import 失败（returncode≠0）判定为未安装。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(1, stderr="ModuleNotFoundError"))
        result = env._detect_package("nonexistent")
        assert result == {"available": False, "version": None}

    def test_returncode_nonzero_warns(self, env, monkeypatch, capsys):
        """returncode≠0 时 _warn 记录 stderr（区分'未安装'和'包损坏'）。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(1, stderr="ImportError: broken"))
        env._detect_package("broken_pkg")
        captured = capsys.readouterr()
        assert "检测 broken_pkg 失败" in captured.err
        assert "ImportError" in captured.err

    def test_timeout_unavailable(self, env, monkeypatch):
        monkeypatch.setattr(env.subprocess, "run", _mock_timeout())
        result = env._detect_package("slow_pkg")
        assert result == {"available": False, "version": None}

    def test_timeout_warns(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_timeout())
        env._detect_package("slow_pkg")
        captured = capsys.readouterr()
        assert "检测 slow_pkg 超时" in captured.err

    def test_oserror_unavailable(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_oserror())
        result = env._detect_package("any")
        assert result == {"available": False, "version": None}
        captured = capsys.readouterr()
        assert "检测 any 异常" in captured.err


class TestGetToolVersion:
    """_get_tool_version(resolved_path, version_cmd) 工具版本获取。"""

    def test_stdout_version(self, env, monkeypatch):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0, stdout="2.9.3\n"))
        assert env._get_tool_version("/usr/bin/apktool", ["--version"]) == "2.9.3"

    def test_fallback_to_stderr(self, env, monkeypatch):
        """stdout 为空时 fallback 到 stderr 首行。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0, stdout="", stderr="1.5.5\n"))
        assert env._get_tool_version("/usr/bin/jadx", ["--version"]) == "1.5.5"

    def test_empty_version_cmd_returns_none(self, env):
        """version_cmd 为空列表时直接返回 None（不执行子进程）。"""
        assert env._get_tool_version("/usr/bin/tool", []) is None

    def test_returncode_nonzero_returns_none(self, env, monkeypatch):
        """--version 失败（returncode≠0）返回 None（版本未知，best-effort）。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(1, stderr="error"))
        assert env._get_tool_version("/usr/bin/tool", ["--version"]) is None

    def test_timeout_warns(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_timeout())
        env._get_tool_version("/usr/bin/tool", ["--version"])
        captured = capsys.readouterr()
        assert "版本检测超时" in captured.err


class TestDetectPlaywrightBrowser:
    """_detect_playwright_browser() Chromium 浏览器检测。"""

    def test_installed(self, env, monkeypatch):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0, stdout="True\n"))
        assert env._detect_playwright_browser() is True

    def test_not_installed(self, env, monkeypatch):
        """returncode 0 但 stdout 为 False（浏览器文件不存在）。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0, stdout="False\n"))
        assert env._detect_playwright_browser() is False

    def test_failure_warns(self, env, monkeypatch, capsys):
        """启动失败（returncode≠0）记 _warn。"""
        monkeypatch.setattr(env.subprocess, "run", _mock_run(1, stderr="playwright error"))
        assert env._detect_playwright_browser() is False
        captured = capsys.readouterr()
        assert "Playwright 浏览器检测失败" in captured.err

    def test_timeout_returns_false(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_timeout())
        assert env._detect_playwright_browser() is False
        captured = capsys.readouterr()
        assert "检测超时" in captured.err


class TestInstallPackage:
    """_install_package(pip_name) pip 安装。"""

    def test_success(self, env, monkeypatch):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0))
        assert env._install_package("capstone") is True

    def test_failure_warns_with_exitcode(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(1, stderr="permission denied"))
        assert env._install_package("somepkg") is False
        captured = capsys.readouterr()
        assert "pip install somepkg 失败" in captured.err
        assert "退出码 1" in captured.err

    def test_timeout(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_timeout())
        assert env._install_package("bigpkg") is False
        captured = capsys.readouterr()
        assert "pip install bigpkg 超时" in captured.err


class TestPostInstallPlaywright:
    """_post_install_playwright() Chromium 浏览器安装。"""

    def test_success(self, env, monkeypatch):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(0))
        assert env._post_install_playwright() is True

    def test_failure_warns_with_exitcode(self, env, monkeypatch, capsys):
        monkeypatch.setattr(env.subprocess, "run", _mock_run(2, stderr="network error"))
        assert env._post_install_playwright() is False
        captured = capsys.readouterr()
        assert "Playwright 浏览器安装失败" in captured.err
        assert "退出码 2" in captured.err


class TestCheckPlaywrightPostInstall:
    """_check_playwright_post_install(skip_install, errors) 编排：检测→按需安装→记错。"""

    def test_browser_present_no_action(self, env, monkeypatch):
        """浏览器已装时不安装、不报错。"""
        monkeypatch.setattr(env, "_detect_playwright_browser", lambda: True)
        errors = []
        env._check_playwright_post_install(skip_install=False, errors=errors)
        assert errors == []

    def test_browser_absent_skip_install_records_error(self, env, monkeypatch):
        """skip_install + 浏览器缺失 → 记 error（不尝试安装）。"""
        monkeypatch.setattr(env, "_detect_playwright_browser", lambda: False)
        errors = []
        env._check_playwright_post_install(skip_install=True, errors=errors)
        assert len(errors) == 1
        assert "playwright install chromium" in errors[0]

    def test_browser_absent_install_success(self, env, monkeypatch):
        """非 skip + 浏览器缺失 + 安装成功 → 无 error。"""
        monkeypatch.setattr(env, "_detect_playwright_browser", lambda: False)
        monkeypatch.setattr(env, "_post_install_playwright", lambda: True)
        errors = []
        env._check_playwright_post_install(skip_install=False, errors=errors)
        assert errors == []

    def test_browser_absent_install_failure_records_error(self, env, monkeypatch):
        """非 skip + 浏览器缺失 + 安装失败 → 记 error。"""
        monkeypatch.setattr(env, "_detect_playwright_browser", lambda: False)
        monkeypatch.setattr(env, "_post_install_playwright", lambda: False)
        errors = []
        env._check_playwright_post_install(skip_install=False, errors=errors)
        assert len(errors) == 1
        assert "playwright install chromium" in errors[0]
