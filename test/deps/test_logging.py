# -*- coding: utf-8 -*-
"""_warn 诊断日志测试（安装器的失败诊断统一出口）。

覆盖：输出目标（stderr 不污染 stdout——dry-run/安装日志与未来可能的
机器可读输出不冲突）、格式拼接、异常组合。
"""


class TestWarn:
    """_warn(msg, exc=None)。"""

    def test_message_only(self, py_deps, capsys):
        py_deps._warn("操作失败")
        captured = capsys.readouterr()
        assert captured.err == "[!] 操作失败\n"
        assert captured.out == ""

    def test_with_exception(self, py_deps, capsys):
        py_deps._warn("读取失败", exc=PermissionError("denied"))
        captured = capsys.readouterr()
        assert "[!] 读取失败" in captured.err
        assert "PermissionError" in captured.err
        assert "denied" in captured.err

    def test_log_to_stderr(self, py_deps, capsys):
        """_log 进度日志走 stderr，stdout 保持干净。"""
        py_deps._log("[*] 安装中")
        captured = capsys.readouterr()
        assert captured.err == "[*] 安装中\n"
        assert captured.out == ""
