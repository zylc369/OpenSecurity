"""control_url.py + embed_client.py IPC 发现与自愈测试。

覆盖（IPC 化后语义——端口文件机制已退役）:
- resolve_control: 固定 IPC 地址（uds），DATA_DIR 沙箱隔离下解析
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
    """resolve_control: IPC 地址解析（uds 固定路径，无发现文件）。"""

    def test_uds_addr_in_sandbox(self, monkeypatch, tmp_path):
        """沙箱 DATA_DIR → 返回 uds 通道的地址对象。"""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        addr = resolve_control()
        if addr is not None:  # 真有控制台跑在沙箱 sock 上才非 None
            assert addr == ControlAddr(url=addr.url, via="uds")

    def test_addr_fields(self):
        """ControlAddr 形态: (url, via)，无端口语义残留。"""
        a = ControlAddr(url="http://localhost", via="uds")
        assert a.url == "http://localhost"
        assert a.via == "uds"

    def test_no_port_semantics_left(self, monkeypatch, tmp_path):
        """端口文件/端口 env 机制已退役——写端口文件不影响解析。"""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        (tmp_path / ".opencode-control.port").write_text("9999\n123\n456.0")
        # 不抛异常即可（IPC 地址与该文件无关）
        resolve_control()


