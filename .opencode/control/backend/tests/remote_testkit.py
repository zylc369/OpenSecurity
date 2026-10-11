"""remote-p2p 测试工具（SignalClient 已上移 services/remote_signal.py 供三端复用）。"""
from __future__ import annotations

import asyncio

from services.remote_crypto import PSK_LEN, SessionCrypto
from services.remote_signal import SignalClient  # noqa: F401 —— 测试侧便捷 re-export


def make_psk(seed: int = 0) -> bytes:
    return bytes((i + seed) % 256 for i in range(PSK_LEN))


class RelayPipeClient(SignalClient):
    """测试便利: 中继数据连接的管道态裸字节收发（relay_start 后纯字节管道）。"""

    async def send_raw(self, data: bytes) -> None:
        """管道态裸字节发送（不经帧/加密——管道透传端到端帧）。"""
        self._writer.write(data)
        await self._writer.drain()

    async def recv_raw(self, timeout: float = 5.0) -> bytes:
        """管道态裸字节接收。"""
        chunk = await asyncio.wait_for(self._reader.read(65536), timeout=timeout)
        if not chunk:
            raise ConnectionError("对端已断开")
        return chunk


class P2pDirectClient:
    """测试桩: 客户端直连路径（打洞 → Noise → UDP 会话; transport 的协议参考）。"""

    def __init__(self, psk: bytes) -> None:
        from services.remote_crypto import SessionCrypto
        self._psk = psk
        self._transport: "asyncio.DatagramTransport | None" = None
        self._session: "SessionCrypto | None" = None
        self._inbox: "asyncio.Queue[tuple[bytes, tuple[str, int]]]" = asyncio.Queue()
        self._frag_seq = 0

    class _Proto(asyncio.DatagramProtocol):
        def __init__(self, inbox: "asyncio.Queue[tuple[bytes, tuple[str, int]]]") -> None:
            self.transport: "asyncio.DatagramTransport | None" = None
            self._inbox = inbox

        def connection_made(self, transport: asyncio.BaseTransport) -> None:  # type: ignore[override]
            import asyncio as _a
            from typing import cast as _c
            self.transport = _c("_a.DatagramTransport", transport)

        def datagram_received(self, data: bytes, addr: "tuple[str, int]") -> None:  # type: ignore[override]
            self._inbox.put_nowait((data, addr))

    async def _ensure_udp(self) -> "tuple[str, int]":
        if self._transport is None:
            loop = asyncio.get_running_loop()
            _, proto = await loop.create_datagram_endpoint(
                lambda: self._Proto(self._inbox), local_addr=("127.0.0.1", 0))
            assert isinstance(proto, self._Proto) and proto.transport is not None
            self._transport = proto.transport
        transport = self._transport
        assert transport is not None
        return cast("tuple[str, int]", transport.get_extra_info("sockname"))

    async def _recv(self, timeout: float = 3.0) -> "tuple[bytes, tuple[str, int]]":
        return await asyncio.wait_for(self._inbox.get(), timeout=timeout)

    async def punch_and_handshake(self, sid: str, gw_ep: "tuple[str, int]") -> None:
        """互射 + Noise 握手（msg1→msg2）。"""
        from services.remote_crypto import NoiseHandshake, SessionCrypto
        from services.remote_crypto import PunchAuth
        import json as _json
        local = await self._ensure_udp()
        packet = (_json.dumps({"t": "punch", "sid": sid,
                               "mac": PunchAuth(self._psk).mac(sid)}) + "\n").encode()
        initiator = NoiseHandshake(initiator=True, psk=self._psk)
        msg1 = initiator.write_message()
        assert self._transport is not None
        # 互射 + 握手首包（burst 同发——回环立即通）
        for _ in range(3):
            self._transport.sendto(packet, gw_ep)
        self._transport.sendto(msg1, gw_ep)
        # 等 gateway 的 punch 回包（确认洞通）与 msg2
        got_msg2 = False
        for _ in range(10):
            data, _ = await self._recv()
            if data.startswith(b"{"):
                continue  # gateway 的 punch 回包
            if len(data) == 48 and not got_msg2:
                initiator.read_message(data)
                got_msg2 = True
                break
        if not got_msg2:
            raise ConnectionError("直连握手超时（未收到 msg2）")
        i_send, i_recv = initiator.split()
        self._session = SessionCrypto(i_send, i_recv)

    async def send_msg(self, msg: dict[str, object]) -> None:
        """会话帧发送（含分片）。"""
        from services.remote_crypto import Fragmenter, FrameCodec, encode_msg
        assert self._session is not None and self._transport is not None
        codec = FrameCodec()
        plaintext = encode_msg(msg)
        if Fragmenter.need_split(plaintext):
            # 测试桩简化: 分片逐发（接收端 Reassembler 重组）
            self._frag_seq += 1
            for frag in Fragmenter().split(plaintext, msg_id=self._frag_seq):
                ct, ctr = self._session.encrypt(encode_msg(frag))
                self._transport.sendto(codec.pack_udp(ctr, ct), self._gw_ep)
        else:
            ct, ctr = self._session.encrypt(plaintext)
            self._transport.sendto(codec.pack_udp(ctr, ct), self._gw_ep)

    _gw_ep: "tuple[str, int]" = ("", 0)

    async def recv_msg(self, timeout: float = 3.0) -> dict[str, object]:
        """会话帧接收（含分片重组简化: 等完整——依赖小消息）。"""
        from services.remote_crypto import FrameCodec, Reassembler, decode_msg
        from services.remote_crypto import CryptoError
        assert self._session is not None
        codec = FrameCodec()
        reasm: "Reassembler | None" = None
        while True:
            data, _ = await self._recv(timeout)
            try:
                counter, ciphertext = codec.unpack_udp(data)
                plaintext = self._session.decrypt(ciphertext, counter)
            except CryptoError:
                continue
            msg = decode_msg(plaintext)
            if str(msg.get("t")) == "_frag":
                if reasm is None:
                    reasm = Reassembler(msg)
                assembled = reasm.feed(msg)
                if assembled is not None:
                    return decode_msg(assembled)
                continue
            return msg

    def set_gw_ep(self, ep: "tuple[str, int]") -> None:
        self._gw_ep = ep

    async def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None


