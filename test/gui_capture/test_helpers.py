# -*- coding: utf-8 -*-
"""_parse_args / _fail / _log 辅助函数测试。

覆盖：参数解析（必填/默认值）、_fail 输出 JSON + exit 2、_log 走 stderr。
"""
import json

import pytest


class TestParseArgs:
    """_parse_args() 命令行参数解析。"""

    def test_required_output_dir(self, cap_mod, monkeypatch):
        """--output-dir 是必填参数。"""
        monkeypatch.setattr("sys.argv", ["gui_capture.py", "--output-dir", "/tmp/out"])
        args = cap_mod._parse_args()
        assert args.output_dir == "/tmp/out"

    def test_missing_output_dir_exits(self, cap_mod, monkeypatch):
        """缺少 --output-dir 时 argparse 报错退出（exit code 2）。"""
        monkeypatch.setattr("sys.argv", ["gui_capture.py"])
        with pytest.raises(SystemExit) as exc_info:
            cap_mod._parse_args()
        assert exc_info.value.code == 2

    def test_default_name(self, cap_mod, monkeypatch):
        """--name 默认值为 'screenshot'。"""
        monkeypatch.setattr("sys.argv", ["gui_capture.py", "--output-dir", "/tmp/out"])
        args = cap_mod._parse_args()
        assert args.name == "screenshot"

    def test_custom_name(self, cap_mod, monkeypatch):
        """--name 可指定自定义名称。"""
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", "/tmp/out", "--name", "step1_initial"
        ])
        args = cap_mod._parse_args()
        assert args.name == "step1_initial"


class TestFail:
    """_fail(error) 输出错误 JSON 到 stdout 并 exit(2)。"""

    def test_outputs_error_json(self, cap_mod, capsys):
        """_fail 输出 {"success": false, "error": ...} 到 stdout。"""
        with pytest.raises(SystemExit) as exc_info:
            cap_mod._fail("test error")
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert result["error"] == "test error"

    def test_chinese_error(self, cap_mod, capsys):
        """中文错误信息正确输出（ensure_ascii=False）。"""
        with pytest.raises(SystemExit):
            cap_mod._fail("创建目录失败")
        captured = capsys.readouterr()
        assert "创建目录失败" in captured.out


class TestLog:
    """_log(msg) 进度日志走 stderr（不污染 stdout 的 JSON）。"""

    def test_log_to_stderr(self, cap_mod, capsys):
        cap_mod._log("[*] 正在截图...")
        captured = capsys.readouterr()
        assert captured.out == ""          # stdout 纯净
        assert "[*] 正在截图..." in captured.err
