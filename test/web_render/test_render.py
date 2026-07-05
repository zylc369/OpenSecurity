# -*- coding: utf-8 -*-
"""render_page() 主函数测试。

覆盖：URL 校验、playwright 缺失、timeout 边界、内容提取（markdown/text/html）、
截图优化、wait_selector。
"""
import os

import pytest


class TestUrlValidation:
    """render_page() URL 前缀校验。"""

    def test_non_http_url_returns_error(self, render_mod, fake_playwright):
        """URL 不以 http:// 或 https:// 开头 → 返回 error。

        注意：URL 校验在 playwright 导入之后，需要 mock playwright 才能到达校验逻辑。
        """
        result = render_mod.render_page("ftp://example.com")
        assert result["success"] is False
        assert "http://" in result["error"] or "https://" in result["error"]

    def test_plain_string_returns_error(self, render_mod):
        result = render_mod.render_page("example.com")
        assert result["success"] is False

    def test_https_url_accepted(self, render_mod, fake_playwright):
        """https:// URL 通过校验，进入 playwright 流程。"""
        result = render_mod.render_page("https://example.com")
        assert result["success"] is True

    def test_http_url_accepted(self, render_mod, fake_playwright):
        """http:// URL 通过校验。"""
        result = render_mod.render_page("http://example.com")
        assert result["success"] is True


class TestPlaywrightMissing:
    """render_page() playwright 未安装路径。"""

    def test_playwright_missing_returns_error(self, render_mod, monkeypatch):
        """playwright 不可导入 → 返回带安装提示的 error。"""
        # 移除 playwright 模块，使 import 失败
        monkeypatch.setitem(__import__("sys").modules, "playwright", None)
        monkeypatch.setitem(__import__("sys").modules, "playwright.sync_api", None)

        result = render_mod.render_page("https://example.com")
        assert result["success"] is False
        assert "playwright" in result["error"]


class TestTimeoutClamping:
    """render_page() timeout 参数边界处理。"""

    def test_timeout_below_minimum_clamped(self, render_mod, fake_playwright):
        """timeout < 5 → 实际传给 goto 的是 5*1000ms。"""
        render_mod.render_page("https://example.com", timeout=1)
        assert fake_playwright.page._goto_timeout == 5 * 1000

    def test_timeout_above_maximum_clamped(self, render_mod, fake_playwright):
        """timeout > 120 → 实际传给 goto 的是 120*1000ms。"""
        render_mod.render_page("https://example.com", timeout=300)
        assert fake_playwright.page._goto_timeout == 120 * 1000

    def test_normal_timeout_passed_through(self, render_mod, fake_playwright):
        """5 ≤ timeout ≤ 120 → 原样传递。"""
        render_mod.render_page("https://example.com", timeout=30)
        assert fake_playwright.page._goto_timeout == 30 * 1000


class TestContentExtraction:
    """render_page() 不同 fmt 的内容提取。"""

    def test_markdown_format(self, render_mod, fake_playwright):
        """fmt='markdown' → 调用 _html_to_markdown 转换。"""
        result = render_mod.render_page("https://example.com", fmt="markdown")
        assert result["success"] is True
        assert result["content_type"] == "markdown"
        assert "hello" in result["content"]

    def test_text_format(self, render_mod, fake_playwright):
        """fmt='text' → 调用 page.inner_text('body')。"""
        result = render_mod.render_page("https://example.com", fmt="text")
        assert result["success"] is True
        assert result["content_type"] == "text"
        assert result["content"] == "plain text from body"

    def test_html_format(self, render_mod, fake_playwright):
        """fmt='html' → 调用 page.content()。"""
        result = render_mod.render_page("https://example.com", fmt="html")
        assert result["success"] is True
        assert result["content_type"] == "html"
        assert "<html>" in result["content"]

    def test_title_extracted(self, render_mod, fake_playwright):
        result = render_mod.render_page("https://example.com")
        assert result["title"] == "Test Page"

    def test_metadata_contains_status_and_url(self, render_mod, fake_playwright):
        result = render_mod.render_page("https://example.com")
        assert result["metadata"]["status_code"] == 200
        assert result["metadata"]["final_url"] == "https://example.com/page"


class TestScreenshot:
    """render_page() 截图优化逻辑。"""

    def test_screenshot_calls_capture_and_optimize(self, render_mod, fake_playwright, monkeypatch, tmp_path):
        """指定 screenshot 参数时调用 capture_and_optimize（截图+优化统一入口）。"""
        called = {}

        def fake_capture(page, output_dir, name, full_page=False):
            called["output_dir"] = output_dir
            called["name"] = name
            called["full_page"] = full_page
            return {
                "format": "png", "quality": None,
                "file": f"{name}.png",
                "path": str(tmp_path / f"{name}.png"),
                "size": 100,
            }

        import sys
        fake_mod = type(sys)("image_optimize")
        fake_mod.capture_and_optimize = fake_capture
        monkeypatch.setitem(sys.modules, "image_optimize", fake_mod)

        shot_path = str(tmp_path / "page")
        result = render_mod.render_page("https://example.com", screenshot=shot_path)

        assert called["name"] == "page"
        assert called["full_page"] is False
        assert result["screenshot"] == str(tmp_path / "page.png")

    def test_screenshot_full_page_passed_through(self, render_mod, fake_playwright, monkeypatch, tmp_path):
        """screenshot_full_page=True 传递给 capture_and_optimize。"""
        called = {}

        def fake_capture(page, output_dir, name, full_page=False):
            called["full_page"] = full_page
            return {"format": "png", "quality": None,
                    "file": f"{name}.png", "path": str(tmp_path / f"{name}.png"), "size": 100}

        import sys
        fake_mod = type(sys)("image_optimize")
        fake_mod.capture_and_optimize = fake_capture
        monkeypatch.setitem(sys.modules, "image_optimize", fake_mod)

        render_mod.render_page("https://example.com", screenshot=str(tmp_path / "page"),
                               screenshot_full_page=True)
        assert called["full_page"] is True

    def test_no_screenshot_returns_none(self, render_mod, fake_playwright):
        """不指定 screenshot → result['screenshot'] 为 None。"""
        result = render_mod.render_page("https://example.com")
        assert result["screenshot"] is None


class TestWaitSelector:
    """render_page() wait_selector 参数。"""

    def test_wait_selector_called(self, render_mod, fake_playwright):
        """指定 wait_selector 时调用 page.wait_for_selector 而非 networkidle。"""
        # FakePage.wait_for_selector 不抛异常即表示被调用
        result = render_mod.render_page(
            "https://example.com", wait_selector="#content"
        )
        assert result["success"] is True
