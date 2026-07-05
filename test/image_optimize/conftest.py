# -*- coding: utf-8 -*-
"""image_optimize.py 测试共享 fixture。

image_optimize.py 位于 .opencode/binary-analysis/scripts/，非包结构，
用 importlib 按文件路径加载为模块，供各测试文件通过 ``opt_mod`` fixture 访问。
"""
import importlib.util
from pathlib import Path

import pytest
from PIL import Image

# image_optimize.py 绝对路径：本文件位于 test/image_optimize/，往上三级到工程根
_OPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "image_optimize.py"
)


@pytest.fixture(scope="session")
def opt_mod():
    """加载 image_optimize.py 为模块（session 级共享）。"""
    spec = importlib.util.spec_from_file_location("image_optimize", _OPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- 测试用图片工厂 ----------

@pytest.fixture
def solid_image():
    """100x100 纯色 RGB 图片（PNG 友好，JPEG 高频损失大）。"""
    return Image.new("RGB", (100, 100), (200, 50, 80))


@pytest.fixture
def noise_image():
    """100x100 随机噪声图片（JPEG 友好，PNG 无损体积大）。"""
    import random
    random.seed(42)  # 可复现
    img = Image.new("RGB", (100, 100))
    pixels = img.load()
    for y in range(100):
        for x in range(100):
            pixels[x, y] = (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))
    return img


@pytest.fixture
def gradient_image():
    """100x100 水平渐变图片（简单内容，用于验证 PSNR 单调性等基本属性）。"""
    img = Image.new("RGB", (100, 100))
    pixels = img.load()
    for y in range(100):
        for x in range(100):
            pixels[x, y] = (x * 2, x * 2, x * 2)
    return img


@pytest.fixture
def complex_image():
    """500x500 二维正弦渐变图片（接近真实截图复杂度）。

    用于验证 JPEG 竞争胜出场景：该图 JPEG 远小于 PNG（10KB vs 149KB），
    且需要 quality>MIN+margin 才能达 PSNR≥35dB。
    """
    import math
    img = Image.new("RGB", (500, 500))
    pixels = img.load()
    for y in range(500):
        for x in range(500):
            r = int(128 + 100 * math.sin(x * 0.05) + 50 * math.cos(y * 0.03))
            g = int(128 + 80 * math.cos(x * 0.03) + 60 * math.sin(y * 0.04))
            b = int(128 + 60 * math.sin((x + y) * 0.02))
            pixels[x, y] = (
                max(0, min(255, r)),
                max(0, min(255, g)),
                max(0, min(255, b)),
            )
    return img
