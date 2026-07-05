# -*- coding: utf-8 -*-
"""web_render_server.py HTTP handler 测试。

直接测试 RenderHandler 的各 _handle_* 方法：
- 参数校验（缺 url/selector/script 时返回错误）
- 正常流程（mock browser_mgr 的返回值）
- 错误处理（浏览器操作抛异常）

不启动真实 HTTP server，直接构造 handler 调用方法。
"""
import json
import io
from unittest.mock import MagicMock, patch
from types import SimpleNamespace

import pytest


@pytest.fixture
def handler(server_mod, fake_pw):
    """构造一个 RenderHandler 实例（不发真实 HTTP 请求）。

    BaseHTTPRequestHandler.__init__ 需要 socket 文件描述符，
    用 MagicMock 跳过 __init__，只测试 _handle_* 方法。
    """
    h = server_mod.RenderHandler.__new__(server_mod.RenderHandler)
    # mock _send_json 捕获输出
    h._sent = []
    h._send_json = lambda data, status=200: h._sent.append({"data": data, "status": status})
    return h


@pytest.fixture
def fake_page():
    """用于 mock browser_mgr 的 page。"""
    page = MagicMock()
    page.url = "https://example.com/page"
    page.title.return_value = "Test Page"
    page.content.return_value = "<html><body>Hello</body></html>"
    page.inner_text.return_value = "plain text"
    return page


# ─── /render ──────────────────────────────────────────


def test_render_missing_url(handler):
    handler._handle_render({})
    assert handler._sent[0]["data"]["success"] is False
    assert "url" in handler._sent[0]["data"]["error"]


def test_render_success(handler, fake_page):
    with patch.object(handler, "_read_body"), \
         patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.context.new_page.return_value = fake_page
        fake_page.goto.return_value = SimpleNamespace(status=200)
        handler._handle_render({"url": "https://example.com", "format": "text"})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["url"] == "https://example.com"
        assert result["title"] == "Test Page"


def test_render_browser_error(handler):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        page = MagicMock()
        page.goto.side_effect = Exception("navigation timeout")
        mock_mgr.context.new_page.return_value = page
        handler._handle_render({"url": "https://fail.example"})
        result = handler._sent[0]["data"]
        assert result["success"] is False
        assert "navigation timeout" in result["error"]


# ─── /screenshot ──────────────────────────────────────


def test_screenshot_missing_url(handler):
    handler._handle_screenshot({"path": "/tmp/x.png"})
    assert handler._sent[0]["data"]["success"] is False


def test_screenshot_missing_path(handler):
    handler._handle_screenshot({"url": "https://example.com"})
    assert handler._sent[0]["data"]["success"] is False


def test_screenshot_success(handler, fake_page, tmp_path):
    shot_path = str(tmp_path / "shot.png")
    with patch("web_render_server.browser_mgr") as mock_mgr, \
         patch("image_optimize.capture_and_optimize") as mock_opt:
        mock_mgr.context.new_page.return_value = fake_page
        mock_opt.return_value = {"path": shot_path, "format": "png", "size": 1024}
        handler._handle_screenshot({"url": "https://example.com", "path": shot_path})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["screenshot"] == shot_path


# ─── /navigate ────────────────────────────────────────


def test_navigate_missing_url(handler):
    handler._handle_navigate({})
    assert handler._sent[0]["data"]["success"] is False


def test_navigate_success(handler, fake_page):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.get_page.return_value = fake_page
        fake_page.goto.return_value = SimpleNamespace(status=200)
        handler._handle_navigate({"url": "https://example.com/login"})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["url"] == "https://example.com/login"


# ─── /click ───────────────────────────────────────────


def test_click_missing_selector(handler):
    handler._handle_click({})
    assert handler._sent[0]["data"]["success"] is False


def test_click_success(handler, fake_page):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.get_page.return_value = fake_page
        handler._handle_click({"selector": "#submit"})
        result = handler._sent[0]["data"]
        assert result["success"] is True


