#!/usr/bin/env python3
"""summary: MCP 图片优化工具

description:
  将任意格式图片优化为 MCP 视觉工具可识别的最小体积。
  策略：PNG 和 JPEG 竞争，取更小者。
  JPEG quality 通过 PSNR ≥ 35dB 二分搜索自动计算（人眼不可区分阈值）。
  无需调用方指定任何格式或质量参数。

usage:
  from image_optimize import optimize_for_mcp
  result = optimize_for_mcp("/path/to/input.png", "/path/to/output_dir", "step1")
  # result = {"format": "jpg", "file": "step1.jpg", "path": "/path/to/output_dir/step1.jpg", "size": 12345}

level: basic

packages: Pillow (PIL)
"""

import io
import math
import os
import tempfile

from PIL import Image, ImageChops, ImageStat

# 人眼不可区分阈值（图像工程标准：PSNR ≥ 35dB 时人眼无法区分压缩前后差异）
PSNR_THRESHOLD_DB = 35.0
# 安全余量：搜索到的最低 quality 基础上加几档，确保略高于下限
QUALITY_SAFETY_MARGIN = 2
# 二分搜索范围
JPEG_Q_SEARCH_MIN = 15
JPEG_Q_SEARCH_MAX = 98


def _calculate_psnr(original: Image.Image, quality: int) -> float:
    """计算给定 JPEG quality 下压缩后与原图的 PSNR（dB）。

    PSNR = 10 * log10(255² / MSE)
    使用 PIL ImageChops + ImageStat 计算，无 numpy 依赖。
    """
    buf = io.BytesIO()
    original.save(buf, "JPEG", quality=quality)
    buf.seek(0)
    compressed = Image.open(buf).convert("RGB")
    diff = ImageChops.difference(original, compressed)
    stat = ImageStat.Stat(diff)
    # ImageStat.rms 返回每个通道的 RMS，MSE = RMS²
    mse = sum(r ** 2 for r in stat.rms) / len(stat.rms)
    if mse == 0:
        return float("inf")
    return 10 * math.log10(255 ** 2 / mse)


def _find_min_jpeg_quality(img: Image.Image) -> int | None:
    """二分搜索 PSNR ≥ PSNR_THRESHOLD_DB 的最低 JPEG quality。

    返回加上安全余量后的 quality 值。
    返回 None 表示搜索范围内无 quality 能达到阈值（图片内容过于复杂，
    JPEG 无法在可接受失真范围内压缩），调用方应回退到 PNG（无损）。
    """
    lo, hi, best = JPEG_Q_SEARCH_MIN, JPEG_Q_SEARCH_MAX, None
    while lo <= hi:
        mid = (lo + hi) // 2
        if _calculate_psnr(img, mid) >= PSNR_THRESHOLD_DB:
            best = mid
            hi = mid - 1  # 尝试更低的 quality
        else:
            lo = mid + 1  # 需要更高的 quality
    if best is None:
        return None  # 搜索范围内无解，调用方应回退 PNG
    return min(best + QUALITY_SAFETY_MARGIN, 100)


def optimize_for_mcp(source_path: str, output_dir: str, name: str) -> dict:
    """将图片优化为 MCP 可识别的最小体积。

    PNG 和 JPEG 竞争：PNG 无损（PSNR=∞），JPEG 搜索到 PSNR ≥ 35dB 的最低 quality。
    取体积更小者输出。

    Args:
        source_path: 输入图片路径（任何 PIL 支持的格式）
        output_dir: 输出目录
        name: 输出文件名前缀（不含扩展名）

    Returns:
        {"format": "png"|"jpg", "file": "name.png"|"name.jpg",
         "path": "/full/path", "size": bytes}
    """
    img = Image.open(source_path).convert("RGB")
    os.makedirs(output_dir, exist_ok=True)

    # 候选 1: PNG（无损，PSNR = ∞ ≥ 35dB）
    png_path = os.path.join(output_dir, f"{name}.png")
    img.save(png_path, "PNG")
    png_size = os.path.getsize(png_path)

    # 候选 2: JPEG（二分搜索最低 quality 使 PSNR ≥ 35dB）
    # 若搜索范围内无 quality 达标（图片过于复杂），跳过 JPEG，PNG 直接胜出
    jpeg_quality = _find_min_jpeg_quality(img)
    if jpeg_quality is not None:
        jpg_path = os.path.join(output_dir, f"{name}.jpg")
        img.save(jpg_path, "JPEG", quality=jpeg_quality)
        jpg_size = os.path.getsize(jpg_path)
    else:
        jpg_size = float("inf")  # JPEG 不可用，确保 PNG 胜出

    # 竞争：取更小者，删除另一个
    if png_size <= jpg_size:
        if jpeg_quality is not None:
            os.remove(jpg_path)
        return {
            "format": "png",
            "quality": None,
            "file": f"{name}.png",
            "path": os.path.abspath(png_path),
            "size": png_size,
        }
    else:
        os.remove(png_path)
        return {
            "format": "jpg",
            "quality": jpeg_quality,
            "file": f"{name}.jpg",
            "path": os.path.abspath(jpg_path),
            "size": jpg_size,
        }


def capture_and_optimize(page, output_dir: str, name: str, full_page: bool = False) -> dict:
    """Playwright Page 截图 + optimize_for_mcp 优化（统一入口）。

    截图到临时 PNG，再调 optimize_for_mcp 优化（PNG/JPEG 竞争取更小者），
    最终输出由图片内容自动决定格式。临时文件在 finally 中清理。

    Args:
        page: Playwright Page 对象（需有 .screenshot(path=..., full_page=...) 方法）
        output_dir: 输出目录
        name: 输出文件名前缀（不含扩展名）
        full_page: 是否全页截图（默认仅视口）

    Returns:
        optimize_for_mcp 的返回值: {"format", "quality", "file", "path", "size"}

    Raises:
        page.screenshot 或 optimize_for_mcp 的异常原样上抛
    """
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tf:
        tmp_png = tf.name
    try:
        page.screenshot(path=tmp_png, full_page=full_page)
        return optimize_for_mcp(tmp_png, output_dir, name)
    finally:
        if os.path.exists(tmp_png):
            os.remove(tmp_png)
