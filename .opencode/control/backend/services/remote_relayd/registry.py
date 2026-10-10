"""relayd 节点注册表（纯内存; 单事件循环内使用，无锁）。

条目生命周期: register 建立连接绑定 → heartbeat 刷新 last_seen →
连接断开 drop; lookup 时按 NODE_OFFLINE_SEC 判定过期（过期视为离线）。
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from services.remote_crypto import SessionCrypto

NODE_OFFLINE_SEC = 90.0  # protocol.md §9（3× 心跳周期）


@dataclass
class NodeEntry:
    """单个 gateway 节点的注册态。"""

    node: str
    writer: asyncio.StreamWriter
    session: SessionCrypto          # gateway 信令会话（下发 punch_hint 用）
    ep: "tuple[str, int] | None" = None      # 最新 update_ep（UDP 公网映射）
    last_seen: float = field(default_factory=time.monotonic)


class Registry:
    """node_id → NodeEntry 查找表 + 待配对 sid 表。"""

    def __init__(self, clock: "object | None" = None) -> None:
        import typing
        self._clock: typing.Callable[[], float] = (  # type: ignore[no-any-reassign]
            clock if clock is not None else time.monotonic)
        self._nodes: dict[str, NodeEntry] = {}
        self._sid_node: dict[str, str] = {}   # 一次性 sid → node（lookup 生成; relay 配对消费）

    # ── 节点表 ────────────────────────────────────────

    def register(self, node: str, writer: asyncio.StreamWriter,
                 session: SessionCrypto) -> None:
        """register/重连覆盖旧条目（旧连接由对端断开自然失效）。"""
        self._nodes[node] = NodeEntry(node=node, writer=writer, session=session)

    def heartbeat(self, node: str) -> bool:
        entry = self._nodes.get(node)
        if entry is None:
            return False
        entry.last_seen = self._clock()
        return True

    def update_ep(self, node: str, ep: "tuple[str, int]") -> bool:
        entry = self._nodes.get(node)
        if entry is None:
            return False
        entry.ep = ep
        entry.last_seen = self._clock()
        return True

    def drop(self, node: str, writer: "asyncio.StreamWriter | None" = None) -> None:
        """注销节点; writer 传入时仅当条目仍属于该连接才删（防旧连接 EOF
        误删新注册——NAT 半死连接的迟到 RST 场景）。"""
        entry = self._nodes.get(node)
        if entry is None:
            return
        if writer is not None and entry.writer is not writer:
            return  # 条目已被新连接覆盖——不动
        self._nodes.pop(node, None)

    def get(self, node: str) -> "NodeEntry | None":
        entry = self._nodes.get(node)
        if entry is None:
            return None
        if self._clock() - entry.last_seen > NODE_OFFLINE_SEC:
            return None  # 过期视为离线（条目保留——恢复心跳即复活）
        return entry

    def nodes_online(self) -> list[str]:
        return [n for n in self._nodes if self.get(n) is not None]

    # ── 一次性 sid（P6 中继配对消费）───────────────────

    def new_sid(self, node: str, sid: str) -> None:
        """lookup 时生成（sid 由 server 层产生; 记录归属节点）。"""
        self._sid_node[sid] = node

    def peek_sid(self, sid: str) -> "str | None":
        """查看 sid 归属节点（不消费）。"""
        return self._sid_node.get(sid)

    def take_sid(self, sid: str) -> "str | None":
        """消费一次性 sid → node; 不存在/已用返回 None。"""
        return self._sid_node.pop(sid, None)
