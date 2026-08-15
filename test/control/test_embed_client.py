"""control_url.py + embed_client.py 端口发现与自愈测试。

覆盖：
- control_url.resolve_control：环境变量优先、端口文件回退、格式容错
- embed_client.base_url：延迟构建、失败清缓存（换端口自愈）
- 降级逻辑不存在
- 分层超时
"""
import httpx
import numpy as np
import pytest


MCP_DIR = __import__("pathlib").Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers"
import sys
sys.path.insert(0, str(MCP_DIR))

from control_url import resolve_control, ControlAddr


class TestResolveControl:
    """resolve_control 地址解析优先级。"""

    def test_env_var_priority(self, monkeypatch, tmp_path):
        """环境变量优先于端口文件（测试覆盖场景）。"""
        monkeypatch.setenv("OPENCODE_CONTROL_PORT", "9999")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / ".opencode-control.port").write_text("8888\n123\n456.0")

        addr = resolve_control()
        assert addr == ControlAddr(port=9999, url="http://127.0.0.1:9999")

    def test_port_file_fallback(self, monkeypatch, tmp_path):
        """无环境变量时读端口文件第一行。"""
        monkeypatch.delenv("OPENCODE_CONTROL_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / ".opencode-control.port").write_text("9777\n54321\n1786460076.0")

        addr = resolve_control()
        assert addr.port == 9777
        assert addr.url == "http://127.0.0.1:9777"

    def test_none_when_nothing_available(self, monkeypatch, tmp_path):
        """无环境变量、无端口文件 → None。"""
        monkeypatch.delenv("OPENCODE_CONTROL_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        assert resolve_control() is None

    def test_invalid_port_file_content(self, monkeypatch, tmp_path):
        """端口文件损坏（第一行非数字）→ None。"""
        monkeypatch.delenv("OPENCODE_CONTROL_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / ".opencode-control.port").write_text("garbage\n123")

        assert resolve_control() is None

    def test_invalid_env_var_ignored(self, monkeypatch, tmp_path):
        """环境变量非数字 → 忽略，走端口文件。"""
        monkeypatch.setenv("OPENCODE_CONTROL_PORT", "not-a-port")
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / ".opencode-control.port").write_text("9776\n1\n1.0")

        assert resolve_control().port == 9776

    def test_addr_has_both_port_and_url(self, monkeypatch):
        """返回结构同时包含 port 和 url。"""
        monkeypatch.setenv("OPENCODE_CONTROL_PORT", "9776")
        addr = resolve_control()
        assert addr.port == 9776
        assert "9776" in addr.url


class TestBaseUrlLazyAndSelfHeal:
    """embed_client base_url 延迟构建 + 失败清缓存自愈。"""

    def _make_client(self):
        from embed_client import HttpEmbedClient
        return HttpEmbedClient()

    def test_base_url_none_at_init(self):
        client = self._make_client()
        assert client._base_url is None

    def test_base_url_built_from_port_file(self, monkeypatch, tmp_path):
        monkeypatch.delenv("OPENCODE_CONTROL_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / ".opencode-control.port").write_text("9777\n1\n1.0")

        client = self._make_client()
        assert client.base_url == "http://127.0.0.1:9777"
        assert client._base_url == "http://127.0.0.1:9777"  # 缓存

    def test_failure_clears_cache_then_re_resolves(self, monkeypatch, tmp_path):
        """换端口自愈：请求失败 → 缓存清空 → 端口文件更新后重新解析到新端口。"""
        monkeypatch.delenv("OPENCODE_CONTROL_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        port_file = tmp_path / ".opencode-control.port"

        # 初始指向一个无服务的端口（port 1）——不能用 9776（真实控制台可能在跑）
        port_file.write_text("1\n1\n1.0")
        client = self._make_client()
        assert client.base_url == "http://127.0.0.1:1"

        # 请求失败（port 1 无服务）→ _try_http 返回 None 且清缓存
        result = client._try_http("/embed", {"inputs": ["x"]})
        assert result is None
        assert client._base_url is None, "失败后 base_url 缓存应被清空"

        # 控制台换端口重启（端口文件被新控制台覆写为 9777）
        # base_url 是纯字符串构建不发网络请求，9777 无服务也不影响断言
        port_file.write_text("9777\n2\n2.0")
        assert client.base_url == "http://127.0.0.1:9777", "应重新解析到新端口"

    def test_encode_raises_when_port_unknown(self, monkeypatch, tmp_path):
        """端口完全未知（无 env、无文件）→ encode 抛 RuntimeError。"""
        monkeypatch.delenv("OPENCODE_CONTROL_PORT", raising=False)
        monkeypatch.setenv("DATA_DIR", str(tmp_path))

        client = self._make_client()
        with pytest.raises(RuntimeError, match="地址未知"):
            client.encode("test")


class TestNoFallback:
    """降级逻辑不存在。"""

    def test_no_fallback_attribute(self):
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient()
        assert not hasattr(client, "_fallback")
        assert not hasattr(client, "_fallback_encode")
        assert not hasattr(client, "_fallback_predict")

    def test_encode_raises_on_dead_port(self, monkeypatch, tmp_path):
        """指向死端口 → RuntimeError（不本地加载模型）。"""
        monkeypatch.setenv("OPENCODE_CONTROL_PORT", "1")  # port 1 无服务

        from embed_client import HttpEmbedClient
        client = HttpEmbedClient()
        with pytest.raises(RuntimeError, match="/embed 请求失败"):
            client.encode("test")


class TestLayeredTimeout:
    """分层超时：首次 60s，后续 10s。"""

    def test_timeout_values(self):
        from embed_client import HttpEmbedClient

        client = HttpEmbedClient()
        assert client._client_first.timeout == httpx.Timeout(60.0)
        assert client._client_normal.timeout == httpx.Timeout(10.0)
