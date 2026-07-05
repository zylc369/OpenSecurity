# -*- coding: utf-8 -*-
"""start_browser_server.sh 单元测试。

测试策略：
- 基本完整性（语法检查、可执行权限）
- 用 subprocess + mock 环境测试关键分支
- 不启动真实浏览器服务
"""
import os
import subprocess
import http.server
import threading
import time

import pytest


# ─── 基本完整性 ────────────────────────────────────────


def test_script_exists(script_path):
    assert os.path.isfile(script_path)


def test_script_executable(script_path):
    assert os.access(script_path, os.X_OK)


def test_script_syntax(script_path):
    result = subprocess.run(["bash", "-n", script_path], capture_output=True, text=True)
    assert result.returncode == 0, f"bash 语法错误: {result.stderr}"


# ─── 环境检查 ──────────────────────────────────────────


def test_no_python_cmd_errors(script_path):
    env = os.environ.copy()
    env.pop("PYTHON_CMD", None)
    result = subprocess.run(
        ["bash", script_path], env=env, capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "PYTHON_CMD" in result.stderr or "ERROR" in result.stderr


# ─── 服务已在运行时跳过 ────────────────────────────────


class _FakeHealthServer:
    """启动一个假 HTTP 服务，/health 返回 200。"""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/health":
                body = b'{"status":"ok","browser":true}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, *args):
            pass

    def __init__(self, port):
        self.port = port
        self._server = None
        self._thread = None

    def start(self):
        self._server = http.server.HTTPServer(("127.0.0.1", self.port), self._Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        time.sleep(0.5)

    def stop(self):
        if self._server:
            self._server.shutdown()
            self._server.server_close()


def test_skips_when_service_running(script_path):
    fake = _FakeHealthServer(port=18888)
    try:
        fake.start()
        env = os.environ.copy()
        env["BROWSER_SERVER_PORT"] = "18888"
        env["PYTHON_CMD"] = "/usr/bin/true"
        result = subprocess.run(
            ["bash", script_path], env=env, capture_output=True, text=True, timeout=10,
        )
        assert result.returncode == 0
        assert "http://127.0.0.1:18888" in result.stdout
    finally:
        fake.stop()


# ─── 脚本内容检查 ──────────────────────────────────────


def test_uses_setsid(script_content):
    assert "setsid" in script_content


def test_uses_timeout(script_content):
    assert "timeout" in script_content
    assert "-k 5" in script_content


def test_writes_pid(script_content):
    assert "browser_server.pid" in script_content
    assert "echo $!" in script_content


def test_health_check(script_content):
    assert "/health" in script_content


def test_log_redirect(script_content):
    assert "browser_server.log" in script_content
    assert "2>&1" in script_content


def test_wait_for_ready(script_content):
    assert "seq" in script_content or "sleep" in script_content


def test_set_euo_pipefail(script_content):
    assert "set -euo pipefail" in script_content
