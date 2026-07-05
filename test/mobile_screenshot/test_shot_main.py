# -*- coding: utf-8 -*-
"""main() 主流程测试。

覆盖：无设备、多设备无 serial、serial 不匹配、screencap 失败、pull 失败、
文件名清洗、完整成功流程、元数据 JSON 输出。
"""
import json
import os
import re
from types import SimpleNamespace

import pytest


# ---------- mock adb 工厂 ----------

def _mock_completed(returncode=0, stdout="", stderr=""):
    """生成假的 subprocess.CompletedProcess。"""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestDeviceDetection:
    """main() 设备检测分支。"""

    def test_no_devices_fails(self, shot_mod, monkeypatch, tmp_path, capsys):
        """没有检测到设备 → _fail。"""
        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: [])
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out")
        ])

        with pytest.raises(SystemExit) as exc_info:
            shot_mod.main()
        assert exc_info.value.code == 2

        result = json.loads(capsys.readouterr().out)
        assert result["success"] is False
        assert "没有检测到" in result["error"]

    def test_multiple_devices_no_serial_fails(self, shot_mod, monkeypatch, tmp_path, capsys):
        """多设备且未指定 --serial → _fail。"""
        monkeypatch.setattr(shot_mod.adb, "get_devices",
                            lambda: ["device1", "device2"])
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out")
        ])

        with pytest.raises(SystemExit) as exc_info:
            shot_mod.main()
        assert exc_info.value.code == 2

        result = json.loads(capsys.readouterr().out)
        assert result["success"] is False
        assert "多台设备" in result["error"]

    def test_serial_not_found_fails(self, shot_mod, monkeypatch, tmp_path, capsys):
        """--serial 指定的设备不在列表中 → _fail。"""
        monkeypatch.setattr(shot_mod.adb, "get_devices",
                            lambda: ["real_device"])
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out"),
            "--serial", "nonexistent"
        ])

        with pytest.raises(SystemExit) as exc_info:
            shot_mod.main()
        assert exc_info.value.code == 2

        result = json.loads(capsys.readouterr().out)
        assert result["success"] is False
        assert "nonexistent" in result["error"]

    def test_single_device_auto_selected(self, shot_mod, monkeypatch, tmp_path):
        """单设备自动选择（不指定 --serial）。"""
        calls = []

        def fake_adb_shell(serial, cmd, **kwargs):
            calls.append((serial, cmd))
            return _mock_completed(0)

        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["only_device"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", fake_adb_shell)
        monkeypatch.setattr(shot_mod.adb, "pull_file", lambda s, r, l: None)
        monkeypatch.setattr(shot_mod, "optimize_for_mcp",
                            lambda src, out, name: {
                                "format": "png", "quality": None,
                                "file": f"{name}.png",
                                "path": str(tmp_path / "out" / f"{name}.png"),
                                "size": 100,
                            })
        # 写假源文件让 optimize 能"读取"（实际被 mock 跳过）
        # 但 main() 先 save tmp_png → 不需要，因为 screencap 是 mock 的
        # 实际上 main 会 screencap → pull → 然后读 tmp_png 优化
        # pull_file mock 不写文件，所以需要让 tmp_png 存在
        # 更好的方式：让 pull_file 写一个假文件
        def fake_pull(serial, remote, local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(b"\x89PNG fake")
        monkeypatch.setattr(shot_mod.adb, "pull_file", fake_pull)

        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out"), "--name", "auto"
        ])

        shot_mod.main()

        # 验证 adb_shell 用了自动检测到的设备
        assert all(c[0] == "only_device" for c in calls)

    def test_specified_serial_used(self, shot_mod, monkeypatch, tmp_path):
        """--serial 指定的设备被使用。"""
        used_serials = []

        def fake_adb_shell(serial, cmd, **kwargs):
            used_serials.append(serial)
            return _mock_completed(0)

        def fake_pull(serial, remote, local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(b"\x89PNG fake")

        monkeypatch.setattr(shot_mod.adb, "get_devices",
                            lambda: ["emulator5554", "other"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", fake_adb_shell)
        monkeypatch.setattr(shot_mod.adb, "pull_file", fake_pull)
        monkeypatch.setattr(shot_mod, "optimize_for_mcp",
                            lambda src, out, name: {
                                "format": "png", "quality": None,
                                "file": f"{name}.png",
                                "path": str(tmp_path / "out" / f"{name}.png"),
                                "size": 100,
                            })
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out"),
            "--serial", "emulator5554"
        ])

        shot_mod.main()

        assert all(s == "emulator5554" for s in used_serials)


class TestScreencapFailure:
    """main() screencap 失败路径。"""

    def test_screencap_fails(self, shot_mod, monkeypatch, tmp_path, capsys):
        """screencap returncode != 0 → _fail。"""
        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["dev1"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell",
                            lambda s, c, **kw: _mock_completed(1, stderr="screencap error"))
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out")
        ])

        with pytest.raises(SystemExit) as exc_info:
            shot_mod.main()
        assert exc_info.value.code == 2

        result = json.loads(capsys.readouterr().out)
        assert result["success"] is False
        assert "screencap" in result["error"]


