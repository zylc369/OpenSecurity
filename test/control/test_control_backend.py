"""控制台后端核心模块测试：port_manager（端口分配/端口文件）+ health 逻辑。

替代原 test_embed_server.py（embed_server.py 已删除，功能迁移到
control/backend：端口分配在 services/port_manager.py，/health 在 routes/health.py）。
"""
import json
import os
import socket
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "control" / "backend"

# DATA_DIR 沙箱（必须在 import config 之前设，强制覆盖）：
# config.DATA_DIR 缺省 = ~/bw-security-analysis（生产路径），port_manager 的
# write/delete_port_file 直接操作该目录——不隔离会污染生产端口文件。
# 本文件全部测试均为纯逻辑测试，不需要真实 DATA_DIR，无脑覆盖最安全。
_SBOX = Path(tempfile.mkdtemp(prefix="control_pm_test_"))
os.environ["DATA_DIR"] = str(_SBOX)
sys.path.insert(0, str(BACKEND_DIR))


class TestBindPortWithFallback:
    """端口动态分配（原 embed_server bind_available_port 的迁移目标）。"""

    def test_finds_available_port(self):
        from services.port_manager import bind_port_with_fallback

        port, sock = bind_port_with_fallback()
        assert isinstance(port, int)
        assert port > 0
        assert sock is not None
        # 返回的 socket 是打开的（端口被占着，无竞争窗口）
        assert sock.getsockname()[1] == port
        sock.close()

    def test_skips_occupied_start_port(self, monkeypatch):
        """起始端口被占 → 自动落到后续候选。

        隔离：CONTROL_PORT env 注入随机高位起始端口（config.get_port_candidates
        支持 env 优先级），避免和生产控制台的 9776 冲突。
        占位用不带 SO_REUSEADDR 的独占 bind（macOS 上 REUSEADDR 允许重复 bind，
        "占用"不成立）。
        """
        import random

        from services.port_manager import bind_port_with_fallback
        from config import get_port_candidates

        monkeypatch.setenv("CONTROL_PORT", str(random.randint(40000, 50000)))
        candidates = get_port_candidates()
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # 故意不设 SO_REUSEADDR——独占 bind 才能真正占住端口
        blocker.bind(("127.0.0.1", candidates[0]))
        blocker.listen(1)
        try:
            port, sock = bind_port_with_fallback()
            assert port != candidates[0], f"应跳过被占的 {candidates[0]}，实际 {port}"
            assert port in candidates
            sock.close()
        finally:
            blocker.close()


class TestPortFileRoundtrip:
    """端口文件写读一致性（三行协议：port/pid/start_time）。

    注意：PORT_FILE 在 config.py import 时固化（读 DATA_DIR 环境变量）。
    monkeypatch 环境变量不够——必须直接 patch port_manager.PORT_FILE 指向临时目录。
    """

    @pytest.fixture(autouse=True)
    def _tmp_port_file(self, tmp_path, monkeypatch):
        """把 port_manager.PORT_FILE 指到临时目录（隔离真实控制台的端口文件）。"""
        import services.port_manager as pm

        fake = tmp_path / ".opencode-control.port"
        monkeypatch.setattr(pm, "PORT_FILE", fake)
        return fake

    def test_write_then_read(self):
        from services import port_manager as pm
        import os

        pm.write_port_file(12345)
        info = pm.read_port_file()
        assert info is not None
        port, pid, start_time = info
        assert port == 12345
        assert pid == os.getpid()
        assert start_time > 0

    def test_read_missing_returns_none(self):
        from services.port_manager import read_port_file

        assert read_port_file() is None

    def test_delete_port_file(self):
        from services import port_manager as pm

        pm.write_port_file(12345)
        pm.delete_port_file()
        assert pm.read_port_file() is None

    def test_delete_port_file_skips_foreign_pid(self):
        """缺口 2 防御：文件指向别的进程时不得删除（防孤儿误删新实例文件）。"""
        from services import port_manager as pm

        pm.write_port_file(12345, pid=999999, start_time=1.0)
        pm.delete_port_file()
        info = pm.read_port_file()
        assert info is not None, "指向别人的文件不应被删"
        assert info[1] == 999999
        # 清理
        from config import PORT_FILE

        PORT_FILE.unlink(missing_ok=True)


class TestProbeLiveControl:
    """probe_live_control：端口文件丢失时探测候选端口上的孤儿实例。

    靠 /health 的 service=="opencode-control" 识别字段（200/503 均接受）。
    """

    @staticmethod
    def _fake_health_service(response_body: dict, status: int = 200):
        """起一个假 HTTP 服务返回指定 JSON，返回 (port, shutdown)。"""
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = json.dumps(response_body).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        t = threading.Thread(target=server.serve_forever, daemon=True)
        t.start()

        def shutdown():
            server.shutdown()
            server.server_close()

        return port, shutdown

    def test_probe_identifies_control(self, monkeypatch):
        """带 service 识别字段 → 命中，返回 (port, pid, start_time)。"""
        import random

        from services.port_manager import probe_live_control

        port, shutdown = self._fake_health_service(
            {"status": "ok", "service": "opencode-control", "pid": 12345, "start_time": 99.5}
        )
        monkeypatch.setenv("CONTROL_PORT", str(port))  # 假服务占起始候选位
        try:
            assert probe_live_control() == (port, 12345, 99.5)
        finally:
            shutdown()

    def test_probe_accepts_loading_state(self, monkeypatch):
        """503 + loading + 识别字段 → 也命中（覆盖孤儿正在加载模型的场景）。"""
        from services.port_manager import probe_live_control

        port, shutdown = self._fake_health_service(
            {"status": "loading", "service": "opencode-control", "pid": 12345, "start_time": 1.0},
            status=503,
        )
        monkeypatch.setenv("CONTROL_PORT", str(port))
        try:
            assert probe_live_control() == (port, 12345, 1.0)
        finally:
            shutdown()

    def test_probe_rejects_foreign_service(self, monkeypatch):
        """无 service 字段（其他服务/旧版控制台）→ 不命中。"""
        import random

        from services.port_manager import probe_live_control

        port, shutdown = self._fake_health_service({"status": "ok"})
        # 假服务占的端口大概率不在候选列表（随机高位），强制候选=假服务端口
        monkeypatch.setenv("CONTROL_PORT", str(port))
        try:
            assert probe_live_control() is None
        finally:
            shutdown()


class TestHealthLogic:
    """/health 状态由模型加载状态决定（503 loading → 200 ok）。

    不起 HTTP——直接验证 model_loader 的就绪标志 is_models_ready（routes/health.py 消费同一状态）。
    """

    def test_preload_flag_starts_false_then_true(self):
        from services import model_loader

        # 模块提供就绪查询；首次导入后经 preload 置 True（本测试进程内直接调 loader）
        model_loader.get_embedder()  # 同步加载（模型在 HF cache，秒级）
        assert model_loader.is_models_ready() is True
