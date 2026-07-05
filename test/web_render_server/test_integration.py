# -*- coding: utf-8 -*-
"""web_render_server.py 集成测试。

用真实 Chromium 测试完整流程：render/screenshot/navigate/execute/cookies/reset。
截图经过 image_optimize 压缩，返回真实文件信息。

server 用 os.system 后台启动（绕过 subprocess 在 pytest 环境的兼容问题）。
requests 加 Connection: close（web_render_server 是 HTTP/1.1 单线程）。
"""
import os
import time
import signal
import subprocess
from pathlib import Path

import pytest
import requests

VENV_PYTHON = os.path.expanduser("~/bw-security-analysis/.venv/bin/python")
SCRIPT_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / ".opencode" / "binary-analysis" / "scripts" / "web_render_server.py"
)
TEST_PORT = 19600
BASE_URL = f"http://127.0.0.1:{TEST_PORT}"
HDR = {"Connection": "close"}  # HTTP/1.1 单线程 server，每次请求后关闭连接

_server_pid = None


def _start_server():
    """用 os.system 后台启动 server。"""
    global _server_pid
    os.system(
        f"{VENV_PYTHON} '{SCRIPT_PATH}' --port {TEST_PORT} --host 127.0.0.1 "
        f"> /dev/null 2>&1 &"
    )
    # 等 server 就绪
    for _ in range(30):
        try:
            r = requests.get(f"{BASE_URL}/health", headers=HDR, timeout=2)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def _stop_server():
    """用 pkill 清理 server 进程。"""
    os.system("pkill -f 'web_render_server.*--port 19600' 2>/dev/null")


def setup_module():
    """模块开始时启动 server。"""
    _stop_server()  # 先清理可能残留的
    time.sleep(1)
    if not _start_server():
        pytest.skip("web_render_server 未就绪", allow_module_level=True)


def teardown_module():
    """模块结束时清理 server。"""
    _stop_server()


# ─── /health ──────────────────────────────────────────


def test_health():
    r = requests.get(f"{BASE_URL}/health", headers=HDR)
    assert r.status_code == 200
    assert r.json()["browser"] is True


# ─── /render ──────────────────────────────────────────


def test_render_markdown():
    r = requests.post(f"{BASE_URL}/render", json={"url": "https://example.com", "format": "markdown"}, headers=HDR)
    d = r.json()
    assert d["success"] is True
    assert "Example Domain" in d["title"]
    assert len(d["content"]) > 0
    assert d["metadata"]["status_code"] == 200


def test_render_text():
    r = requests.post(f"{BASE_URL}/render", json={"url": "https://example.com", "format": "text"}, headers=HDR)
    assert r.json()["success"] is True


def test_render_html():
    r = requests.post(f"{BASE_URL}/render", json={"url": "https://example.com", "format": "html"}, headers=HDR)
    assert "<html" in r.json()["content"].lower()


def test_render_missing_url():
    r = requests.post(f"{BASE_URL}/render", json={}, headers=HDR)
    assert r.json()["success"] is False


# ─── /screenshot（真实截图 + 压缩）────────────────────


def test_screenshot_creates_file(tmp_path):
    shot_path = str(tmp_path / "shot")
    r = requests.post(f"{BASE_URL}/screenshot", json={"url": "https://example.com", "path": shot_path}, headers=HDR)
    d = r.json()
    assert d["success"] is True
    assert d["size"] > 0
    assert "format" in d
    assert os.path.isfile(d["screenshot"])
    assert os.path.getsize(d["screenshot"]) > 0


def test_screenshot_full_page(tmp_path):
    shot_path = str(tmp_path / "full")
    r = requests.post(f"{BASE_URL}/screenshot", json={"url": "https://example.com", "path": shot_path, "full_page": True}, headers=HDR)
    d = r.json()
    assert d["success"] is True
    assert os.path.isfile(d["screenshot"])
    assert os.path.getsize(d["screenshot"]) > 0


def test_screenshot_missing_url():
    r = requests.post(f"{BASE_URL}/screenshot", json={"path": "/tmp/x"}, headers=HDR)
    assert r.json()["success"] is False


# ─── /navigate + /content ────────────────────────────


def test_navigate_then_content():
    requests.post(f"{BASE_URL}/navigate", json={"url": "https://example.com"}, headers=HDR)
    r = requests.post(f"{BASE_URL}/content", json={"format": "text"}, headers=HDR)
    assert len(r.json()["content"]) > 0


# ─── /execute ─────────────────────────────────────────


def test_execute_javascript():
    requests.post(f"{BASE_URL}/navigate", json={"url": "https://example.com"}, headers=HDR)
    r = requests.post(f"{BASE_URL}/execute", json={"script": "document.title"}, headers=HDR)
    d = r.json()
    assert d["success"] is True
    assert "Example Domain" in d["result"]


def test_execute_missing_script():
    r = requests.post(f"{BASE_URL}/execute", json={}, headers=HDR)
    assert r.json()["success"] is False


# ─── /cookies ─────────────────────────────────────────


def test_cookies_set_then_get():
    requests.post(f"{BASE_URL}/navigate", json={"url": "https://example.com"}, headers=HDR)
    requests.post(f"{BASE_URL}/cookies", json={"name": "test_cookie", "value": "abc123", "domain": "example.com"}, headers=HDR)
    r = requests.post(f"{BASE_URL}/cookies", json={}, headers=HDR)
    names = [c["name"] for c in r.json()["cookies"]]
    assert "test_cookie" in names


# ─── /reset ───────────────────────────────────────────


def test_reset_clears_cookies():
    requests.post(f"{BASE_URL}/navigate", json={"url": "https://example.com"}, headers=HDR)
    requests.post(f"{BASE_URL}/cookies", json={"name": "x", "value": "y", "domain": "example.com"}, headers=HDR)
    requests.post(f"{BASE_URL}/reset", json={}, headers=HDR)
    r = requests.post(f"{BASE_URL}/cookies", json={}, headers=HDR)
    names = [c.get("name", "") for c in r.json()["cookies"]]
    assert "x" not in names


# ─── 404 ─────────────────────────────────────────────


def test_unknown_endpoint_404():
    r = requests.get(f"{BASE_URL}/nonexistent", headers=HDR)
    assert r.status_code == 404
