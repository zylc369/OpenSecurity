# -*- coding: utf-8 -*-
"""web_render_server.py 单元测试。

用 Fake Playwright 组件（conftest.py 定义），不启动真实 Chromium。
"""
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ─── BrowserManager 生命周期 ──────────────────────────


def test_start_initializes_browser(server_mod, fake_pw):
    m = server_mod.BrowserManager()
    m.start()
    assert m._browser is not None
    assert m._context is not None
    assert m._page is None
    m.stop()


def test_stop_clears_all(mgr):
    mgr.stop()
    assert mgr._browser is None
    assert mgr._context is None
    assert mgr._playwright is None
    assert mgr._page is None


def test_stop_is_idempotent(server_mod, fake_pw):
    m = server_mod.BrowserManager()
    m.start()
    m.stop()
    m.stop()


def test_reset_creates_new_context(mgr):
    old = mgr._context
    mgr.reset()
    assert mgr._context is not old
    assert mgr._page is None


def test_ensure_alive_when_alive(mgr, fake_pw):
    before = mgr._browser
    mgr.ensure_alive()
    assert mgr._browser is before


def test_ensure_alive_when_dead(mgr, fake_pw):
    fake_pw.browser._connected = False
    mgr.ensure_alive()
    # ensure_alive 调 stop()+start() 重建了 browser
    assert mgr._browser is not None


# ─── 活跃 page ────────────────────────────────────────


def test_get_page_creates_if_none(mgr):
    assert mgr._page is None
    p = mgr.get_page()
    assert p is not None


def test_get_page_reuses(mgr):
    p1 = mgr.get_page()
    p2 = mgr.get_page()
    assert p1 is p2


def test_get_page_recreates_if_closed(mgr):
    p1 = mgr.get_page()
    p1._closed = True
    p2 = mgr.get_page()
    assert p2 is not p1


def test_close_page(mgr):
    mgr.get_page()
    assert mgr._page is not None
    mgr.close_page()
    assert mgr._page is None


def test_close_page_no_active(mgr):
    mgr.close_page()


# ─── context property ─────────────────────────────────


def test_context_property(mgr):
    assert mgr.context is mgr._context


def test_context_triggers_ensure_alive(mgr, fake_pw):
    fake_pw.browser._connected = False
    _ = mgr.context
    assert mgr._browser is not None


# ─── touch ────────────────────────────────────────────


def test_touch_updates(mgr):
    old = mgr._last_activity
    time.sleep(0.01)
    mgr.touch()
    assert mgr._last_activity > old


def test_touch_initialized_on_start(mgr):
    assert mgr._last_activity > 0


# ─── _render_content ──────────────────────────────────


def test_render_content_text(server_mod):
    page = MagicMock()
    page.inner_text.return_value = "plain text"
    assert server_mod._render_content(page, "text") == "plain text"


def test_render_content_html(server_mod):
    page = MagicMock()
    page.content.return_value = "<html>raw</html>"
    assert server_mod._render_content(page, "html") == "<html>raw</html>"


def test_render_content_unknown_fallback_html(server_mod):
    page = MagicMock()
    page.content.return_value = "<html>x</html>"
    assert server_mod._render_content(page, "unknown") == "<html>x</html>"


def test_render_content_markdown(server_mod):
    page = MagicMock()
    page.content.return_value = "<html><body><h1>Title</h1></body></html>"
    try:
        result = server_mod._render_content(page, "markdown")
        assert isinstance(result, str) and len(result) > 0
    except ImportError:
        page.inner_text.assert_called_with("body")
