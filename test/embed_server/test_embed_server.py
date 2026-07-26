"""embed_server.py 单元测试 + 集成测试。

覆盖验收标准：
- F1: 动态端口分配（bind_available_port）
- F2: 端口文件写入
- F3/F4: /health 返回 503/200
- F5: /embed 和 /rerank 端点
"""
import socket
import time
import httpx
import pytest


class TestBindAvailablePort:
    """F1: 动态端口分配。"""

    def test_finds_available_port(self):
        from embed_server import bind_available_port

        sock, port = bind_available_port(start=9776, max_tries=30)
        assert isinstance(port, int)
        assert 9776 <= port <= 9776 + 30
        sock.close()

    def test_skips_occupied_port(self):
        """占用 9776 → 应该返回 9777。"""
        from embed_server import bind_available_port

        # 占用 9776
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        blocker.bind(("127.0.0.1", 9776))
        try:
            sock, port = bind_available_port(start=9776, max_tries=30)
            assert port == 9777, f"期望 9777，实际 {port}"
            sock.close()
        finally:
            blocker.close()

    def test_raises_when_all_occupied(self):
        """所有端口都被占 → RuntimeError。"""
        from embed_server import bind_available_port

        # 占用 9776 和 9777（max_tries=2 只有这两个）
        blockers = []
        for port in (9776, 9777):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            blockers.append(s)
        try:
            with pytest.raises(RuntimeError, match="无可用端口"):
                bind_available_port(start=9776, max_tries=2)
        finally:
            for s in blockers:
                s.close()

    def test_returned_socket_is_open(self):
        """返回的 socket 是打开的（端口被占着，不会竞争）。"""
        from embed_server import bind_available_port

        sock, port = bind_available_port(start=9776)
        # socket 应该还开着——可以 getsockname
        assert sock.getsockname()[1] == port
        sock.close()


class TestPortFile:
    """F2: 端口文件写入（集成测试，需要运行 embed_server）。"""

    def test_port_file_written(self, running_embed_server, tmp_port_file):
        """端口文件存在且格式正确（端口\nPID）。"""
        port, pid = running_embed_server
        assert tmp_port_file.exists(), "端口文件不存在"

        content = tmp_port_file.read_text().strip()
        lines = content.split("\n")
        assert lines[0] == str(port), f"端口文件第一行期望 {port}，实际 {lines[0]}"
        assert int(lines[1]) == pid, f"端口文件第二行 PID 期望 {pid}，实际 {lines[1]}"


class TestHealth:
    """F3/F4: /health 状态码。"""

    def test_health_returns_200_when_ready(self, running_embed_server):
        """F4: 模型就绪后 /health 返回 200。"""
        port, _ = running_embed_server
        r = httpx.get(f"http://127.0.0.1:{port}/health", timeout=5)
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_health_503_logic_directly(self):
        """F3: _models_ready=False 时 health handler 返回 503。

        直接测试 health handler 函数（不通过 HTTP），因为预加载后 /health 永远 200。
        """
        import embed_server

        # 保存原始状态
        original = embed_server._models_ready
        try:
            # 模拟模型未加载
            embed_server._models_ready = False

            # 构造 mock request
            class MockRequest:
                pass

            # 直接调用 async handler
            import asyncio
            response = asyncio.run(embed_server.health(MockRequest()))
            assert response.status_code == 503
            assert response.body == b'{"status":"loading"}'
        finally:
            embed_server._models_ready = original


class TestEmbedEndpoint:
    """F5（部分）: /embed 端点。"""

    def test_embed_single_text(self, running_embed_server):
        """单条文本返回 1024 维向量。"""
        port, _ = running_embed_server
        r = httpx.post(
            f"http://127.0.0.1:{port}/embed",
            json={"inputs": "hello world"},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1, f"期望 1 个向量，实际 {len(data)}"
        assert len(data[0]) == 1024, f"期望 1024 维，实际 {len(data[0])}"

    def test_embed_batch(self, running_embed_server):
        """多条文本返回多个向量。"""
        port, _ = running_embed_server
        r = httpx.post(
            f"http://127.0.0.1:{port}/embed",
            json={"inputs": ["hello", "world"]},
            timeout=60,
        )
        assert r.status_code == 200
        data = r.json()
        assert len(data) == 2
        assert all(len(v) == 1024 for v in data)

    def test_embed_missing_inputs(self, running_embed_server):
        """缺少 inputs 参数返回 400。"""
        port, _ = running_embed_server
        r = httpx.post(
            f"http://127.0.0.1:{port}/embed",
            json={},
            timeout=10,
        )
        assert r.status_code == 400


class TestRerankEndpoint:
    """F5（部分）: /rerank 端点。"""

    def test_rerank_returns_scores(self, running_embed_server):
        """返回与 texts 等长的 score 列表。"""
        port, _ = running_embed_server
        r = httpx.post(
            f"http://127.0.0.1:{port}/rerank",
            json={"query": "security", "texts": ["vulnerability", "hello"]},
            timeout=60,  # 首次触发 reranker 加载
        )
        assert r.status_code == 200
        scores = r.json()
        assert len(scores) == 2, f"期望 2 个 score，实际 {len(scores)}"

    def test_rerank_missing_params(self, running_embed_server):
        """缺少参数返回 400。"""
        port, _ = running_embed_server
        r = httpx.post(
            f"http://127.0.0.1:{port}/rerank",
            json={"query": "test"},
            timeout=10,
        )
        assert r.status_code == 400
