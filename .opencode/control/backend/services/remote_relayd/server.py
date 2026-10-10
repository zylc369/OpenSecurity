"""relayd 服务端主循环（P5: TCP 准入 + 信令; P6 增补中继; P7 增补 UDP STUN）。

连接生命周期（protocol.md §2/§8）:
  1. peer IP 封禁检查 → RST
  2. 首个 TCP 帧承载 Noise NNpsk2 握手（NOISE_WAIT 内完成; 失败计数/断开）
  3. 会话加密信令循环: register（gateway） / lookup·relay_open（client）
     / heartbeat / update_ep —— 消息处理独立函数，便于单测
"""
from __future__ import annotations

import asyncio
import logging
from typing import cast

from services.remote_crypto import (
    CryptoError,
    FrameCodec,
    NoiseHandshake,
    PunchAuth,
    SessionCrypto,
    TcpFrameReader,
    decode_msg,
    encode_msg,
)
from services.remote_relayd.failban import FailBan
from services.remote_relayd.registry import Registry
from services.remote_relayd.relay import RelayManager
from services.remote_relayd.stun import StunProtocol

logger = logging.getLogger(__name__)

NOISE_WAIT_SEC = 10.0


def _node_id(msg: dict[str, object]) -> str:
    """消息里的 node 字段收口（非 str → 空串）。"""
    value = msg.get("node")
    return value if isinstance(value, str) else ""


def _parse_ep(value: object) -> "tuple[str, int] | None":
    """endpoint 字段收口: [ip, port] → (str, int); 非法 → None。"""
    if not isinstance(value, list):
        return None
    items = cast("list[object]", value)
    if len(items) != 2:
        return None
    host, port = items[0], items[1]
    if not isinstance(host, str) or not isinstance(port, int) or isinstance(port, bool):
        return None
    return host, port