def test_click_element_not_found(handler, fake_page):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.get_page.return_value = fake_page
        fake_page.click.side_effect = Exception("element not found")
        handler._handle_click({"selector": "#nonexistent"})
        result = handler._sent[0]["data"]
        assert result["success"] is False
        assert "not found" in result["error"]


# ─── /type ────────────────────────────────────────────


def test_type_missing_selector(handler):
    handler._handle_type({"text": "hello"})
    assert handler._sent[0]["data"]["success"] is False


def test_type_missing_text(handler):
    handler._handle_type({"selector": "#input"})
    assert handler._sent[0]["data"]["success"] is False


def test_type_success(handler, fake_page):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.get_page.return_value = fake_page
        handler._handle_type({"selector": "#username", "text": "admin"})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        fake_page.fill.assert_called_with("#username", "admin")


# ─── /content ─────────────────────────────────────────


def test_content_success(handler, fake_page):
    with patch("web_render_server.browser_mgr") as mock_mgr, \
         patch("web_render_server._render_content", return_value="page content"):
        mock_mgr.get_page.return_value = fake_page
        handler._handle_content({"format": "markdown"})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["content"] == "page content"


# ─── /execute ─────────────────────────────────────────


def test_execute_missing_script(handler):
    handler._handle_execute({})
    assert handler._sent[0]["data"]["success"] is False


def test_execute_success(handler, fake_page):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.get_page.return_value = fake_page
        fake_page.evaluate.return_value = "XSS confirmed"
        handler._handle_execute({"script": "return document.title"})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["result"] == "XSS confirmed"


# ─── /cookies ─────────────────────────────────────────


def test_cookies_get(handler):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr.context.cookies.return_value = [{"name": "session", "value": "abc"}]
        handler._handle_cookies({})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["action"] == "get"
        assert result["cookies"][0]["name"] == "session"


def test_cookies_set(handler):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        handler._handle_cookies({"name": "token", "value": "xyz", "domain": "example.com"})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["action"] == "set"
        mock_mgr.context.add_cookies.assert_called()


# ─── /reset ───────────────────────────────────────────


def test_reset_success(handler):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        handler._handle_reset({})
        result = handler._sent[0]["data"]
        assert result["success"] is True
        assert result["action"] == "reset"
        mock_mgr.reset.assert_called()


# ─── /health (GET) ────────────────────────────────────


def test_health_alive(server_mod):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr._browser = MagicMock()
        mock_mgr._browser.is_connected.return_value = True
        h = server_mod.RenderHandler.__new__(server_mod.RenderHandler)
        h._sent = []
        h._send_json = lambda data, status=200: h._sent.append({"data": data})
        h.do_GET = server_mod.RenderHandler.do_GET.__get__(h)
        # 模拟 path
        h.path = "/health"
        h.do_GET()
        assert h._sent[0]["data"]["status"] == "ok"
        assert h._sent[0]["data"]["browser"] is True


def test_health_dead(server_mod):
    with patch("web_render_server.browser_mgr") as mock_mgr:
        mock_mgr._browser = MagicMock()
        mock_mgr._browser.is_connected.return_value = False
        h = server_mod.RenderHandler.__new__(server_mod.RenderHandler)
        h._sent = []
        h._send_json = lambda data, status=200: h._sent.append({"data": data})
        h.path = "/health"
        h.do_GET = server_mod.RenderHandler.do_GET.__get__(h)
        h.do_GET()
        assert h._sent[0]["data"]["browser"] is False


def test_unknown_endpoint_returns_404(server_mod):
    h = server_mod.RenderHandler.__new__(server_mod.RenderHandler)
    h._sent = []
    h._send_json = lambda data, status=200: h._sent.append({"data": data, "status": status})
    h.path = "/unknown"
    h.do_GET = server_mod.RenderHandler.do_GET.__get__(h)
    h.do_GET()
    assert h._sent[0]["status"] == 404
