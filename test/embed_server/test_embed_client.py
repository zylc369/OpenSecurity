"""embed_client.py 单元测试 + 集成测试。

覆盖验收标准：
- F5: 降级逻辑已删除（server 不可用时抛 RuntimeError）
- F8: 分层超时（首次 60s，后续 10s）
- A3: 接口兼容性（encode/predict 签名不变）
- _read_port: 端口文件读取逻辑
"""
import os
import time
import numpy as np
import pytest
import httpx


class TestReadPort:
    """_read_port 端口发现逻辑。"""

    def test_env_var_priority(self, monkeypatch, tmp_port_file):
        """环境变量优先于端口文件。"""
        from embed_client import _read_port

        monkeypatch.setenv("EMBED_SERVER_PORT", "9999")
        tmp_port_file.write_text("8888\n12345")

        assert _read_port() == 9999

    def test_port_file_fallback(self, monkeypatch, tmp_port_file):
        """无环境变量时从端口文件读取。"""
        from embed_client import _read_port

        monkeypatch.delenv("EMBED_SERVER_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_port_file.parent))
        tmp_port_file.write_text("9777\n54321")

        assert _read_port() == 9777

    def test_default_when_nothing_available(self, monkeypatch, tmp_path):
        """无环境变量、无端口文件 → 默认 9776。"""
        from embed_client import _read_port

        monkeypatch.delenv("EMBED_SERVER_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        assert _read_port() == 9776

    def test_invalid_port_file_content(self, monkeypatch, tmp_port_file):
        """端口文件内容损坏 → 默认 9776。"""
        from embed_client import _read_port

        monkeypatch.delenv("EMBED_SERVER_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_port_file.parent))
        tmp_port_file.write_text("not_a_port")

        assert _read_port() == 9776


class TestEncodeSuccess:
    """encode() 成功路径（集成测试）。"""

    def test_encode_single_returns_1d(self, running_embed_server):
        """单条文本 → 1D 向量 (dim,)。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        vec = client.encode("test sentence")
        assert vec.shape == (1024,), f"期望 (1024,)，实际 {vec.shape}"
        assert isinstance(vec, np.ndarray)

    def test_encode_list_returns_2d(self, running_embed_server):
        """多条文本 → 2D 向量 (N, dim)。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        vecs = client.encode(["hello", "world"])
        assert vecs.shape == (2, 1024), f"期望 (2, 1024)，实际 {vecs.shape}"

    def test_encode_accepts_convert_to_numpy_kwarg(self, running_embed_server):
        """A3: 接口兼容——接受 convert_to_numpy 参数（SentenceTransformer.encode 签名）。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        # 不应抛异常——kwargs 被 **kwargs 吃掉
        vec = client.encode("test", convert_to_numpy=True, batch_size=32)
        assert vec.shape == (1024,)


class TestPredictSuccess:
    """predict() 成功路径（集成测试）。"""

    def test_predict_returns_scores(self, running_embed_server):
        """返回 scores 数组。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        scores = client.predict([("query", "doc1"), ("query", "doc2")])
        assert scores.shape == (2,), f"期望 (2,)，实际 {scores.shape}"
        assert isinstance(scores, np.ndarray)

    def test_predict_empty_pairs(self, running_embed_server):
        """空 pairs → 空数组。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        scores = client.predict([])
        assert scores.shape == (0,)

    def test_predict_accepts_kwargs(self, running_embed_server):
        """A3: 接口兼容——接受 batch_size/activation_fn 等 kwargs。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        scores = client.predict([("q", "d")], batch_size=8, activation_fn="sigmoid")
        assert scores.shape == (1,)


class TestEncodeFailure:
    """F5: server 不可用时抛 RuntimeError（不降级）。"""

    def test_encode_raises_runtime_error(self, monkeypatch):
        """embed_server 未运行 → encode() 抛 RuntimeError。"""
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient()
        # 指向一个不存在的端口
        client._base_url = "http://127.0.0.1:1"  # port 1 通常没有服务

        with pytest.raises(RuntimeError, match="embed_server /embed 请求失败"):
            client.encode("test")

    def test_predict_raises_runtime_error(self, monkeypatch):
        """embed_server 未运行 → predict() 抛 RuntimeError。"""
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient()
        client._base_url = "http://127.0.0.1:1"

        with pytest.raises(RuntimeError, match="embed_server /rerank 请求失败"):
            client.predict([("q", "d")])

    def test_no_fallback_attribute(self):
        """确认降级逻辑已完全删除——_fallback 字段不存在。"""
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient()
        assert not hasattr(client, "_fallback"), "_fallback 字段仍存在"
        assert not hasattr(client, "_fallback_encode"), "_fallback_encode 方法仍存在"
        assert not hasattr(client, "_fallback_predict"), "_fallback_predict 方法仍存在"
        assert not hasattr(client, "_confirmed_available"), "_confirmed_available 字段仍存在"


class TestLayeredTimeout:
    """F8: 分层超时——首次 60s，后续 10s。"""

    def test_first_request_uses_60s_timeout(self):
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient.__new__(HttpEmbedClient)  # 不触发 __init__
        client._client_first = httpx.Client(timeout=60.0)
        client._client_normal = httpx.Client(timeout=10.0)
        client._first_request = True

        assert client._client_first.timeout == httpx.Timeout(60.0)

    def test_normal_request_uses_10s_timeout(self):
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient.__new__(HttpEmbedClient)
        client._client_first = httpx.Client(timeout=60.0)
        client._client_normal = httpx.Client(timeout=10.0)
        client._first_request = True

        assert client._client_normal.timeout == httpx.Timeout(10.0)

    def test_first_request_flag_flips_after_success(self, running_embed_server):
        """首次请求成功后 _first_request 变为 False。"""
        from embed_client import HttpEmbedClient

        port, _ = running_embed_server
        client = HttpEmbedClient()
        client._base_url = f"http://127.0.0.1:{port}"

        assert client._first_request is True
        client.encode("test")
        assert client._first_request is False, "首次请求后 _first_request 应为 False"


class TestBaseUrlLazy:
    """base_url 延迟构建。"""

    def test_base_url_none_at_init(self):
        """__init__ 时不读端口——_base_url 为 None。"""
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient()
        assert client._base_url is None

    def test_base_url_built_on_first_access(self, monkeypatch, tmp_port_file):
        """首次访问 base_url 时才读端口。"""
        from embed_client import HttpEmbedClient

        monkeypatch.delenv("EMBED_SERVER_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_port_file.parent))
        tmp_port_file.write_text("9777\n12345")

        client = HttpEmbedClient()
        assert client._base_url is None

        url = client.base_url
        assert url == "http://127.0.0.1:9777"
        assert client._base_url == "http://127.0.0.1:9777"  # 缓存
