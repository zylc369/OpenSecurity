"""relayd UDP STUN（protocol.md §4.4——简化自定协议，非 RFC 5389）。

UDP 端口收明文 JSON `{"t":"stun"}\\n` → 回 `{"t":"stun.resp","src":[ip,port]}\\n`
（告知发送方的公网 UDP 映射）。其他包静默忽略（打洞包 client↔gateway 直发不经此）。
"""
from __future__ import annotations

import asyncio
import json
import logging

logger = logging.getLogger(__name__)


def build_stun_response(peer: "tuple[str, int]") -> bytes:
    return (json.dumps({"t": "stun.resp", "src": [peer[0], peer[1]]}) + "\n").encode()


def parse_stun_request(data: bytes) -> bool:
    """判断是否为合法 STUN 请求（容忍未知字段/空白）。"""
    from typing import cast
    try:
        obj = cast("dict[str, object]", json.loads(data))
    except ValueError:
        return False
    return isinstance(obj, dict) and obj.get("t") == "stun"


class StunProtocol(asyncio.DatagramProtocol):
    """UDP 监听协议: STUN 回显（其余忽略）。"""

    def __init__(self) -> None:
        self.transport: "asyncio.DatagramTransport | None" = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:  # type: ignore[override]
        self.transport = transport  # type: ignore[assignment]

    def datagram_received(self, data: bytes, addr: "tuple[str, int]") -> None:  # type: ignore[override]
        if parse_stun_request(data):
            assert self.transport is not None
            self.transport.sendto(build_stun_response(addr), addr)
