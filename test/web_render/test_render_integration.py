# -*- coding: utf-8 -*-
"""web_render.py render_page() 真实链路集成测试。

用真实 Playwright + chromium 渲染真实网页，验证：
- 截图经 optimize_for_mcp 后输出有效图片
- markdown 提取返回真实页面内容
- 截图→优化→输出完整链路无残留临时文件

运行条件：playwright + chromium 已安装。
用项目 venv 运行：~/bw-security-analysis/.venv/bin/python -m pytest test/web_render/test_render_integration.py -v -s
"""
import os
import threading
from http.server import HTTPServer, SimpleHTTPRequestHandler

import pytest
from PIL import Image

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def local_server(tmp_path_factory):
    """起本地 HTTP 服务（避免依赖外部网站稳定性）。"""
    from functools import partial

    served_dir = tmp_path_factory.mktemp("www")
    (served_dir / "index.html").write_text(
        "<html><head><title>Test Page</title></head>"
        "<body><h1>Hello Integration Test</h1>"
        "<p>This is a test page for web_render integration testing.</p>"
        "</body></html>"
    )

    handler = partial(SimpleHTTPRequestHandler, directory=str(served_dir))
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    yield f"http://127.0.0.1:{port}"

    server.shutdown()


class TestRenderPageReal:
    """render_page() 真实浏览器集成测试（零 mock）。"""

    def test_render_returns_real_content(self, render_mod, playwright_ok, local_server):
        """render_page 返回真实页面 markdown 内容（不是 mock 的固定文本）。"""
        result = render_mod.render_page(local_server + "/index.html", fmt="markdown")

        assert result["success"] is True
        assert "Hello Integration Test" in result["content"]
        assert result["title"] == "Test Page"

    def test_screenshot_produces_valid_image(self, render_mod, playwright_ok, local_server, tmp_path):
        """截图后输出是有效的图片文件（能被 PIL 打开）。"""
        shot = str(tmp_path / "real_shot")

        result = render_mod.render_page(
            local_server + "/index.html", fmt="text", screenshot=shot
        )

        assert result["success"] is True
        assert result["screenshot"] is not None

        path = result["screenshot"]
        assert os.path.exists(path)
        img = Image.open(path)
        assert img.size == (1280, 720)
        assert img.mode == "RGB"

    def test_screenshot_format_auto_decided(self, render_mod, playwright_ok, local_server, tmp_path):
        """截图格式由图片内容自动决定（不依赖 --screenshot 的扩展名）。

        capture_and_optimize 从 --screenshot 路径提取 name（去掉扩展名），
        再由 optimize_for_mcp 决定输出 png 还是 jpg。输入扩展名不影响输出。
        """
        # 用 .xyz 扩展名（不存在于 optimize 输出中），验证输出一定是 .png 或 .jpg
        shot = str(tmp_path / "trick.xyz")

        result = render_mod.render_page(
            local_server + "/index.html", fmt="text", screenshot=shot
        )

        assert result["success"] is True
        # 输出必须是 png 或 jpg，不能是 xyz
        assert result["screenshot"].endswith((".png", ".jpg"))
        assert not result["screenshot"].endswith(".xyz")

    def test_full_page_screenshot_larger(self, render_mod, playwright_ok, local_server, tmp_path):
        """全页截图比视口截图内容更多（验证 full_page 参数生效）。"""
        result_vp = render_mod.render_page(
            local_server + "/index.html", screenshot=str(tmp_path / "vp")
        )
        result_fp = render_mod.render_page(
            local_server + "/index.html",
            screenshot=str(tmp_path / "fp"),
            screenshot_full_page=True,
        )

        assert result_vp["success"] and result_fp["success"]

        vp_img = Image.open(result_vp["screenshot"])
        fp_img = Image.open(result_fp["screenshot"])
        assert fp_img.size[1] >= vp_img.size[1]

    def test_no_temp_file_residual(self, render_mod, playwright_ok, local_server, tmp_path):
        """截图优化后无临时文件残留。"""
        render_mod.render_page(
            local_server + "/index.html", screenshot=str(tmp_path / "clean")
        )

        files = os.listdir(str(tmp_path))
        temp_files = [f for f in files if f.startswith("tmp")]
        assert len(temp_files) == 0
