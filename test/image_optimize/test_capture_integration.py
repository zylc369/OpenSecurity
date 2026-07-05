# -*- coding: utf-8 -*-
"""capture_and_optimize 真实链路集成测试。

与 test_capture.py（mock 测试）互补：本文件用真实 Playwright + chromium
截图真实网页，走完整的 截图 → optimize_for_mcp → 输出 链路。

运行条件：playwright + chromium 已安装。
用项目 venv 运行：~/bw-security-analysis/.venv/bin/python -m pytest test/image_optimize/test_capture_integration.py -v -s
.venv_test 无 playwright 时自动跳过。

分类标记：pytest.mark.integration 可用于过滤（-m "not integration" 跳过）。
"""
import os
import time

import pytest
from PIL import Image

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def real_page():
    """启动真实浏览器，返回一个已导航的 Page 对象。模块级共享（启动慢）。"""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(viewport={"width": 1280, "height": 720})
    page = ctx.new_page()
    yield page
    browser.close()
    pw.stop()


@pytest.fixture(scope="module")
def simple_url():
    """起本地 HTTP 服务提供简单测试页面（避免依赖外部网站）。"""
    import threading
    from functools import partial
    from http.server import HTTPServer, SimpleHTTPRequestHandler
    import tempfile, os

    www = tempfile.mkdtemp()
    with open(os.path.join(www, "index.html"), "w") as f:
        f.write(
            "<html><head><title>Simple</title></head>"
            "<body><h1>Hello World</h1><p>Test page for screenshot optimization.</p>"
            "</body></html>"
        )
    handler = partial(SimpleHTTPRequestHandler, directory=www)
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/index.html"
    server.shutdown()


class TestCaptureAndOptimizeReal:
    """capture_and_optimize 真实截图 + 真实优化（零 mock）。"""

    def test_simple_page_produces_valid_png(self, opt_mod, playwright_ok, real_page, simple_url, tmp_path):
        """简单页面（纯文字）截图 → 输出有效 PNG（PNG 竞争胜出场景）。"""
        real_page.goto(simple_url, wait_until="domcontentloaded", timeout=30000)

        result = opt_mod.capture_and_optimize(real_page, str(tmp_path), "simple")

        assert result["size"] > 0
        assert os.path.exists(result["path"])
        img = Image.open(result["path"])
        assert img.size == (1280, 720)
        assert img.mode == "RGB"

    def test_simple_page_output_valid_and_small(self, opt_mod, playwright_ok, real_page, simple_url, tmp_path):
        """简单页面截图 → 输出有效图片且体积合理。

        不假设格式（PNG/JPEG 由内容决定），只验证：
        - 输出是有效图片（PIL 能打开）
        - 体积合理（纯文字页面应 < 50KB）
        """
        real_page.goto(simple_url, wait_until="domcontentloaded", timeout=30000)

        result = opt_mod.capture_and_optimize(real_page, str(tmp_path), "text_page")

        assert result["format"] in ("png", "jpg")
        assert result["size"] < 50 * 1024  # 纯文字页面应 < 50KB

    def test_complex_page_jpeg_smaller(self, opt_mod, playwright_ok, real_page, tmp_path):
        """复杂页面 JPEG 比 PNG 小（JPEG 竞争胜出场景）。

        用渐变色块密集的本地页面，JPEG 有损压缩应显著优于 PNG。
        """
        import math
        html = "<html><body style='margin:0'>"
        for i in range(50):
            r = int(128 + 100 * math.sin(i * 0.3))
            g = int(128 + 80 * math.cos(i * 0.5))
            b = int(128 + 60 * math.sin(i * 0.7))
            html += (
                f"<div style='height:15px;"
                f"background:linear-gradient(90deg,rgb({r},{g},{b}),rgb({b},{r},{g}));"
                f"color:white;padding:2px'>Section {i}</div>"
            )
        html += "</body></html>"
        html_file = tmp_path / "complex.html"
        html_file.write_text(html)

        # file:// 被 web_render 拒绝，但 capture_and_optimize 直接调 page.screenshot
        # 所以用 set_content 注入 HTML
        real_page.set_content(html)

        result = opt_mod.capture_and_optimize(
            real_page, str(tmp_path), "complex", full_page=True
        )

        assert result["format"] == "jpg"
        assert result["quality"] is not None
        assert result["quality"] > 0

        # 对比：同图存 PNG 多大
        img = Image.open(result["path"])
        raw_png = tmp_path / "raw_compare.png"
        img.save(str(raw_png), "PNG")
        raw_size = raw_png.stat().st_size
        # JPEG 应比 PNG 小
        assert result["size"] < raw_size

    def test_optimize_speed_under_1s(self, opt_mod, playwright_ok, real_page, simple_url, tmp_path):
        """optimize_for_mcp 处理真实截图应在 1 秒内完成。"""
        real_page.goto(simple_url, wait_until="domcontentloaded", timeout=30000)

        t0 = time.time()
        result = opt_mod.capture_and_optimize(real_page, str(tmp_path), "speed")
        elapsed = time.time() - t0

        assert elapsed < 1.0, f"优化耗时 {elapsed:.2f}s 超过 1s 阈值"
        assert result["size"] > 0

    def test_no_temp_file_left(self, opt_mod, playwright_ok, real_page, simple_url, tmp_path):
        """capture_and_optimize 完成后临时 PNG 被清理（无残留）。"""
        real_page.goto(simple_url, wait_until="domcontentloaded", timeout=30000)

        opt_mod.capture_and_optimize(real_page, str(tmp_path), "cleanup")

        # tmp_path 下只有最终输出文件，没有临时 tmp*.png
        files = os.listdir(str(tmp_path))
        temp_files = [f for f in files if f.startswith("tmp") and f.endswith(".png")]
        assert len(temp_files) == 0, f"残留临时文件: {temp_files}"
        # 只有 1 个输出文件
        output_files = [f for f in files if f.endswith((".png", ".jpg"))]
        assert len(output_files) == 1