class RelayServer:
    """relayd 实例（单进程单实例; serve() 后 run_forever 由调用方控制）。"""

    def __init__(self, psk: bytes) -> None:
        self._psk = psk
        self._codec = FrameCodec()
        self._punch_auth = PunchAuth(psk)
        self.registry = Registry()
        self.failban = FailBan()
        self.relay = RelayManager(self.registry)
        self._server: asyncio.Server | None = None
        self._stun_transport: "asyncio.DatagramTransport | None" = None
        self._handlers: set[asyncio.Task[None]] = set()

    # ── 生命周期 ──────────────────────────────────────

    async def serve(self, host: str = "0.0.0.0", port: int = 41000) -> int:
        """启动 TCP（信令+中继）与 UDP（STUN，同端口）监听; 返回实际 TCP 端口。"""
        self._server = await asyncio.start_server(self._handle_conn, host, port)
        sockets = self._server.sockets or []
        tcp_port = sockets[0].getsockname()[1] if sockets else port
        stun_transport, _ = await asyncio.get_running_loop().create_datagram_endpoint(
            StunProtocol, local_addr=(host, tcp_port))
        self._stun_transport = stun_transport  # type: ignore[assignment]
        return tcp_port

    async def close(self) -> None:
        """关闭监听并断开全部活跃连接（wait_closed 会等 handler 结束——须先 cancel）。"""
        if self._server is not None:
            self._server.close()
            for task in list(self._handlers):
                task.cancel()
            if self._handlers:
                await asyncio.gather(*self._handlers, return_exceptions=True)
            await self._server.wait_closed()
            self._server = None
        if self._stun_transport is not None:
            self._stun_transport.close()
            self._stun_transport = None

    # ── 连接处理 ──────────────────────────────────────

    async def _handle_conn(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._handlers.add(task)
        peername = writer.get_extra_info("peername") or ("?", 0)
        ip = str(peername[0])
        if self.failban.is_banned(ip):
            writer.close()
            return
        session = await self._admit(reader, writer, ip)
        if session is None:
            return
        try:
            await self._signal_loop(reader, writer, session)
        except (CryptoError, asyncio.IncompleteReadError, ConnectionError):
            pass  # 对端断开/帧异常——正常终态
        except asyncio.CancelledError:
            pass  # server.close 主动断开
        finally:
            writer.close()
            if task is not None:
                self._handlers.discard(task)

    async def _admit(self, reader: asyncio.StreamReader,
                     writer: asyncio.StreamWriter,
                     ip: str) -> "SessionCrypto | None":
        """Noise 准入握手; 失败计数/封禁，成功清零。"""
        try:
            head = await asyncio.wait_for(reader.read(4), NOISE_WAIT_SEC)
            frame_reader = TcpFrameReader()
            frames = frame_reader.feed(head)
            while not frames:
                chunk = await asyncio.wait_for(reader.read(4096), NOISE_WAIT_SEC)
                if not chunk:
                    return None
                frames = frame_reader.feed(chunk)
            responder = NoiseHandshake(initiator=False, psk=self._psk)
            responder.read_message(frames[0])
            msg2 = responder.write_message()
            writer.write(self._codec.pack_tcp(msg2))
            await writer.drain()
            r_send, r_recv = responder.split()
            self.failban.reset(ip)
            return SessionCrypto(r_send, r_recv)
        except (asyncio.TimeoutError, CryptoError, ValueError, OSError):
            banned = self.failban.note_fail(ip)
            logger.warning("准入失败 ip=%s banned=%s", ip, banned)
            return None

    async def _signal_loop(self, reader: asyncio.StreamReader,
                           writer: asyncio.StreamWriter,
                           session: SessionCrypto) -> None:
        """连接消息循环: 首消息为中继角色（relay_attach/join）→ 数据连接;
        否则信令循环（register 后绑定节点; 心跳/lookup 同通道）。"""
        registered_node: "str | None" = None
        frame_reader = TcpFrameReader()
        first = True
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                break
            for payload in frame_reader.feed(chunk):
                msg = decode_msg(session.decrypt_seq(payload))
                if first and str(msg.get("t")) in ("relay_attach", "relay_join"):
                    await self._relay_data_conn(msg, reader, writer, session)
                    return  # 中继连接生命周期到此为止（管道终态）
                first = False
                if registered_node is None and str(msg.get("t")) == "register":
                    registered_node = str(msg.get("node", ""))
                reply = await self.handle_msg(msg, writer, session,
                                              node=registered_node)
                if reply is not None:
                    writer.write(self._codec.pack_tcp(session.encrypt_seq(
                        encode_msg(reply))))
                    await writer.drain()
        if registered_node is not None:
            logger.info("gateway 信令断开 drop node=%s", registered_node)
            self.registry.drop(registered_node, writer=writer)
        else:
            peer = writer.get_extra_info("peername") or ("?", 0)
            logger.info("客户端信令连接关闭 peer=%s:%s", peer[0], peer[1])

    async def _relay_data_conn(self, msg: dict[str, object],
                               reader: asyncio.StreamReader,
                               writer: asyncio.StreamWriter,
                               session: SessionCrypto) -> None:
        """中继数据连接: add_side → relay_start → 等管道终态。"""
        sid = msg.get("sid")
        result = await self.relay.add_side(
            sid if isinstance(sid, str) else "", str(msg.get("t")), reader, writer)
        if isinstance(result, str):
            writer.write(self._codec.pack_tcp(session.encrypt_seq(encode_msg(
                {"t": "error", "code": result, "msg": "中继配对失败"}))))
            await writer.drain()
            writer.close()
            return
        writer.write(self._codec.pack_tcp(session.encrypt_seq(
            encode_msg({"t": "relay_start"}))))
        await writer.drain()
        await asyncio.gather(*result, return_exceptions=True)

    # ── 信令消息处理（独立函数; 单测直接调）─────────────

    async def handle_msg(self, msg: dict[str, object],
                         writer: asyncio.StreamWriter,
                         session: SessionCrypto,
                         node: "str | None") -> "dict[str, object] | None":
        t = str(msg.get("t", ""))
        if t == "register":
            self.registry.register(_node_id(msg), writer, session)
            return {"t": "registered", "heartbeat_sec": 30}
        if t == "heartbeat":
            if node is None or not self.registry.heartbeat(node):
                return {"t": "error", "code": "proto_error", "msg": "未注册即心跳"}
            return {"t": "heartbeat_ack"}
        if t == "update_ep":
            ep = _parse_ep(msg.get("ep"))
            if node is None or ep is None:
                return {"t": "error", "code": "proto_error", "msg": "update_ep 参数非法"}
            ok = self.registry.update_ep(node, ep)
            return None if ok else {"t": "error", "code": "proto_error",
                                    "msg": "未注册即更新端点"}
        if t == "lookup":
            logger.info("lookup node=%s from client（信令）", msg.get("node"))
            client_ep = _parse_ep(msg.get("udp_ep"))
            return await self._lookup(_node_id(msg), writer,
                                      session, list(client_ep) if client_ep else None)
        if t == "relay_open":
            logger.info("relay_open node=%s sid=%s", msg.get("node"), msg.get("sid"))
            sid = msg.get("sid")
            node = _node_id(msg)
            if (not isinstance(sid, str) or not node
                    or self.relay.open(sid) is None):
                return {"t": "error", "code": "bad_sid", "msg": "sid 无效或已消费"}
            entry = self.registry.get(node)
            if entry is None:
                return {"t": "endpoints", "ok": False, "error": "node_offline"}
            # 通知 gateway 开数据连接 join（protocol.md §4.2 relay_peer）
            try:
                entry.writer.write(self._codec.pack_tcp(
                    entry.session.encrypt_seq(
                        encode_msg({"t": "relay_peer", "sid": sid}))))
                await entry.writer.drain()
            except (ConnectionError, OSError):
                return {"t": "endpoints", "ok": False, "error": "node_offline"}
            sockname = writer.get_extra_info("sockname") or ("0.0.0.0", 0)
            return {"t": "relay_ready", "sid": sid,
                    "addr": [str(sockname[0]), int(sockname[1])]}
        return {"t": "error", "code": "proto_error", "msg": f"未知消息类型: {t}"}

    async def _lookup(self, node: str, client_writer: asyncio.StreamWriter,
                      session: SessionCrypto,
                      client_ep: "list[object] | None") -> dict[str, object]:
        """查询节点; 在线则生成一次性 sid + 向 gateway 下发 punch_hint。

        punch_hint 的 client endpoint: 优先 client 携带的 udp_ep（STUN 预探测，
        protocol.md §6）; 未携带则用信令 TCP 源地址兜底。
        """
        entry = self.registry.get(node)
        if entry is None:
            return {"t": "endpoints", "ok": False, "error": "node_offline"}
        sid = PunchAuth.gen_sid()
        self.registry.new_sid(node, sid)
        hint: dict[str, object] = {"t": "punch_hint", "sid": sid,
                                   "client": client_ep if client_ep is not None
                                   else self._tcp_peer_ep(client_writer)}
        try:
            entry.writer.write(self._codec.pack_tcp(
                entry.session.encrypt_seq(encode_msg(hint))))
            await entry.writer.drain()
        except (ConnectionError, OSError):
            return {"t": "endpoints", "ok": False, "error": "node_offline"}
        return {"t": "endpoints", "ok": True,
                "gw": [entry.ep[0], entry.ep[1]] if entry.ep else ["", 0],
                "sid": sid}

    def _tcp_peer_ep(self, writer: asyncio.StreamWriter) -> list[object]:
        """信令 TCP 连接源地址（punch_hint 兜底值）。"""
        peername = writer.get_extra_info("peername") or ("0.0.0.0", 0)
        return [str(peername[0]), int(peername[1])]
