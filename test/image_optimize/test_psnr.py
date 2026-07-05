# -*- coding: utf-8 -*-
"""_calculate_psnr 和 _find_min_jpeg_quality 测试。

PSNR 计算正确性 + 二分搜索找到 PSNR≥35dB 的最低 quality + 安全余量。
"""
import math

import pytest
from PIL import Image


class TestCalculatePsnr:
    """_calculate_psnr(original, quality) → float（dB）。"""

    def test_high_quality_high_psnr(self, opt_mod, solid_image):
        """quality=100 时 JPEG 虽非无损但 PSNR 较高（实测 ~53dB，远超 35dB 阈值）。

        JPEG quality=100 仍有量化损失，不是数学意义上的"无损"，
        但对人眼足够接近（>50dB 远超人眼可区分范围）。
        """
        psnr = opt_mod._calculate_psnr(solid_image, 100)
        assert psnr >= 40  # quality=100 应远高于 35dB 阈值

    def test_high_quality_higher_psnr(self, opt_mod, noise_image):
        """高 quality 的 PSNR > 低 quality 的 PSNR（单调性）。"""
        low = opt_mod._calculate_psnr(noise_image, 20)
        high = opt_mod._calculate_psnr(noise_image, 90)
        assert high > low

    def test_solid_image_high_psnr(self, opt_mod, solid_image):
        """纯色图片在任何 quality 下 PSNR 都应很高（极易压缩）。"""
        psnr = opt_mod._calculate_psnr(solid_image, 30)
        assert psnr >= 35  # 纯色图低 quality 也达阈值

    def test_returns_float(self, opt_mod, solid_image):
        """返回值是 float。"""
        psnr = opt_mod._calculate_psnr(solid_image, 50)
        assert isinstance(psnr, float)

    def test_psnr_value_reasonable(self, opt_mod, noise_image):
        """PSNR 值在合理范围（10-100dB）。"""
        psnr = opt_mod._calculate_psnr(noise_image, 50)
        assert 10 < psnr < 100


class TestFindMinJpegQuality:
    """_find_min_jpeg_quality(img) → int（含安全余量）。"""

    def test_returns_int(self, opt_mod, solid_image):
        result = opt_mod._find_min_jpeg_quality(solid_image)
        assert isinstance(result, int)

    def test_quality_in_valid_range(self, opt_mod, gradient_image):
        """有解时 quality 在 [JPEG_Q_SEARCH_MIN, 100] 范围内。"""
        result = opt_mod._find_min_jpeg_quality(gradient_image)
        assert result is not None
        assert opt_mod.JPEG_Q_SEARCH_MIN <= result <= 100

    def test_solid_image_low_quality(self, opt_mod, solid_image):
        """纯色图片极易压缩，最低 quality 就能达 PSNR≥35dB。

        二分搜索应找到 JPEG_Q_SEARCH_MIN + 安全余量。
        """
        result = opt_mod._find_min_jpeg_quality(solid_image)
        # 纯色图 JPEG_Q_SEARCH_MIN 应已达标，加余量后 = MIN + 2
        assert result == opt_mod.JPEG_Q_SEARCH_MIN + opt_mod.QUALITY_SAFETY_MARGIN

    def test_gradient_higher_quality_than_solid(self, opt_mod, complex_image):
        """复杂图片比纯色图需要更高 quality 才能达 PSNR≥35dB。"""
        result = opt_mod._find_min_jpeg_quality(complex_image)
        solid_q = opt_mod._find_min_jpeg_quality(Image.new("RGB", (100, 100), (128, 128, 128)))
        assert result is not None
        assert result > solid_q

    def test_noise_image_returns_none(self, opt_mod, noise_image):
        """纯随机噪声 JPEG 无法在任何 quality 下达到 35dB → 返回 None。

        这是核心质量保障：搜索范围内无解时返回 None，
        optimize_for_mcp 会据此回退到 PNG（无损），保证 MCP 识别质量。
        """
        result = opt_mod._find_min_jpeg_quality(noise_image)
        assert result is None

    def test_quality_at_least_min_plus_margin(self, opt_mod, gradient_image):
        """quality 至少是搜索到的最低值 + 安全余量。"""
        result = opt_mod._find_min_jpeg_quality(gradient_image)
        assert result is not None
        assert result >= opt_mod.JPEG_Q_SEARCH_MIN + opt_mod.QUALITY_SAFETY_MARGIN

    def test_result_quality_meets_threshold(self, opt_mod, gradient_image):
        """用返回的 quality 压缩，PSNR 确实 ≥ 35dB（端到端验证）。

        用渐变图（真实截图的常见内容）验证，而非纯随机噪声——
        纯随机噪声 JPEG 无法在任何 quality 下达到 35dB（JPEG 固有限制，非代码 bug）。
        """
        quality = opt_mod._find_min_jpeg_quality(gradient_image)
        psnr = opt_mod._calculate_psnr(gradient_image, quality)
        assert psnr >= opt_mod.PSNR_THRESHOLD_DB

    def test_capped_at_100(self, opt_mod, gradient_image):
        """quality 不超过 100（min(best + margin, 100)）。"""
        result = opt_mod._find_min_jpeg_quality(gradient_image)
        assert result is not None
        assert result <= 100
