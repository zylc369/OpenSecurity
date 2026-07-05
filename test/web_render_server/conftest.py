# -*- coding: utf-8 -*-
"""web_render_server.py 测试共享 fixture。

web_render_server.py 位于 .opencode/binary-analysis/scripts/，非包结构，
用 importlib 按文件路径加载为模块。

_handle_screenshot 内部 from image_optimize import capture_and_optimize，
需要 scripts/ 在 sys.path 里。
"""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_SCRIPTS_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts"
)
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

_SCRIPT_PATH = _SCRIPTS_DIR / "web_render_server.py"


@pytest.fixture(scope="session")
def server_mod():
    """加载 web_render_server.py 为模块。

    web_render_server.py 模块级 import playwright，缺失时 sys.exit(1)。
    先检测 playwright 可用性，缺失时 skip 整个测试模块。
    """
    pytest.importorskip("playwright")
    spec = importlib.util.spec_from_file_location("web_render_server", _SCRIPT_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["web_render_server"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------- Fake Playwright 组件 ----------


class FakePage:
    """记录调用历史的假 Page。"""

    def __init__(self):
        self.url = "https://example.com"
        self._closed = False

    def goto(self, url, timeout=None, wait_until=None):
        self.url = url
        return SimpleNamespace(status=200)

    def title(self): return "Test Page"
    def content(self): return "<html><body>Hello</body></html>"
    def inner_text(self, selector): return "plain text"
    def screenshot(self, path=None, full_page=False):
        with open(path, "wb") as f:
            f.write(b"\x89PNG fake")
    def click(self, selector, timeout=None): pass
    def fill(self, selector, value): pass
    def press(self, selector, key, timeout=None): pass
    def evaluate(self, script): return "eval_result"
    def wait_for_selector(self, selector, timeout=None): pass
    def wait_for_load_state(self, state, timeout=None): pass
    def close(self): self._closed = True
    def is_closed(self): return self._closed


class FakeContext:
    def __init__(self):
        self._pages = []
        self._cookies = []

    def new_page(self):
        p = FakePage()
        self._pages.append(p)
        return p

    def close(self): pass
    def add_cookies(self, cookies): self._cookies.extend(cookies)
    def cookies(self): return self._cookies


class FakeBrowser:
    def __init__(self):
        self._connected = True
        self.contexts_created = 0

    def new_context(self, **kwargs):
        self.contexts_created += 1
        return FakeContext()

    def is_connected(self): return self._connected
    def close(self): self._connected = False


class FakePlaywright:
    def __init__(self, browser):
        self._browser = browser
        self.chromium = SimpleNamespace(launch=lambda headless=True: browser)

    def stop(self): pass


@pytest.fixture
def fake_pw(server_mod, monkeypatch):
    """替换 server_mod.sync_playwright，返回 FakePlaywright。

    用 monkeypatch.setattr 直接替换模块属性（不依赖 sys.modules）。
    """
    browser = FakeBrowser()
    pw = FakePlaywright(browser)
    cm = MagicMock()
    cm.start.return_value = pw
    monkeypatch.setattr(server_mod, "sync_playwright", lambda: cm)
    return SimpleNamespace(browser=browser, pw=pw)


@pytest.fixture
def mgr(server_mod, fake_pw):
    """已启动的 BrowserManager。"""
    m = server_mod.BrowserManager()
    m.start()
    yield m
    m.stop()
