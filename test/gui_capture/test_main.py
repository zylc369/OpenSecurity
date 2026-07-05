# -*- coding: utf-8 -*-
"""main() 主流程测试。

覆盖：pyautogui 缺失、目录创建失败、截图失败、正常流程（mock pyautogui + optimize_for_mcp）、
临时文件清理、元数据 JSON 输出。
"""
import json
import os
import sys

import pytest


class TestMainPyautoguiMissing:
    """main() 中 pyautogui 导入失败路径。"""

    def test_pyautogui_missing_fails(self, cap_mod, monkeypatch, tmp_path, capsys):
        """pyautogui 未安装 → _fail 输出 JSON + exit 2。"""
        # sys.modules['pyautogui'] = None 使 `import pyautogui` 触发 ImportError
        monkeypatch.setitem(sys.modules, "pyautogui", None)
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", str(tmp_path / "out")
        ])

        with pytest.raises(SystemExit) as exc_info:
            cap_mod.main()
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert "pyautogui" in result["error"]


class TestMainDirectoryError:
    """main() 中输出目录创建失败路径。"""

    def test_makedirs_failure_fails(self, cap_mod, monkeypatch, fake_pyautogui, capsys):
        """os.makedirs 抛 OSError → _fail。"""
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", "/nonexistent_root/x/y"
        ])
        # makedirs 对不存在的根路径会抛 PermissionError（OSError 子类）
        with pytest.raises(SystemExit) as exc_info:
            cap_mod.main()
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False


class TestMainScreenshotError:
    """main() 中截图失败路径。"""

    def test_screenshot_exception_fails(self, cap_mod, monkeypatch, fake_pyautogui, tmp_path, capsys):
        """pyautogui.screenshot() 抛异常 → _fail。"""
        def raising_screenshot():
            raise RuntimeError("screen capture failed")
        fake_pyautogui.screenshot = raising_screenshot
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", str(tmp_path / "out"), "--name", "step1"
        ])

        with pytest.raises(SystemExit) as exc_info:
            cap_mod.main()
        assert exc_info.value.code == 2

        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is False
        assert "截图失败" in result["error"]


class TestMainSuccess:
    """main() 正常流程：截图 → 优化 → 输出元数据 JSON。"""

    def test_full_success_flow(self, cap_mod, monkeypatch, fake_pyautogui, tmp_path, capsys):
        """完整成功流程：截图 → optimize_for_mcp → 删临时文件 → 输出 JSON。"""
        out_dir = tmp_path / "views"
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", str(out_dir), "--name", "step1_initial"
        ])

        # mock optimize_for_mcp 返回固定结果
        def fake_optimize(source_path, output_dir, name):
            # 验证临时 PNG 存在
            assert os.path.exists(source_path)
            assert source_path.endswith("_raw.png")
            # 写一个假的优化文件
            opt_path = os.path.join(output_dir, f"{name}.png")
            with open(opt_path, "wb") as f:
                f.write(b"\x89PNG fake")
            return {
                "format": "png", "quality": None,
                "file": f"{name}.png", "path": opt_path, "size": 9,
            }

        monkeypatch.setattr(cap_mod, "optimize_for_mcp", fake_optimize)

        cap_mod.main()

        # 临时文件已删除
        assert not os.path.exists(str(out_dir / "step1_initial_raw.png"))
        # 优化后文件存在
        assert os.path.exists(str(out_dir / "step1_initial.png"))

        # stdout 是成功的 JSON
        captured = capsys.readouterr()
        result = json.loads(captured.out)
        assert result["success"] is True
        assert result["format"] == "png"
        assert result["file"] == "step1_initial.png"
        assert result["screen_resolution"] == [1920, 1080]
        assert result["screenshot_size"] == [100, 100]
        assert result["screenshot_path"].endswith("step1_initial.png")

    def test_metadata_json_file_written(self, cap_mod, monkeypatch, fake_pyautogui, tmp_path):
        """元数据 JSON 文件写入 --output-dir/<name>.json。"""
        out_dir = tmp_path / "views"
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", str(out_dir), "--name", "meta_test"
        ])

        monkeypatch.setattr(cap_mod, "optimize_for_mcp",
                            lambda src, out, name: {
                                "format": "jpg", "quality": 80,
                                "file": f"{name}.jpg",
                                "path": str(out_dir / f"{name}.jpg"),
                                "size": 5000,
                            })

        cap_mod.main()

        meta_path = out_dir / "meta_test.json"
        assert meta_path.exists()
        with open(meta_path, encoding="utf-8") as f:
            meta = json.load(f)
        assert meta["success"] is True
        assert meta["format"] == "jpg"
        assert meta["screenshot_path"].endswith("meta_test.jpg")

    def test_temp_png_removed_on_optimize_failure(
        self, cap_mod, monkeypatch, fake_pyautogui, tmp_path
    ):
        """optimize_for_mcp 抛异常时临时 PNG 仍残留（当前实现未用 try/finally 包裹优化）。

        这是一个已知的健壮性缺口——优化失败时 main() 异常退出，临时文件残留。
        测试记录当前行为，便于将来改进时发现。
        """
        out_dir = tmp_path / "views"
        monkeypatch.setattr("sys.argv", [
            "gui_capture.py", "--output-dir", str(out_dir), "--name", "fail_opt"
        ])

        def raising_optimize(src, out, name):
            raise RuntimeError("optimize crashed")

        monkeypatch.setattr(cap_mod, "optimize_for_mcp", raising_optimize)

        with pytest.raises(RuntimeError, match="optimize crashed"):
            cap_mod.main()

        # 临时文件残留（已知缺口）
        assert os.path.exists(str(out_dir / "fail_opt_raw.png"))
