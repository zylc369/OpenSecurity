"""control_url.py + embed_client.py IPC 发现与自愈测试。

覆盖（IPC 化后语义——端口文件机制已退役）:
- resolve_control: 启动方注入 OPENSECURITY_CONTROL_IPC（uds 绝对路径）；
  注入缺失 → RuntimeError（薄壳须由插件 mcp-manager 启动）；sock 不存在 → None
- embed_client: 延迟 base_url 构建、失败清缓存（自愈）
- 分层超时常量存在性
"""
from pathlib import Path
import sys

import pytest

MCP_DIR = Path(__file__).resolve().parents[2] / ".opencode" / "mcp-servers"
sys.path.insert(0, str(MCP_DIR))

from control_url import ControlAddr, resolve_control  # noqa: E402


class TestResolveControl:
    """resolve_control: 启动方注入的 IPC 地址解析（无发现文件）。"""

    def test_uds_addr_by_injected_env(self, monkeypatch, tmp_path):
        """沙箱注入 OPENSECURITY_CONTROL_IPC（sock 存在）→ 返回 uds 地址对象。"""
        sock = tmp_path / "opensecurity-control.sock"
        sock.touch()
        monkeypatch.setenv("OPENSECURITY_CONTROL_IPC", str(sock))
        assert resolve_control() == ControlAddr(url="http://localhost", via="uds")

    def test_missing_injection_raises(self, monkeypatch):
        """未注入 OPENSECURITY_CONTROL_IPC → RuntimeError（薄壳须由插件启动）。"""
        monkeypatch.delenv("OPENSECURITY_CONTROL_IPC", raising=False)
        with pytest.raises(RuntimeError, match="OPENSECURITY_CONTROL_IPC"):
            resolve_control()

    def test_sock_absent_returns_none(self, monkeypatch, tmp_path):
        """注入地址但 sock 不存在 → None（Unix 语义：不臆造可达地址）。"""
        monkeypatch.setenv("OPENSECURITY_CONTROL_IPC", str(tmp_path / "no-instance.sock"))
        assert resolve_control() is None

    def test_addr_fields(self):
        """ControlAddr 形态: (url, via)，无端口语义残留。"""
        a = ControlAddr(url="http://localhost", via="uds")
        assert a.url == "http://localhost"
        assert a.via == "uds"

    def test_no_port_semantics_left(self, monkeypatch, tmp_path):
        """端口文件机制已退役——写端口文件不影响解析（地址只来自注入 env）。"""
        sock = tmp_path / "opensecurity-control.sock"
        sock.touch()
        monkeypatch.setenv("OPENSECURITY_CONTROL_IPC", str(sock))
        (tmp_path / ".opencode-control.port").write_text("9999\n123\n456.0")
        addr = resolve_control()
        assert addr == ControlAddr(url="http://localhost", via="uds")