class TestPullFailure:
    """main() pull_file 失败路径。"""

    def test_pull_fails_cleans_remote(self, shot_mod, monkeypatch, tmp_path, capsys):
        """pull_file 抛 AdbError → _fail + 清理设备上的临时文件。"""
        remote_cmds = []

        def fake_adb_shell(serial, cmd, **kwargs):
            remote_cmds.append(cmd)
            return _mock_completed(0)

        def failing_pull(serial, remote, local):
            raise shot_mod.adb.AdbError("pull failed", shot_mod.adb.ErrorCode.ADB_CMD_FAILED)

        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["dev1"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", fake_adb_shell)
        monkeypatch.setattr(shot_mod.adb, "pull_file", failing_pull)
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out"), "--name", "test"
        ])

        with pytest.raises(SystemExit) as exc_info:
            shot_mod.main()
        assert exc_info.value.code == 2

        result = json.loads(capsys.readouterr().out)
        assert result["success"] is False
        assert "拉取截图失败" in result["error"]

        # 验证清理了设备临时文件（rm -f /sdcard/test.png）
        rm_cmds = [c for c in remote_cmds if "rm -f" in c]
        assert any("/sdcard/test.png" in c for c in rm_cmds)


class TestFilenameSanitization:
    """main() 文件名特殊字符清洗（re.sub）。"""

    def test_special_chars_replaced(self, shot_mod, monkeypatch, tmp_path):
        """name 含特殊字符 → 替换为下划线。"""
        def fake_pull(serial, remote, local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(b"\x89PNG fake")

        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["dev1"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", lambda s, c, **kw: _mock_completed(0))
        monkeypatch.setattr(shot_mod.adb, "pull_file", fake_pull)
        monkeypatch.setattr(shot_mod, "optimize_for_mcp",
                            lambda src, out, name: {
                                "format": "png", "quality": None,
                                "file": f"{name}.png",
                                "path": str(tmp_path / "out" / f"{name}.png"),
                                "size": 100,
                            })
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out"),
            "--name", "step 1/initial"
        ])

        shot_mod.main()

        # 验证清洗后的文件名
        meta_path = tmp_path / "out" / "step_1_initial.json"
        assert meta_path.exists()


class TestFullSuccess:
    """main() 完整成功流程。"""

    def test_success_flow(self, shot_mod, monkeypatch, tmp_path, capsys):
        """截图 → pull → 优化 → 清理临时 → 输出 JSON。"""
        out_dir = tmp_path / "views"

        def fake_pull(serial, remote, local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(b"\x89PNG fake")

        optimize_called = {}

        def fake_optimize(source_path, output_dir, name):
            optimize_called["source"] = source_path
            optimize_called["name"] = name
            return {
                "format": "jpg", "quality": 75,
                "file": f"{name}.jpg",
                "path": str(out_dir / f"{name}.jpg"),
                "size": 5000,
            }

        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["emulator5554"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", lambda s, c, **kw: _mock_completed(0))
        monkeypatch.setattr(shot_mod.adb, "pull_file", fake_pull)
        monkeypatch.setattr(shot_mod, "optimize_for_mcp", fake_optimize)
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(out_dir), "--name", "step1"
        ])

        shot_mod.main()

        # 临时文件已删除
        assert not os.path.exists(str(out_dir / "step1_raw.png"))

        # stdout 是成功 JSON
        result = json.loads(capsys.readouterr().out)
        assert result["success"] is True
        assert result["format"] == "jpg"
        assert result["device"] == "emulator5554"
        assert result["screenshot_path"].endswith("step1.jpg")

    def test_metadata_json_written(self, shot_mod, monkeypatch, tmp_path):
        """元数据 JSON 写入 --output-dir/<name>.json。"""
        out_dir = tmp_path / "views"

        def fake_pull(serial, remote, local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(b"\x89PNG fake")

        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["dev1"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", lambda s, c, **kw: _mock_completed(0))
        monkeypatch.setattr(shot_mod.adb, "pull_file", fake_pull)
        monkeypatch.setattr(shot_mod, "optimize_for_mcp",
                            lambda src, out, name: {
                                "format": "png", "quality": None,
                                "file": f"{name}.png",
                                "path": str(out_dir / f"{name}.png"),
                                "size": 200,
                            })
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(out_dir), "--name", "meta_test"
        ])

        shot_mod.main()

        meta_path = out_dir / "meta_test.json"
        assert meta_path.exists()
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        assert meta["success"] is True
        assert meta["device"] == "dev1"

    def test_remote_temp_cleaned_after_success(self, shot_mod, monkeypatch, tmp_path):
        """成功后清理设备上的临时截图文件。"""
        shell_cmds = []

        def tracking_shell(serial, cmd, **kwargs):
            shell_cmds.append(cmd)
            return _mock_completed(0)

        def fake_pull(serial, remote, local):
            os.makedirs(os.path.dirname(local), exist_ok=True)
            with open(local, "wb") as f:
                f.write(b"\x89PNG fake")

        monkeypatch.setattr(shot_mod.adb, "get_devices", lambda: ["dev1"])
        monkeypatch.setattr(shot_mod.adb, "adb_shell", tracking_shell)
        monkeypatch.setattr(shot_mod.adb, "pull_file", fake_pull)
        monkeypatch.setattr(shot_mod, "optimize_for_mcp",
                            lambda src, out, name: {
                                "format": "png", "quality": None,
                                "file": f"{name}.png",
                                "path": str(tmp_path / "out" / f"{name}.png"),
                                "size": 100,
                            })
        monkeypatch.setattr("sys.argv", [
            "mobile_screenshot.py", "--output-dir", str(tmp_path / "out"), "--name", "cleanup"
        ])

        shot_mod.main()

        # 成功后应有 rm -f /sdcard/cleanup.png
        rm_cmds = [c for c in shell_cmds if "rm -f" in c]
        assert any("/sdcard/cleanup.png" in c for c in rm_cmds)
