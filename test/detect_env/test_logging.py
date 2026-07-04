# -*- coding: utf-8 -*-
"""_warn 与 _stderr_tail 诊断日志测试。

这两个函数是 detect_env 全部失败诊断的统一出口（收口设计），
覆盖：输出目标（stderr 不污染 stdout）、格式拼接、异常/详情组合、stderr 截断。
"""
from types import SimpleNamespace


class TestWarn:
    """_warn(msg, exc=None, detail=None) 统一 stderr 诊断日志。"""

    def test_message_only(self, env, capsys):
        env._warn("操作失败")
        captured = capsys.readouterr()
        assert captured.err == "[!] 操作失败\n"
        assert captured.out == ""

    def test_with_exception(self, env, capsys):
        env._warn("读取失败", exc=PermissionError("denied"))
        captured = capsys.readouterr()
        assert "[!] 读取失败" in captured.err
        assert "PermissionError" in captured.err
        assert "denied" in captured.err

    def test_with_detail(self, env, capsys):
        env._warn("检测失败", detail="ModuleNotFoundError: No module named 'xxx'")
        captured = capsys.readouterr()
        assert "[!] 检测失败" in captured.err
        assert "ModuleNotFoundError" in captured.err

    def test_with_exception_and_detail(self, env, capsys):
        env._warn("安装失败", exc=OSError("io error"), detail="exit code 1")
        captured = capsys.readouterr()
        assert "安装失败" in captured.err
        assert "OSError" in captured.err
        assert "io error" in captured.err
        assert "exit code 1" in captured.err

    def test_empty_detail_not_appended(self, env, capsys):
        """detail 为空字符串时不追加（避免多余的 ': '）。"""
        env._warn("test", detail="")
        captured = capsys.readouterr()
        assert captured.err == "[!] test\n"

    def test_none_exception_not_appended(self, env, capsys):
        env._warn("test", exc=None)
        captured = capsys.readouterr()
        assert captured.err == "[!] test\n"

    def test_stdout_always_clean(self, env, capsys):
        """_warn 必须只走 stderr——--check-preinstall 模式 Plugin 用 JSON.parse(stdout)，
        任何 stdout 泄漏都会破坏 JSON 解析。"""
        env._warn("diagnostic", exc=ValueError("x"), detail="info")
        captured = capsys.readouterr()
        assert captured.out == ""


class TestStderrTail:
    """_stderr_tail(result) 子进程 stderr 截断（统一截断逻辑，消除魔法值）。"""

    def test_normal(self, env):
        result = SimpleNamespace(stderr="some error output")
        assert env._stderr_tail(result) == "some error output"

    def test_strips_whitespace(self, env):
        result = SimpleNamespace(stderr="  \n  trimmed  \n  ")
        assert env._stderr_tail(result) == "trimmed"

    def test_none_stderr(self, env):
        """stderr 为 None（子进程无错误输出）时返回空字符串。"""
        result = SimpleNamespace(stderr=None)
        assert env._stderr_tail(result) == ""

    def test_empty_stderr(self, env):
        result = SimpleNamespace(stderr="")
        assert env._stderr_tail(result) == ""

    def test_truncates_at_limit(self, env):
        """超过 _STDERR_TAIL 字符的 stderr 被截断到该长度。"""
        limit = env._STDERR_TAIL
        long_stderr = "x" * (limit + 100)  # 确保超过限制
        result = SimpleNamespace(stderr=long_stderr)
        tail = env._stderr_tail(result)
        assert len(tail) == limit
        assert tail == "x" * limit

    def test_under_limit_not_truncated(self, env):
        short = "y" * (env._STDERR_TAIL - 1)
        result = SimpleNamespace(stderr=short)
        assert env._stderr_tail(result) == short
