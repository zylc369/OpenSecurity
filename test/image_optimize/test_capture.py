# -*- coding: utf-8 -*-
"""capture_and_optimize() 截图+优化统一入口测试。

覆盖：截图→优化→清理临时文件的完整流程、full_page 传递、page 异常处理。
用 FakePage 模拟 Playwright Page 对象（duck-typed）。
"""
import os
from types import SimpleNamespace

import pytest
from PIL import Image


class FakePage:
    """模拟 Playwright Page 对象（只需 .screenshot 方法）。"""

    def __init__(self, image=None):
        self._image = image or Image.new("RGB", (100, 100), (200, 50, 80))
        self.screenshot_calls = []

    def screenshot(self, path=None, full_page=False):
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        self._image.save(path, "PNG")


class TestCaptureAndOptimize:
    """capture_and_optimize(page, output_dir, name, full_page) 测试。"""

    def test_returns_optimize_result(self, opt_mod, tmp_path):
        """返回值是 optimize_for_mcp 的结果 dict。"""
        page = FakePage(Image.new("RGB", (100, 100), (128, 128, 128)))
        result = opt_mod.capture_and_optimize(page, str(tmp_path / "out"), "shot")

        assert set(result.keys()) == {"format", "quality", "file", "path", "size"}
        assert result["size"] > 0
        assert os.path.exists(result["path"])

    def test_temp_png_cleaned_up(self, opt_mod, tmp_path):
        """临时 PNG 截图文件在优化后被删除。"""
        page = FakePage()
        opt_mod.capture_and_optimize(page, str(tmp_path / "out"), "cleanup")

        # tmp_path 下不应有临时文件（只有优化后的输出）
        files = os.listdir(str(tmp_path / "out"))
        assert len(files) == 1  # 只有最终输出的 .png 或 .jpg

    def test_full_page_passed_to_screenshot(self, opt_mod, tmp_path):
        """full_page=True 传递给 page.screenshot()。"""
        page = FakePage()
        opt_mod.capture_and_optimize(page, str(tmp_path / "out"), "fp", full_page=True)

        assert page.screenshot_calls[0]["full_page"] is True

    def test_full_page_default_false(self, opt_mod, tmp_path):
        """full_page 默认为 False。"""
        page = FakePage()
        opt_mod.capture_and_optimize(page, str(tmp_path / "out"), "vp")

        assert page.screenshot_calls[0]["full_page"] is False

    def test_screenshot_exception_propagates(self, opt_mod, tmp_path):
        """page.screenshot() 抛异常时原样上抛，不静默吞。"""
        class FailingPage:
            def screenshot(self, path=None, full_page=False):
                raise RuntimeError("screenshot crashed")

        with pytest.raises(RuntimeError, match="screenshot crashed"):
            opt_mod.capture_and_optimize(FailingPage(), str(tmp_path / "out"), "fail")

    def test_screenshot_exception_cleans_temp(self, opt_mod, tmp_path):
        """page.screenshot() 抛异常后临时文件被清理（finally 兜底）。"""
        class FailingPage:
            def screenshot(self, path=None, full_page=False):
                # 写一个半成品文件模拟崩溃前状态
                with open(path, "wb") as f:
                    f.write(b"partial")
                raise RuntimeError("crashed")

        out_dir = tmp_path / "out"
        with pytest.raises(RuntimeError):
            opt_mod.capture_and_optimize(FailingPage(), str(out_dir), "crash")

        # 临时 PNG 被清理
        if out_dir.exists():
            files = os.listdir(str(out_dir))
            assert len(files) == 0

    def test_creates_output_dir(self, opt_mod, tmp_path):
        """output_dir 不存在时自动创建。"""
        page = FakePage()
        deep_dir = tmp_path / "nested" / "deep" / "out"

        opt_mod.capture_and_optimize(page, str(deep_dir), "img")

        assert os.path.isdir(str(deep_dir))
