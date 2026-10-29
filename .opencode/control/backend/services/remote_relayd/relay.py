"""relayd 中继会话管理（protocol.md §4.2/§7）。

配对模型: lookup 生成一次性 sid（registry.new_sid）→ client relay_open 携带
sid 建待配对会话 → client/gateway 各开一条新 TCP（同 Noise 准入），首条加密
消息 relay_attach / relay_join → 两侧齐即回 relay_start 并启动双向字节管道
（管道内是端到端加密 TCP 帧，relayd 不解析）→ sid 消费。

server 层只调三个入口: open()/add_side()/sweep()。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import cast
from dataclasses import dataclass, field

from services.remote_relayd.registry import Registry

logger = logging.getLogger(__name__)

RELAY_PAIR_TIMEOUT_SEC = 30.0


@dataclass
class _PendingSession:
    """待配对会话。"""

    sid: str
    node: str
    client: "tuple[asyncio.StreamReader, asyncio.StreamWriter] | None" = None
    gw: "tuple[asyncio.StreamReader, asyncio.StreamWriter] | None" = None
    created: float = field(default_factory=time.monotonic)
    paired_evt: asyncio.Event = field(default_factory=asyncio.Event)
    pipes: "list[asyncio.Task[None]] | None" = None


class RelayManager:
    """中继会话表 + 配对 + 字节管道（单事件循环内使用）。"""

    def __init__(self, registry: Registry) -> None:
        self._registry = registry
        self._pending: dict[str, _PendingSession] = {}

    # ── 信令侧 ────────────────────────────────────────

    def open(self, sid: str) -> "str | None":
        """relay_open: 校验 sid pending → 建待配对会话 → 返回目标节点名。"""
        node = self._registry.peek_sid(sid)
        if node is None:
            return None
        self.sweep()
        self._pending[sid] = _PendingSession(sid=sid, node=node)
        return node

    # ── 数据连接侧 ────────────────────────────────────

    async def add_side(self, sid: str, role: str,
                       reader: asyncio.StreamReader,
                       writer: asyncio.StreamWriter) -> "list[asyncio.Task[None]] | str":
        """数据连接首消息处理（relay_attach/relay_join）。

        首侧挂起等对侧; 第二侧配对并启动管道。返回管道任务列表（成功）
        或错误码（"bad_sid"）。成功方回 relay_start 后应等待管道终态。
        """
        session = self._pending.get(sid)
        if session is None:
            return "bad_sid"
        if (role == "relay_attach" and session.client is not None) or \
                (role != "relay_attach" and session.gw is not None):
            return "bad_sid"
        if role == "relay_attach":
            session.client = (reader, writer)
        else:
            session.gw = (reader, writer)
        if session.client is not None and session.gw is not None:
            self._registry.take_sid(sid)  # 一次性消费
            self._pending.pop(sid, None)
            session.pipes = RelayPipe(session.client, session.gw).start()
            logger.info("中继配对完成 sid=%s node=%s", sid, session.node)
            session.paired_evt.set()
            return session.pipes
        try:
            await asyncio.wait_for(session.paired_evt.wait(),
                                   timeout=RELAY_PAIR_TIMEOUT_SEC)
        except asyncio.TimeoutError:
            self._pending.pop(sid, None)
            logger.warning("中继配对超时（%ss）sid=%s", RELAY_PAIR_TIMEOUT_SEC, sid)
            return "bad_sid"
        return session.pipes if session.pipes is not None else "bad_sid"

    # ── 维护 ──────────────────────────────────────────

    def sweep(self, now: float | None = None) -> int:
        """清理超时未配对会话; 返回清理数。"""
        now = now if now is not None else time.monotonic()
        expired = [sid for sid, s in self._pending.items()
                   if now - s.created > RELAY_PAIR_TIMEOUT_SEC]
        for sid in expired:
            session = self._pending.pop(sid)
            session.paired_evt.set()  # 唤醒等待方（pipes=None → bad_sid）
            for conn in (session.client, session.gw):
                if conn is not None:
                    conn[1].close()
        return len(expired)

class RelayPipe:
    """中继字节管道（双向 pump——任一方向断开即整体终态，writer.close 级联）。

    生命周期收口: start() 建双泵任务 / wait() 等终态 / close() 主动断。
    relayd 对管道内容零解析（VPS 零知识——端到端加密帧透传）。
    """

    def __init__(self, client: "tuple[asyncio.StreamReader, asyncio.StreamWriter]",
                 gw: "tuple[asyncio.StreamReader, asyncio.StreamWriter]") -> None:
        self._client = client
        self._gw = gw
        self._tasks: "list[asyncio.Task[None]]" = []

    def start(self) -> "list[asyncio.Task[None]]":
        """启动双向泵; 返回任务列表（server 层 gather 等终态用）。"""
        loop = asyncio.get_running_loop()
        self._tasks = [
            loop.create_task(self._pump(self._client[0], self._gw[1])),
            loop.create_task(self._pump(self._gw[0], self._client[1])),
        ]
        return self._tasks

    async def wait(self) -> None:
        """等待管道终态（对端断开/主动 close）。"""
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def close(self) -> None:
        for task in self._tasks:
            task.cancel()
        await self.wait()

    async def _pump(self, reader: asyncio.StreamReader,
                    writer: asyncio.StreamWriter) -> None:
        """单向字节搬运（EOF/断开即止）。"""
        peer = cast("tuple[str, int] | None", writer.get_extra_info("peername"))
        try:
            while True:
                chunk = await reader.read(65536)
                if not chunk:
                    break
                writer.write(chunk)
                await writer.drain()
        except (ConnectionError, OSError):
            pass
        finally:
            logger.info("中继泵结束 peer=%s", peer)
            try:
                writer.close()
            except (ConnectionError, OSError):
                pass