class RelayE2eClient(RelayPipeClient):
    """测试桩: 中继路径的端到端客户端（attach → relay_start → 端到端握手 → 会话）。

    会话消息与 UdpSession 同构（TCP 帧承载; 分片消息走 Reassembler）。
    """

    _e2e: "SessionCrypto | None" = None

    async def e2e_handshake(self, psk: bytes) -> None:
        """relay_start 之后在管道上与 gateway 完成端到端 Noise 握手。"""
        from services.remote_crypto import FrameCodec, NoiseHandshake, SessionCrypto
        codec = FrameCodec()
        initiator = NoiseHandshake(initiator=True, psk=psk)
        self._writer.write(codec.pack_tcp(initiator.write_message()))
        await self._writer.drain()
        frames = self._frames.feed(b"")
        while not frames:
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=5.0)
            if not chunk:
                raise ConnectionError("端到端握手期间对端断开")
            frames = self._frames.feed(chunk)
        initiator.read_message(frames[0])
        i_send, i_recv = initiator.split()
        self._e2e = SessionCrypto(i_send, i_recv)  # noqa: SLF001 —— 测试桩

    @property
    def e2e(self) -> "SessionCrypto":
        assert self._e2e is not None, "先调 e2e_handshake"
        return self._e2e

    async def send_e2e(self, msg: dict[str, object]) -> None:
        """端到端会话帧发送。"""
        from services.remote_crypto import FrameCodec, encode_msg
        self._writer.write(FrameCodec().pack_tcp(self.e2e.encrypt_seq(encode_msg(msg))))
        await self._writer.drain()

    async def recv_e2e(self, timeout: float = 5.0) -> "object":
        """端到端会话帧接收（wire 消息对象）。"""
        from services import remote_wire
        frames = self._frames.feed(b"")
        while not frames:
            chunk = await asyncio.wait_for(self._reader.read(4096), timeout=timeout)
            if not chunk:
                raise ConnectionError("对端已断开")
            frames = self._frames.feed(chunk)
        return remote_wire.decode(self.e2e.decrypt_seq(frames[0]))




from typing import cast  # noqa: E402 —— 模块级 cast（类内已局部引用）
