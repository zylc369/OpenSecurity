# -*- coding: utf-8 -*-
"""web_render.py 测试共享 fixture。

web_render.py 位于 .opencode/binary-analysis/scripts/，非包结构，
用 importlib 按文件路径加载为模块。

render_page() 内部 `from playwright.sync_api import sync_playwright`，
测试中通过 sys.modules 注入 fake playwright 模块来模拟浏览器行为。
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

# web_render.py 绝对路径
_RENDER_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "web_render.py"
)


@pytest.fixture(scope="session")
def render_mod():
    """加载 web_render.py 为模块（session 级共享）。"""
    spec = importlib.util.spec_from_file_location("web_render", _RENDER_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------- Fake Playwright 组件 ----------

class FakeResponse:
    """模拟 page.goto() 返回的响应。"""
    def __init__(self, status=200):
        self.status = status


class FakePage:
    """模拟 Playwright Page 对象。"""
    def __init__(self, title="Test Page", html="<html><body>hello</body></html>",
                 final_url="https://example.com/page", status=200):
        self._title = title
        self._html = html
        self.url = final_url
        self._response = FakeResponse(status)
        self.screenshot_calls = []

    def goto(self, url, timeout=None, wait_until=None):
        self._goto_url = url
        self._goto_timeout = timeout
        return self._response

    def wait_for_selector(self, selector, timeout=None):
        pass

    def wait_for_load_state(self, state, timeout=None):
        pass

    def title(self):
        return self._title

    def content(self):
        return self._html

    def inner_text(self, selector):
        return "plain text from body"

    def screenshot(self, path=None, full_page=False):
        self.screenshot_calls.append({"path": path, "full_page": full_page})
        # 写一个假的 PNG 文件
        with open(path, "wb") as f:
            f.write(b"\x89PNG\r\n\x1a\n fake png content")


class FakeContext:
    def __init__(self, page=None):
        self._page = page or FakePage()

    def new_page(self):
        return self._page


class FakeBrowser:
    def __init__(self, page=None):
        self._page = page or FakePage()
        self.closed = False

    def new_context(self, user_agent=None, viewport=None):
        return FakeContext(self._page)

    def close(self):
        self.closed = True


class FakePlaywright:
    """模拟 sync_playwright() 返回的对象。"""
    def __init__(self, browser=None):
        self._browser = browser or FakeBrowser()
        self.chromium = SimpleNamespace(
            launch=lambda headless=True: self._browser
        )


class FakeSyncPlaywrightCM:
    """模拟 sync_playwright() 返回的上下文管理器。"""
    def __init__(self, playwright):
        self._pw = playwright

    def __enter__(self):
        return self._pw

    def __exit__(self, *args):
        pass


@pytest.fixture
def fake_playwright(monkeypatch):
    """注入 fake playwright.sync_api 模块到 sys.modules。

    返回 FakeBrowser 实例，测试中可检查 page/browser 的调用记录。
    """
    page = FakePage()
    browser = FakeBrowser(page=page)
    pw = FakePlaywright(browser=browser)

    fake_api = SimpleNamespace(
        sync_playwright=lambda: FakeSyncPlaywrightCM(pw)
    )
    monkeypatch.setitem(sys.modules, "playwright", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", fake_api)

    return SimpleNamespace(page=page, browser=browser)
