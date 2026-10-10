"""信令连接客户端（Noise 准入 + 帧加密收发）——gateway / transport / 测试共用。"""
from __future__ import annotations

import asyncio
import collections
from typing import TypeVar

from services.remote_crypto import (
    FrameCodec,
    NoiseHandshake,
    SessionCrypto,
    TcpFrameReader,
    decode_msg,
    encode_msg,
)


TSelf = TypeVar("TSelf", bound="SignalClient")


class SignalClient:
    """信令连接客户端（protocol.md §4.1 消息的可靠收发）。"""

    def __init__(self, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter, session: SessionCrypto) -> None:
        self._reader = reader
        self._writer = writer
        self._session = session
        self._frames = TcpFrameReader()
        self._inbox: "collections.deque[bytes]" = collections.deque()
        self._codec = FrameCodec()

    @classmethod
    async def connect(cls: "type[TSelf]", host: str, port: int, psk: bytes,
                      handshake_timeout: float = 5.0) -> "TSelf":
        codec = FrameCodec()
        reader, writer = await asyncio.open_connection(host, port)
        try:
            initiator = NoiseHandshake(initiator=True, psk=psk)
            msg1 = initiator.write_message()
            writer.write(codec.pack_tcp(msg1))
            await writer.drain()
            # 服务端回 msg2（首帧; 复用同一 reader 防 TCP 分段丢前半帧）
            frame_reader = TcpFrameReader()
            while True:
                chunk = await asyncio.wait_for(reader.read(4096),
                                               timeout=handshake_timeout)
                if not chunk:
                    raise ConnectionError("服务端在握手期间断开")
                frames = frame_reader.feed(chunk)
                if frames:
                    initiator.read_message(frames[0])
                    break
        except BaseException:
            writer.close()  # 失败先关连接（防泄漏 transport 卡住对端/事件循环清理）
            raise
        i_send, i_recv = initiator.split()
        return cls(reader, writer, SessionCrypto(i_send, i_recv))

    async def send(self, msg: dict[str, object]) -> None:
        self._writer.write(self._codec.pack_tcp(self._session.encrypt_seq(encode_msg(msg))))
        await self._writer.drain()

    async def recv(self, timeout: float = 30.0) -> dict[str, object]:
        """取下一条消息。

        一次 read 可能携带多帧——必须全部入 inbox 逐条交付
        （只取首帧会静默丢弃后续帧: lookup 与 relay_open 的下发紧邻时必炸）。
        """
        while not self._inbox:
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=timeout)
            if not chunk:
                raise ConnectionError("对端已断开")
            self._inbox.extend(self._frames.feed(chunk))
        return decode_msg(self._session.decrypt_seq(self._inbox.popleft()))

    @property
    def session(self) -> SessionCrypto:
        """信令会话密钥（下发/接收加密消息复用; punch_hint 场景由 relayd 侧使用）。"""
        return self._session

    async def close(self) -> None:
        self._writer.close()
