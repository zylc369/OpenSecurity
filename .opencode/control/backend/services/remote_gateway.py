"""remote gateway（节点角色——Mac Mini 侧）。

职责（分段交付）:
- P8: 信令连接生命周期——注册/心跳/STUN 刷新 update_ep/断线指数退避重连
- P9: 固定 UDP socket 上的打洞应答（punch_hint→互射）+ 直连 UDP 会话（Noise+帧+分片）
- P10: 中继数据连接（relay_join）+ api.req 本机转发

纯组件设计: 构造参数显式注入（ConfigManager/lifespan 接线见 P14），
不 import 任何配置单例——便于单测与三端角色复用。
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Awaitable, Callable, cast

import httpx

from services.remote_crypto import (
    CryptoError,
    Fragmenter,
    FrameCodec,
    NoiseHandshake,
    PunchAuth,
    Reassembler,
    SessionCrypto,
    TcpFrameReader,
    decode_msg,
    encode_msg,
)
from services import remote_netutil
from services import remote_wire
from services.remote_signal import SignalClient

logger = logging.getLogger(__name__)

SESSION_IDLE_CLOSE_SEC = 60.0  # 会话空闲关闭（protocol.md §9）
HEARTBEAT_SEC = 30.0
_RELAY_INFLIGHT_MAX = 32  # 中继会话处理并发上限（资源保护线——业务并发由后端决定）
STUN_REFRESH_SEC = 60.0
SIGNAL_DEAD_SEC = 2 * HEARTBEAT_SEC  # 信令活性判死阈值（无任何收包超此值→重建，覆盖换网死连接）
RECONNECT_MIN_SEC = 1.0
RECONNECT_MAX_SEC = 30.0
PUNCH_BURST = 3
PUNCH_INTERVAL_SEC = 0.1


class UdpSession:
    """单个客户端的直连 UDP 会话（帧收发 + 分片重组 + 消息分发）。"""

    def __init__(self, session: SessionCrypto,
                 send_fn: "Callable[[bytes, tuple[str, int]], None]",
                 addr: "tuple[str, int]",
                 dispatcher: "Callable[[remote_wire.WireMsg, UdpSession], Any]") -> None:
        self._session = session
        self._send_fn = send_fn
        self._addr = addr
        self._dispatcher = dispatcher
        self._reasm: "Reassembler | None" = None
        self._fragmenter = Fragmenter()
        self._codec = FrameCodec()
        self.last_active = time.monotonic()

    @property
    def addr(self) -> "tuple[str, int]":
        return self._addr

    async def handle_frame(self, ciphertext: bytes, counter: int) -> None:
        """解密一帧 → 分片累积/完整消息分发。"""
        plaintext = self._session.decrypt(ciphertext, counter)
        msg = remote_wire.decode(plaintext)
        self.last_active = time.monotonic()
        if isinstance(msg, remote_wire.UnknownMsg) and str(msg.raw.get("t")) == "_frag":
            if self._reasm is None:
                self._reasm = Reassembler(msg.raw)
            assembled = self._reasm.feed(msg.raw)
            if assembled is not None:
                self._reasm = None
                await self._dispatch_msg(remote_wire.decode(assembled))
            else:
                nack = self._reasm.due_nack()
                if nack is not None:
                    await self._send_frag_envelope(nack)
        else:
            await self._dispatch_msg(msg)

    async def _dispatch_msg(self, msg: remote_wire.WireMsg) -> None:
        await self._dispatcher(msg, self)

    async def send_msg(self, msg: remote_wire.WireMsg) -> None:
        """发送消息（超 FRAG_LIMIT 自动分片; 每片独立加密为 UDP 帧）。"""
        plaintext = remote_wire.encode(msg)
        if Fragmenter.need_split(plaintext):
            for frag in self._fragmenter.split(plaintext):
                await self._send_frag_envelope(frag)
        else:
            await self._send_plain(plaintext)

    async def _send_frag_envelope(self, frag: "dict[str, object]") -> None:
        """分片信封直发（crypto 层机制信封——不经业务消息对象）。"""
        await self._send_plain(encode_msg(frag))

    async def _send_plain(self, plaintext: bytes) -> None:
        ciphertext, counter = self._session.encrypt(plaintext)
        self._send_fn(self._codec.pack_udp(counter, ciphertext), self._addr)


class GatewayUdpProtocol(asyncio.DatagramProtocol):
    """gateway 固定 UDP socket: STUN 应答 + 打洞包 + 直连会话帧。"""

    def __init__(self, gateway: "RemoteGateway") -> None:
        self._gateway = gateway
        self._codec = FrameCodec()
        self.transport: "asyncio.DatagramTransport | None" = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:  # type: ignore[override]
        self.transport = cast("asyncio.DatagramTransport", transport)

    def datagram_received(self, data: bytes, addr: "tuple[str, int]") -> None:  # type: ignore[override]
        loop = asyncio.get_event_loop()
        if self._gateway._is_relay_addr(addr):
            self._gateway._on_stun_resp(data)
            return
        session = self._gateway._sessions.get(addr)
        if session is not None:
            try:
                counter, ciphertext = self._codec.unpack_udp(data)
            except CryptoError:
                return
            loop.create_task(self._safe_handle(session, ciphertext, counter))
            return
        if data.startswith(b"{"):
            self._gateway._on_punch_packet(data, addr)
            return
        if len(data) == 32:
            self._gateway._on_handshake_msg1(data, addr)
            return
        logger.debug("未知 UDP 包忽略（%dB from %s）", len(data), addr)

    async def _safe_handle(self, session: UdpSession, ciphertext: bytes,
                           counter: int) -> None:
        try:
            await session.handle_frame(ciphertext, counter)
        except Exception:  # noqa: BLE001 —— 会话错误不杀 socket
            logger.exception("UDP 会话处理异常（%s）", session.addr)


class RemoteGateway:
    """gateway 节点: 维持与 relayd 的注册信令（单实例; start/stop 显式控制）。"""

    def __init__(self, psk: bytes, relay_host: str, relay_port: int,
                 node_id: str, backend_port: int = 0) -> None:
        self._psk = psk
        self._codec = FrameCodec()
        self._punch_auth = PunchAuth(psk)
        self._backend_port = backend_port
        self._relay_host = relay_host
        self._relay_port = relay_port
        self._node_id = node_id
        self._task: "asyncio.Task[None] | None" = None
        self._running = False
        self._client: "SignalClient | None" = None
        self._udp: "GatewayUdpProtocol | None" = None
        self._sessions: "dict[tuple[str, int], UdpSession]" = {}
        self._punched: "set[tuple[str, int]]" = set()
        self._stun_fut: "asyncio.Future[tuple[str, int]] | None" = None
        self._join_tasks: "set[asyncio.Task[None]]" = set()
        self._relay_inflight = asyncio.Semaphore(_RELAY_INFLIGHT_MAX)

    def _is_relay_addr(self, addr: "tuple[str, int]") -> bool:
        return addr[0] == self._relay_host and addr[1] == self._relay_port

    @property
    def udp_local_addr(self) -> "tuple[str, int] | None":
        """固定 UDP socket 本地地址（打洞互射与 STUN 共用; 测试/诊断用）。"""
        if self._udp is None or self._udp.transport is None:
            return None
        return cast("tuple[str, int]", self._udp.transport.get_extra_info("sockname"))

    def _lan_ep(self) -> "tuple[str, int] | None":
        """自报 LAN 端点（同 LAN 打洞候选）: 探测 IP + 固定 UDP socket 端口。

        端口取固定 socket——与打洞/STUN 同一映射; 探测或 socket 缺失 → None
        （relayd/client 回退公网映射候选，不劣化）。
        """
        lan = remote_netutil.probe_lan_ip()
        addr = self.udp_local_addr
        if lan is None or addr is None:
            return None
        return (lan, addr[1])

    async def _ensure_udp(self) -> None:
        """建立固定 UDP socket（幂等; local_addr 绑定任意端口）。"""
        if self._udp is not None and self._udp.transport is not None:
            return
        transport, proto = await asyncio.get_running_loop().create_datagram_endpoint(
            lambda: GatewayUdpProtocol(self), local_addr=("0.0.0.0", 0))
        self._udp = cast("GatewayUdpProtocol", proto)
        self._udp.transport = cast("asyncio.DatagramTransport", transport)

    def _udp_send(self, data: bytes, addr: "tuple[str, int]") -> None:
        if self._udp is not None and self._udp.transport is not None:
            self._udp.transport.sendto(data, addr)

    # ── 生命周期 ──────────────────────────────────────

    def start(self) -> None:
        """启动注册循环（幂等; 需在事件循环内调用）。"""
        if self._task is not None and not self._task.done():
            return
        self._running = True
        self._task = asyncio.get_running_loop().create_task(self._register_loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._close_client()
        for task in list(self._join_tasks):  # 断开全部中继会话（节点下线=服务终止）
            task.cancel()
        if self._join_tasks:
            await asyncio.gather(*self._join_tasks, return_exceptions=True)
        self._close_udp()
        self._sessions.clear()
        self._punched.clear()

    def _close_udp(self) -> None:
        """关闭固定 UDP socket（幂等——重建/停止双路径收口）。"""
        if self._udp is not None:
            transport = self._udp.transport
            if transport is not None:
                transport.close()
            self._udp = None

    async def _close_client(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except (ConnectionError, OSError):
                pass
            self._client = None

    # ── 注册主循环 ────────────────────────────────────

    async def _register_loop(self) -> None:
        backoff = RECONNECT_MIN_SEC
        while self._running:
            try:
                await self._ensure_udp()
                client = await SignalClient.connect(
                    self._relay_host, self._relay_port, self._psk)
                from services.remote_wire import SignalRegister
                await client.send(SignalRegister(msg_id=0, node=self._node_id, ver=1,
                                                 lan_ep=self._lan_ep()))
                ack = await client.recv(timeout=10.0)
                if not isinstance(ack, remote_wire.Registered):
                    raise ConnectionError(f"注册应答异常: {ack}")
                self._client = client
                backoff = RECONNECT_MIN_SEC
                logger.info("gateway 已注册（node=%s relay=%s:%s）",
                            self._node_id, self._relay_host, self._relay_port)
                await self._signal_steady(client)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001 —— 重连循环统一面
                logger.warning("信令断开（%.2fs 后重连）: %s", backoff, e)
                await self._close_client()
                self._close_udp()  # 换网场景: 旧 UDP socket 绑定失效——重建绑新网络
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, RECONNECT_MAX_SEC)

    async def _signal_steady(self, client: SignalClient) -> None:
        """注册成功后的信令维持: 心跳 + STUN 刷新 + 服务端下行消息分派。

        活性检测: 超过 SIGNAL_DEAD_SEC 无任何收包 → 判连接死亡抛错重建
        （覆盖换网/网络黑洞——死连接上 send 不报错、recv 永远超时）。
        """
        last_hb = 0.0
        last_stun = 0.0
        last_rx = time.monotonic()
        ep: "tuple[str, int] | None" = None
        while self._running:
            now = time.monotonic()
            if now - last_rx > SIGNAL_DEAD_SEC:
                raise ConnectionError(
                    f"信令静默超时（{SIGNAL_DEAD_SEC:.0f}s 无收包）——重建注册")
            if now - last_hb >= HEARTBEAT_SEC:
                from services.remote_wire import SignalHeartbeat
                await client.send(SignalHeartbeat(msg_id=0))
                last_hb = now
            if self._sessions:
                idle_eps = [a for a, s2 in self._sessions.items()
                            if now - s2.last_active > SESSION_IDLE_CLOSE_SEC]
                for stale_ep in idle_eps:  # 独立变量名——不遮蔽下方 STUN 的 ep（review#11）
                    logger.info("会话空闲超时清理: %s", stale_ep)
                    self._sessions.pop(stale_ep, None)
            if now - last_stun >= STUN_REFRESH_SEC:
                new_ep = await self._stun_probe()
                if new_ep is not None and new_ep != ep:
                    ep = new_ep
                    from services.remote_wire import SignalUpdateEp
                    await client.send(SignalUpdateEp(msg_id=0, ep=(ep[0], ep[1]),
                                                     lan_ep=self._lan_ep()))
                last_stun = now
            try:
                msg = await client.recv(timeout=1.0)
            except asyncio.TimeoutError:
                continue
            last_rx = time.monotonic()  # 任何收包（含 heartbeat_ack）刷新活性
            await self._dispatch(msg, client)

    async def _dispatch(self, msg: "remote_wire.WireMsg",
                        client: SignalClient) -> None:
        """relayd 下行消息分派（isinstance——消息对象已解码）。"""
        from services.remote_wire import HeartbeatAck, PunchHint, RelayPeer
        if isinstance(msg, PunchHint):
            await self._on_punch_hint(msg)
        elif isinstance(msg, RelayPeer):
            join_task = asyncio.get_running_loop().create_task(
                self._relay_join_and_serve(msg.sid))
            self._join_tasks.add(join_task)
            join_task.add_done_callback(self._join_tasks.discard)
        elif isinstance(msg, HeartbeatAck):
            pass
        else:
            logger.debug("未知信令消息忽略: %s", type(msg).__name__)

    # ── 打洞（protocol.md §6）──────────────────────────

    async def _on_punch_hint(self, msg: "remote_wire.PunchHint") -> None:
        """对 client endpoint 互射 punch 包（用固定 UDP socket——映射一致性）。"""
        sid = msg.sid
        target = msg.client
        packet = (json.dumps({"t": "punch", "sid": sid,
                              "mac": self._punch_auth.mac(sid)}) + "\n").encode()
        logger.info("打洞互射开始 → %s:%s（sid=%s, %d 包 × %.0fms）",
                    target[0], target[1], sid, PUNCH_BURST, PUNCH_INTERVAL_SEC * 1000)
        for _ in range(PUNCH_BURST):
            self._udp_send(packet, target)
            await asyncio.sleep(PUNCH_INTERVAL_SEC)
        logger.debug("punch 互射完成 → %s", target)

    def _on_punch_packet(self, data: bytes, addr: "tuple[str, int]") -> None:
        """收到 client 的 punch 包: HMAC 校验 → 标记洞通（允许该 addr 发起握手）。"""
        try:
            obj = cast("dict[str, object]", json.loads(data))
        except ValueError:
            return
        sid = obj.get("sid")
        mac = obj.get("mac")
        if (not isinstance(sid, str) or not isinstance(mac, str)
                or not self._punch_auth.verify(sid, mac)):
            logger.warning("punch 包 MAC 校验失败（忽略）: %s:%s", addr[0], addr[1])
            return
        self._punched.add(addr)
        logger.info("收到合法 punch（洞通旁证）: %s:%s sid=%s", addr[0], addr[1], sid)

    def _on_handshake_msg1(self, data: bytes, addr: "tuple[str, int]") -> None:
        """client 直连 Noise 握手 msg1（仅接受打过洞的地址）。"""
        if addr not in self._punched:
            logger.debug("未打洞地址的握手请求忽略: %s", addr)
            return
        try:
            responder = NoiseHandshake(initiator=False, psk=self._psk)
            responder.read_message(data)
            msg2 = responder.write_message()
            send_k, recv_k = responder.split()
        except (CryptoError, ValueError) as e:
            logger.warning("直连握手失败（%s）: %s", addr, e)
            return
        self._udp_send(msg2, addr)  # 裸 Noise 消息（protocol.md §3.2 判别）
        session = UdpSession(SessionCrypto(send_k, recv_k), self._udp_send, addr,
                             self._session_dispatch)
        self._sessions[addr] = session
        self._punched.discard(addr)
        logger.info("直连会话建立: %s", addr)

    # ── 会话分发 ──────────────────────────────────────

    async def _handle_session_msg(
            self, send: "Callable[[remote_wire.WireMsg], Awaitable[None]]",
            msg: remote_wire.WireMsg) -> None:
        """会话消息语义单点（UDP 每包任务与中继每消息任务共用）。

        新增消息类型只改此处——两条路径自动获得一致语义。
        """
        if isinstance(msg, remote_wire.PingMsg):
            await send(remote_wire.PongMsg(msg_id=msg.msg_id, ts=time.time()))
        elif isinstance(msg, remote_wire.ApiReq):
            await send(await self._forward_api(msg))  # ApiResp 同 id 直传
        else:
            logger.debug("未知会话消息忽略: %s", type(msg).__name__)

    async def _session_dispatch(self, msg: remote_wire.WireMsg,
                                session: UdpSession) -> None:
        """端到端会话消息分发（UDP 直连路径——语义见 _handle_session_msg）。"""
        await self._handle_session_msg(session.send_msg, msg)

    # ── 中继会话（protocol.md §4.2/§4.3）────────────────

    async def _relay_join_and_serve(self, sid: str) -> None:
        """relay_peer → 连 relayd join → 端到端握手（应答方）→ 会话循环。"""
        conn: "SignalClient | None" = None
        try:
            conn = await SignalClient.connect(self._relay_host, self._relay_port,
                                              self._psk)
            await conn.send(remote_wire.RelayJoin(msg_id=0, sid=sid))
            ack = await conn.recv(timeout=10.0)
            if not isinstance(ack, remote_wire.RelayStart):
                raise ConnectionError(
                    f"relay_join 应答异常: {type(ack).__name__}")
            # 管道态: 与 client 的端到端 Noise 握手（client 发起 msg1）
            responder = NoiseHandshake(initiator=False, psk=self._psk)
            # 管道裸字节——循环 feed 直到出帧（与其他握手点同模式，防 TCP 分段）
            e2e_reader = TcpFrameReader()
            frames: list[bytes] = []
            while not frames:
                chunk = await asyncio.wait_for(conn._reader.read(4096), timeout=10.0)  # noqa: SLF001
                if not chunk:
                    raise ConnectionError("端到端握手期间管道断开")
                frames = e2e_reader.feed(chunk)
            responder.read_message(frames[0])
            conn._writer.write(self._codec.pack_tcp(responder.write_message()))  # noqa: SLF001
            await conn._writer.drain()
            send_k, recv_k = responder.split()
            session = SessionCrypto(send_k, recv_k)
            logger.info("中继会话建立（sid=%s）", sid)
            await self._relay_session_loop(conn, session)
        except (ConnectionError, OSError, asyncio.TimeoutError, CryptoError,
                ValueError) as e:
            logger.warning("中继会话失败（sid=%s）: %s", sid, e)
        except asyncio.CancelledError:
            pass  # stop() 主动断开
        finally:
            if conn is not None:
                conn._writer.close()  # noqa: SLF001 —— 断管道（relayd pump 感知 EOF）

    async def _relay_session_loop(self, conn: SignalClient,
                                  session: SessionCrypto) -> None:
        """中继会话读取循环（**只读/解码/派发**——处理在独立任务中并发执行）。

        多路复用: 慢请求（如 TTS）不再阻塞读取循环与后续消息（Ping/新请求）。
        """
        frame_reader = TcpFrameReader()
        tasks: "set[asyncio.Task[None]]" = set()
        try:
            while True:
                chunk = await conn._reader.read(4096)  # noqa: SLF001
                if not chunk:
                    break
                for payload in frame_reader.feed(chunk):
                    msg = remote_wire.decode(session.decrypt_seq(payload))
                    task = asyncio.get_running_loop().create_task(
                        self._serve_relay_msg(conn, session, msg))
                    tasks.add(task)
                    task.add_done_callback(tasks.discard)
        except (ConnectionError, OSError, CryptoError, asyncio.IncompleteReadError):
            pass  # 对端断开——正常终态
        finally:
            for task in list(tasks):
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _serve_relay_msg(self, conn: SignalClient, session: SessionCrypto,
                               msg: remote_wire.WireMsg) -> None:
        """中继单消息处理（读取循环外的独立任务——全类型多路复用）。

        发送并发原子性: encrypt_seq 同步 + 单次 write + drain 并发安全。
        """
        try:
            async with self._relay_inflight:  # 资源保护线（业务并发由后端决定）
                await self._handle_session_msg(
                    lambda m: self._relay_send(conn, session, m), msg)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 —— 单条异常不杀会话（与 UDP 路径 _safe_handle 对称）
            logger.exception("中继会话单消息处理异常（会话继续）")

    async def _relay_send(self, conn: SignalClient, session: SessionCrypto,
                          msg: remote_wire.WireMsg) -> None:
        conn._writer.write(self._codec.pack_tcp(  # noqa: SLF001
            session.encrypt_seq(remote_wire.encode(msg))))
        await conn._writer.drain()

    # ── api.req 本机转发（protocol.md §4.3/D1）───────────

    async def _forward_api(self, msg: remote_wire.ApiReq) -> remote_wire.ApiResp:
        """api.req → 本机 backend HTTP → api.resp（业务零耦合的转发层）。"""
        if not self._backend_port:
            return remote_wire.ApiResp(msg_id=msg.msg_id, status=503,
                                       mime="text/plain", body="backend port 未配置")
        method = msg.method or "GET"
        path = msg.path or "/"
        headers: "dict[str, str]" = {}
        if msg.token:
            headers["Authorization"] = f"Bearer {msg.token}"
        json_body = msg.body
        try:
            # TTS 长请求（自愈+冷启+长文合成可达数分钟）与普通推理共用——
            # 放宽到 600s（普通请求秒级返回不受影响; 30s 会截断节点本地慢请求）
            async with httpx.AsyncClient(timeout=600.0) as http:
                r = await http.request(method, f"http://127.0.0.1:{self._backend_port}{path}",
                                       json=json_body, headers=headers)
        except httpx.HTTPError as e:
            return remote_wire.ApiResp(msg_id=msg.msg_id, status=502,
                                       mime="text/plain",
                                       body=f"backend 转发失败: {e}")
        resp: httpx.Response = r
        mime_raw = resp.headers.get("content-type")  # pyright: ignore[reportAny] —— httpx Headers.get 存根泛型返回 Any
        mime = mime_raw if isinstance(mime_raw, str) else "application/json"
        status = int(resp.status_code)
        content = bytes(resp.content)
        if "json" in mime:
            return remote_wire.ApiResp(
                msg_id=msg.msg_id, status=status, mime=mime,
                body=cast("dict[str, object] | list[object]", r.json()))
        return remote_wire.ApiResp(msg_id=msg.msg_id, status=status,
                                   mime=mime, body=content)

    # ── STUN ─────────────────────────────────────────

    def _on_stun_resp(self, data: bytes) -> None:
        """固定 socket 收到的 STUN 应答（唤醒探测 future）。"""
        fut = self._stun_fut
        if fut is None or fut.done():
            return
        try:
            obj = cast("dict[str, object]", json.loads(data))
        except ValueError:
            return
        src = obj.get("src")
        items = cast("list[object] | None", src if isinstance(src, list) else None)
        if (items is not None and len(items) == 2 and isinstance(items[0], str)
                and isinstance(items[1], int) and not isinstance(items[1], bool)):
            fut.set_result((items[0], items[1]))

    async def _stun_probe(self) -> "tuple[str, int] | None":
        """经固定 UDP socket 探测自身公网映射（与打洞同 socket——映射一致）。"""
        await self._ensure_udp()
        loop = asyncio.get_running_loop()
        self._stun_fut = loop.create_future()
        assert self._udp is not None and self._udp.transport is not None
        self._udp.transport.sendto(b'{"t":"stun"}\n',
                                   (self._relay_host, self._relay_port))
        try:
            return await asyncio.wait_for(self._stun_fut, timeout=3.0)
        except (OSError, asyncio.TimeoutError) as e:
            logger.warning("STUN 探测失败: %r", e)
            return None
        finally:
            self._stun_fut = None
