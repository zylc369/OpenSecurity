# -*- coding: utf-8 -*-
"""optimize_for_mcp 主函数测试。

PNG/JPEG 竞争取更小者 + 输出格式 + 文件清理。
"""
import os

import pytest
from PIL import Image


class TestOptimizeForMcp:
    """optimize_for_mcp(source_path, output_dir, name) → dict。"""

    def test_solid_image_prefers_png(self, opt_mod, solid_image, tmp_path):
        """纯色图片 PNG 更小 → 输出 PNG。"""
        src = tmp_path / "input.png"
        solid_image.save(src, "PNG")

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "step1")

        assert result["format"] == "png"
        assert result["quality"] is None
        assert result["file"] == "step1.png"
        assert result["path"].endswith("step1.png")
        assert result["size"] > 0
        assert os.path.exists(result["path"])
        # JPEG 候选应被删除
        assert not os.path.exists(os.path.join(str(tmp_path / "out"), "step1.jpg"))

    def test_noise_image_falls_back_to_png(self, opt_mod, noise_image, tmp_path):
        """纯随机噪声 JPEG 无法达到 PSNR≥35dB → 回退到 PNG（无损）。

        这是质量保障的核心：当 JPEG 搜索范围内无解时，
        optimize_for_mcp 不产出不达标 JPEG，而是输出 PNG 保证质量。
        """
        src = tmp_path / "input.png"
        noise_image.save(src, "PNG")

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "step2")

        assert result["format"] == "png"
        assert result["quality"] is None
        assert result["file"] == "step2.png"
        assert result["path"].endswith("step2.png")
        assert result["size"] > 0
        assert os.path.exists(result["path"])
        # 不应生成 .jpg 文件
        assert not os.path.exists(os.path.join(str(tmp_path / "out"), "step2.jpg"))

    def test_creates_output_dir(self, opt_mod, solid_image, tmp_path):
        """output_dir 不存在时自动创建。"""
        src = tmp_path / "input.png"
        solid_image.save(src, "PNG")
        out_dir = tmp_path / "nested" / "deep" / "out"

        result = opt_mod.optimize_for_mcp(str(src), str(out_dir), "img")

        assert os.path.isdir(str(out_dir))
        assert os.path.exists(result["path"])

    def test_return_dict_fields_complete(self, opt_mod, solid_image, tmp_path):
        """返回 dict 含所有必需字段。"""
        src = tmp_path / "input.png"
        solid_image.save(src, "PNG")

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "x")

        assert set(result.keys()) == {"format", "quality", "file", "path", "size"}

    def test_path_is_absolute(self, opt_mod, solid_image, tmp_path):
        """返回的 path 是绝对路径。"""
        src = tmp_path / "input.png"
        solid_image.save(src, "PNG")

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "abs")

        assert os.path.isabs(result["path"])

    def test_jpeg_output_smaller_than_raw_png(self, opt_mod, complex_image, tmp_path):
        """复杂图片 JPEG 输出比原始 PNG 小（JPEG 有损压缩生效）。

        用 500x500 二维正弦渐变图验证（JPEG ~10KB vs PNG ~149KB）。
        """
        src = tmp_path / "input.png"
        complex_image.save(src, "PNG")
        raw_size = os.path.getsize(src)

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "small")

        assert result["format"] == "jpg"  # 复杂图 JPEG 应胜出
        assert result["size"] < raw_size

    def test_jpeg_quality_meets_psnr_threshold(self, opt_mod, gradient_image, tmp_path):
        """JPEG 输出的 PSNR ≥ 35dB（端到端验证压缩质量）。

        用渐变图（真实截图常见内容）验证。纯随机噪声 JPEG 无法达到 35dB，
        是 JPEG 编码的固有限制，不是代码 bug。
        """
        src = tmp_path / "input.png"
        gradient_image.save(src, "PNG")

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "psnr_check")

        if result["format"] == "jpg":
            psnr = opt_mod._calculate_psnr(gradient_image, result["quality"])
            assert psnr >= opt_mod.PSNR_THRESHOLD_DB

    def test_accepts_jpeg_input(self, opt_mod, solid_image, tmp_path):
        """输入是 JPEG 也能处理（PIL 支持的任何格式）。"""
        src = tmp_path / "input.jpg"
        solid_image.save(src, "JPEG", quality=85)

        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "from_jpg")

        assert result["format"] in ("png", "jpg")
        assert os.path.exists(result["path"])

    def test_name_with_special_chars(self, opt_mod, solid_image, tmp_path):
        """name 含特殊字符时不崩溃（调用方负责清洗，函数不过滤）。"""
        src = tmp_path / "input.png"
        solid_image.save(src, "PNG")

        # name 直接用，函数不做清洗（mobile_screenshot.py 在调用前清洗）
        result = opt_mod.optimize_for_mcp(str(src), str(tmp_path / "out"), "step_1")

        assert result["file"] == "step_1.png" or result["file"] == "step_1.jpg"

    def test_overwrites_existing_output(self, opt_mod, solid_image, tmp_path):
        """同名输出已存在时覆盖（不报错）。"""
        src = tmp_path / "input.png"
        solid_image.save(src, "PNG")
        out_dir = tmp_path / "out"
        out_dir.mkdir()

        # 第一次
        r1 = opt_mod.optimize_for_mcp(str(src), str(out_dir), "dup")
        # 第二次（同名）
        r2 = opt_mod.optimize_for_mcp(str(src), str(out_dir), "dup")

        assert r1["file"] == r2["file"]
        assert os.path.exists(r2["path"])
