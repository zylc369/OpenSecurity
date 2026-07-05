# -*- coding: utf-8 -*-
"""_parse_args / _fail / _log 辅助函数测试。"""
import json

import pytest


class TestParseArgs:
    """_parse_args() 命令行参数解析。"""

    def test_required_output_dir(self, shot_mod, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mobile_screenshot.py", "--output-dir", "/tmp/out"])
        args = shot_mod._parse_args()
        assert args.output_dir == "/tmp/out"

    def test_missing_output_dir_exits(self, shot_mod, monkeypatch):
        """缺少 --output-dir 时 argparse 报错退出。"""
        monkeypatch.setattr("sys.argv", ["mobile_screenshot.py"])
        with pytest.raises(SystemExit) as exc_info:
            shot_mod._parse_args()
        assert exc_info.value.code == 2

    def test_default_name(self, shot_mod, monkeypatch):
        monkeypatch.setattr("sys.argv", ["mobile_screenshot.py", "--output-dir", "/tmp/out"])
        args = shot_mod._parse_args()
        assert args.name == "screenshot"

    def test_default_serial_none(self, shot_mod, monkeypatch):
        """--serial 默认为 None（自动检测）。"""
        monkeypatch.setattr("sys.argv", ["mobile_screenshot.py", "--output-dir", "/tmp/out"])
        args = shot_mod._parse_args()
        assert args.serial is None

    def test_custom_serial(self, shot_mod, monkeypatch):
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", "/tmp/out", "--serial", "emulator5554"
        ])
        args = shot_mod._parse_args()
        assert args.serial == "emulator5554"


class TestFail:
    """_fail(error) 输出错误 JSON + exit 2。"""

    def test_outputs_error_json(self, shot_mod, capsys):
        with pytest.raises(SystemExit) as exc_info:
            shot_mod._fail("device error")
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert result["error"] == "device error"


class TestLog:
    """_log(msg) 走 stderr。"""

    def test_log_to_stderr(self, shot_mod, capsys):
        shot_mod._log("[*] testing...")
        captured = capsys.readouterr()
        assert captured.out == ""
        assert "[*] testing..." in captured.err
