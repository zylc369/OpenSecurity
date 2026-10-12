"""remote transport（主控角色——控制台 backend 侧，protocol.md §7 路径状态机）。

分段交付:
- P11: 直连路径——信令 lookup、客户端打洞（Puncher）、UDP 会话（UdpClientSession）
- P12: 中继 fallback、会话管理、后台 loop 线程 + 同步 request() facade

线程模型: start() 起后台 asyncio loop 线程; request()/probe() 跨线程提交
（remote_client 的调用点在 worker 线程——remote_link 体系语义不变）。
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, cast

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
from services.remote_signal import SignalClient
from services import remote_wire

logger = logging.getLogger(__name__)


class TransportError(RuntimeError):
    """transport 层统一失败面（remote_client 映射为 RemoteUnavailable）。"""


class UdpClientSession:
    """客户端侧直连 UDP 会话（与 gateway UdpSession 协议对称）。"""

    def __init__(self, session: SessionCrypto,
                 send_fn: "Callable[[bytes, tuple[str, int]], None]",
                 peer: "tuple[str, int]",
                 msg_handler: "Callable[[remote_wire.WireMsg], Any]") -> None:
        self._session = session
        self._send_fn = send_fn
        self._peer = peer
        self._handler = msg_handler
        self._reasm: "Reassembler | None" = None
        self._fragmenter = Fragmenter()
        self._codec = FrameCodec()

    async def handle_datagram(self, data: bytes) -> None:
        try:
            counter, ciphertext = self._codec.unpack_udp(data)
            plaintext = self._session.decrypt(ciphertext, counter)
        except CryptoError as e:
            # 安全可见性: 解密失败的 UDP 包（伪造/损坏/重放）——debug 级
            # （攻击场景可能高频，避免刷屏但排查可见）
            logger.debug("UDP 包解密失败（丢弃）: %s", e)
            return
        msg = remote_wire.decode(plaintext)
        if isinstance(msg, remote_wire.UnknownMsg) and str(msg.raw.get("t")) == "_frag":
            if self._reasm is None:
                self._reasm = Reassembler(msg.raw)
            assembled = self._reasm.feed(msg.raw)
            if assembled is not None:
                self._reasm = None
                await self._handler(remote_wire.decode(assembled))
            else:
                nack = self._reasm.due_nack()
                if nack is not None:
                    await self._send_frag_envelope(nack)
            return
        await self._handler(msg)

    async def send_msg(self, msg: remote_wire.WireMsg) -> None:
        """业务消息发送（wire.encode 单点; 超限自动分片）。"""
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
        self._send_fn(self._codec.pack_udp(counter, ciphertext), self._peer)


class _ClientUdpProtocol(asyncio.DatagramProtocol):
    """客户端固定 UDP socket: punch 回包 + 握手 msg2 + 会话帧统一入 inbox。"""

    def __init__(self) -> None:
        self.transport: "asyncio.DatagramTransport | None" = None
        self.inbox: "asyncio.Queue[tuple[bytes, tuple[str, int]]]" = asyncio.Queue()

    def connection_made(self, transport: asyncio.BaseTransport) -> None:  # type: ignore[override]
        import typing
        self.transport = typing.cast("asyncio.DatagramTransport", transport)

    def datagram_received(self, data: bytes, addr: "tuple[str, int]") -> None:  # type: ignore[override]
        self.inbox.put_nowait((data, addr))

    def local_addr(self) -> "tuple[str, int]":
        import typing
        assert self.transport is not None
        return typing.cast("tuple[str, int]", self.transport.get_extra_info("sockname"))


class DirectConnector:
    """直连建立器: lookup → 打洞互射 → Noise 握手（protocol.md §6 客户端侧）。"""

    def __init__(self, psk: bytes, relay_host: str, relay_port: int,
                 punch_timeout: float = 5.0, punch_burst: int = 3) -> None:
        self._psk = psk
        self._codec = FrameCodec()
        self._punch_auth = PunchAuth(psk)
        self._relay_host = relay_host
        self._relay_port = relay_port
        self._punch_timeout = punch_timeout
        self._punch_burst = punch_burst

    async def connect(self, node_id: str,
                      msg_handler: "Callable[[remote_wire.WireMsg], Any]"
                      ) -> "tuple[UdpClientSession, _ClientUdpProtocol]":
        """完整直连建立流程; 失败抛 TransportError（调用方 fallback 中继）。"""
        loop = asyncio.get_running_loop()
        transport, proto = await loop.create_datagram_endpoint(
            _ClientUdpProtocol, local_addr=("0.0.0.0", 0))
        try:
            # ① 信令 lookup（携带自身 UDP 映射——回环/锥形 NAT 下即本地址）
            local = proto.local_addr()
            sig = await SignalClient.connect(self._relay_host, self._relay_port,
                                             self._psk)
            try:
                await sig.send(remote_wire.LookupMsg(
                    msg_id=0, node=node_id, udp_ep=local))
                resp = await sig.recv(timeout=5.0)
            finally:
                await sig.close()
            if not isinstance(resp, remote_wire.LookupResp):
                raise TransportError(f"lookup 应答异常: {type(resp).__name__}")
            if not resp.ok:
                raise TransportError(f"节点不可达: {resp.error}")
            if not (resp.gw[0] and resp.gw[1] > 0 and resp.sid):
                raise TransportError("endpoints 响应畸形")
            gw_ep = resp.gw
            sid = resp.sid

            # ② 打洞互射 + Noise 握手（并行等待 msg2）
            punch_pkt = (json.dumps({"t": "punch", "sid": sid,
                                     "mac": self._punch_auth.mac(sid)}) + "\n").encode()
            initiator = NoiseHandshake(initiator=True, psk=self._psk)
            msg1 = initiator.write_message()
            assert proto.transport is not None
            for _ in range(self._punch_burst):
                proto.transport.sendto(punch_pkt, gw_ep)
            proto.transport.sendto(msg1, gw_ep)
            deadline = time.monotonic() + self._punch_timeout
            got_msg2 = False
            while time.monotonic() < deadline:
                try:
                    data, _ = await asyncio.wait_for(
                        proto.inbox.get(), timeout=max(0.05, deadline - time.monotonic()))
                except asyncio.TimeoutError:
                    break
                if data.startswith(b"{"):
                    continue  # gateway 的 punch 回包（洞通旁证）
                if len(data) == 48:
                    initiator.read_message(data)
                    got_msg2 = True
                    break
            if not got_msg2:
                raise TransportError(f"打洞超时（{self._punch_timeout}s）")
            i_send, i_recv = initiator.split()
            session = UdpClientSession(SessionCrypto(i_send, i_recv),
                                       lambda d, a: proto.transport.sendto(d, a)  # type: ignore[union-attr]
                                       if proto.transport else None, gw_ep, msg_handler)
            # 排空互射期间的残留 punch 包（避免喂给会话分发循环）
            DirectConnection._drain_inbox(proto.inbox)
            return session, proto  # 调用方包装为 DirectConnection 并 start_pump
        except (OSError, CryptoError, ConnectionError, TransportError) as e:
            transport.close()  # TransportError（打洞超时/节点离线）也须回收——常规路径必经
            if isinstance(e, TransportError):
                raise
            raise TransportError(f"直连建立失败: {e}") from e





class DirectConnection:
    """已建立的直连（会话 + UDP socket + 入站分发泵; aclose 收口生命周期）。"""

    def __init__(self, session: UdpClientSession,
                 proto: _ClientUdpProtocol) -> None:
        self._session = session
        self._proto = proto
        self._pump: "asyncio.Task[None] | None" = None

    @staticmethod
    def _drain_inbox(inbox: "asyncio.Queue[tuple[bytes, tuple[str, int]]]") -> None:
        """排空残留 punch 包（互射期遗留——避免污染会话分发）。"""
        while not inbox.empty():
            try:
                inbox.get_nowait()
            except asyncio.QueueEmpty:
                break

    def start_pump(self) -> None:
        """启动入站分发（inbox → session.handle_datagram）。"""
        if self._pump is None or self._pump.done():
            self._pump = asyncio.get_running_loop().create_task(self._pump_loop())

    async def _pump_loop(self) -> None:
        inbox = self._proto.inbox
        while True:
            data, _addr = await inbox.get()
            if data is None:  # close 哨兵
                break
            try:
                await self._session.handle_datagram(data)
            except Exception:  # noqa: BLE001 —— 单帧畸形不杀泵（review#13——与 gateway _safe_handle 对称）
                logger.exception("直连泵单帧处理异常（会话继续）")

    @property
    def session(self) -> UdpClientSession:
        return self._session

    async def send_msg(self, msg: remote_wire.WireMsg) -> None:
        await self._session.send_msg(msg)

    @property
    def broken(self) -> bool:
        return self._pump is not None and self._pump.done()

    async def aclose(self) -> None:
        if self._pump is not None:
            self._pump.cancel()
            try:
                await self._pump
            except asyncio.CancelledError:
                pass
            self._pump = None
        if self._proto.transport is not None:
            self._proto.transport.close()


class RelayConnection:
    """中继路径连接（protocol.md §4.2 客户端侧全流程 + 端到端会话泵）。"""

    def __init__(self, sig: SignalClient, data: SignalClient,
                 session: SessionCrypto,
                 msg_handler: "Callable[[remote_wire.WireMsg], Any]") -> None:
        self._codec = FrameCodec()
        self._sig = sig
        self._data = data
        self._session = session
        self._handler = msg_handler
        self._pump: "asyncio.Task[None] | None" = None
        self._frames = TcpFrameReader()

    @classmethod
    async def establish(cls, psk: bytes, relay_host: str, relay_port: int,
                        node_id: str,
                        msg_handler: "Callable[[remote_wire.WireMsg], Any]"
                        ) -> "RelayConnection":
        # ① lookup + relay_open（同一信令短连接）
        sig = await SignalClient.connect(relay_host, relay_port, psk)
        try:
            await sig.send(remote_wire.LookupMsg(
                msg_id=0, node=node_id))  # udp_ep 省略——relayd 回退 TCP 对端
            resp = await sig.recv(timeout=5.0)
            if not isinstance(resp, remote_wire.LookupResp):
                raise TransportError(
                    f"lookup 应答异常: {type(resp).__name__}")
            sid = resp.sid
            if not resp.ok or not sid:
                raise TransportError(f"节点不可达: {resp.error or '(无详情)'}")
            await sig.send(remote_wire.RelayOpen(msg_id=0, node=node_id, sid=sid))
            ready = await sig.recv(timeout=5.0)
            if not isinstance(ready, remote_wire.RelayReady):
                raise TransportError(f"relay_open 失败: {type(ready).__name__}")
        except (ConnectionError, OSError, asyncio.TimeoutError) as e:
            await sig.close()
            raise TransportError(f"中继信令失败: {e}") from e
        # ② 数据连接 attach → relay_start
        data = await SignalClient.connect(relay_host, relay_port, psk)
        try:
            await data.send(remote_wire.RelayAttach(msg_id=0, sid=sid))
            ack = await data.recv(timeout=10.0)
            if not isinstance(ack, remote_wire.RelayStart):
                raise TransportError(
                    f"relay_attach 失败: {type(ack).__name__}")
            # ③ 端到端握手（initiator）
            initiator = NoiseHandshake(initiator=True, psk=psk)
            data._writer.write(FrameCodec().pack_tcp(initiator.write_message()))  # noqa: SLF001
            await data._writer.drain()  # noqa: SLF001
            frames = data._frames.feed(b"")  # noqa: SLF001
            reader = data._reader  # noqa: SLF001
            while not frames:
                chunk = await asyncio.wait_for(reader.read(4096), timeout=5.0)
                if not chunk:
                    raise ConnectionError("端到端握手期间管道断开")
                frames = data._frames.feed(chunk)  # noqa: SLF001
            initiator.read_message(frames[0])
            i_send, i_recv = initiator.split()
            session = SessionCrypto(i_send, i_recv)
        except (ConnectionError, OSError, asyncio.TimeoutError, CryptoError,
                ValueError) as e:
            await data.close()
            await sig.close()
            raise TransportError(f"中继建立失败: {e}") from e
        return cls(sig, data, session, msg_handler)

    def start_pump(self) -> None:
        if self._pump is None or self._pump.done():
            self._pump = asyncio.get_running_loop().create_task(self._pump_loop())

    async def _pump_loop(self) -> None:
        reader = self._data._reader  # noqa: SLF001
        try:
            while True:
                chunk = await reader.read(4096)
                if not chunk:
                    break
                for payload in self._frames.feed(chunk):
                    await self._handler(
                        remote_wire.decode(self._session.decrypt_seq(payload)))
        except (ConnectionError, OSError, CryptoError, asyncio.IncompleteReadError) as e:
            # 对端断开——会话失效（上层下次重建）; 断开原因留痕（排查打洞/中继稳定性）
            logger.debug("会话读取失败（对端断开，待重建）: %s", e)

    async def send_msg(self, msg: remote_wire.WireMsg) -> None:
        self._data._writer.write(self._codec.pack_tcp(  # noqa: SLF001
            self._session.encrypt_seq(remote_wire.encode(msg))))
        await self._data._writer.drain()  # noqa: SLF001

    @property
    def broken(self) -> bool:
        return self._pump is not None and self._pump.done()

    async def aclose(self) -> None:
        if self._pump is not None:
            self._pump.cancel()
            try:
                await self._pump
            except asyncio.CancelledError:
                pass
            self._pump = None
        await self._data.close()
        await self._sig.close()


@dataclass(frozen=True)
class TransportJob:
    """transport 任务基类（worker 线程 → loop 线程的强类型载荷——tuple[object] 禁令）。"""


@dataclass(frozen=True)
class ApiJob(TransportJob):
    method: str
    path: str
    body: "dict[str, object] | None"
    token: str
    timeout_sec: float = 0.0  # >0 覆盖配置默认（大文件分片慢链路放宽）


@dataclass(frozen=True)
class PingJob(TransportJob):
    pass


@dataclass
class TransportConfig:
    """transport 配置（P2PSettings 的 client 侧投影; protocol.md §9 默认值）。"""

    relay_host: str
    relay_port: int
    psk: bytes
    node_id: str
    # review#3(dict 禁令): remote_client/remote_link 间传强类型对象，不再传 dict
    punch_timeout_sec: float = 5.0
    relay_timeout_sec: float = 5.0
    api_timeout_sec: float = 30.0
    idle_close_sec: float = 60.0


class RemoteTransport:
    """同步 facade: 后台 asyncio loop 线程 + request()/probe() 跨线程提交。

    路径状态机（protocol.md §7）: 无会话 → 直连尝试（超时 punch_timeout）
    → 失败落中继 → 全失败 TransportError（remote_link 现有降级链路接管）。
    """

    def __init__(self, cfg: TransportConfig) -> None:
        self._cfg = cfg
        self._codec = FrameCodec()
        self._loop: "asyncio.AbstractEventLoop | None" = None
        self._thread: "threading.Thread | None" = None
        self._conn: "DirectConnection | RelayConnection | None" = None
        self._session_lock = asyncio.Lock()  # review#3: 并发 job 重复建立→连接泄漏
        self._pending: "dict[int, asyncio.Future[remote_wire.WireMsg]]" = {}
        self._next_id = 1
        self._last_active = 0.0

    # ── 生命周期 ──────────────────────────────────────

    def start(self) -> None:
        if self._loop is not None:
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True,
                                        name="remote-transport")
        self._thread.start()

    def _run_loop(self) -> None:
        assert self._loop is not None
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def aclose(self) -> None:
        if self._conn is not None:
            await self._conn.aclose()
            self._conn = None

    def stop(self) -> None:
        if self._loop is not None:
            # 先取消全部在途请求（future 置异常 → _handle_job 立即失败返回，
            # 而非挂死到 api_timeout+15 兜底——任何 close 场景的等待方立即感知）
            def _fail_pending() -> None:
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(TransportError("transport 已停止"))
                self._pending.clear()
            try:
                self._loop.call_soon_threadsafe(_fail_pending)
            except RuntimeError as e:
                # loop 已关闭（异常退出/重复关闭）——在途取消不可达，
                # 记录以可排查（等待方将由 api_timeout+15 兜底超时）
                logger.warning("transport.stop 取消在途请求失败（loop 已关闭）: %s", e)
            try:
                self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError as e:
                logger.warning("transport.stop 停止 loop 失败（已关闭）: %s", e)
            if self._thread is not None:
                self._thread.join(timeout=5.0)
            self._loop.close()
            self._loop = None
            self._thread = None

    # ── 同步 API（worker 线程调用）────────────────────

    def request(self, method: str, path: str,
                body: "dict[str, object] | None" = None,
                token: str = "",
                timeout: float | None = None) -> "remote_wire.ApiResp":
        """api.req → ApiResp（强类型）; 失败抛 TransportError。

        timeout: 本请求级超时（None=配置默认——大文件分片等慢链路场景显式放宽）。"""
        job = ApiJob(method=method, path=path, body=body, token=token)
        if timeout is not None:  # frozen dataclass → replace 重建（不可变语义）
            import dataclasses as _dc
            job = _dc.replace(job, timeout_sec=timeout)
        got = self._submit(job)
        if not isinstance(got, remote_wire.ApiResp):
            raise TransportError(
                f"api 请求收到非响应消息: {type(got).__name__}")
        return got

    def probe(self) -> bool:
        """ping/pong 健康探测（remote_link 心跳语义复用）。"""
        try:
            self._submit(PingJob())
            return True
        except TransportError:
            return False

    def _submit(self, job: TransportJob) -> "remote_wire.WireMsg":
        if self._loop is None:
            raise TransportError("transport 未启动")
        # ApiJob 可带请求级超时（大文件分片慢链路放宽; 其余用配置默认）
        req_timeout = (job.timeout_sec if isinstance(job, ApiJob) and job.timeout_sec > 0
                       else self._cfg.api_timeout_sec)
        async_task = asyncio.run_coroutine_threadsafe(
            self._handle_job(job), self._loop)
        try:
            return async_task.result(
                timeout=req_timeout + 15.0)
        except concurrent.futures.TimeoutError as e:
            async_task.cancel()
            raise TransportError("请求超时（transport 线程）") from e
        except TransportError:
            raise

    # ── loop 内实现 ───────────────────────────────────

    async def _handle_job(self, job: TransportJob) -> "remote_wire.WireMsg":
        conn = await self._ensure_session()
        self._last_active = time.monotonic()
        msg_id = self._next_id
        self._next_id += 1
        from services.remote_wire import ApiReq, ApiResp, PingMsg, WireMsg
        fut: "asyncio.Future[WireMsg]" = \
            asyncio.get_running_loop().create_future()
        self._pending[msg_id] = fut
        try:
            if isinstance(job, ApiJob):
                await conn.send_msg(ApiReq(msg_id=msg_id, method=job.method,
                                           path=job.path, body=job.body,
                                           token=job.token or None))
                logger.debug("api.req %s %s（id=%s 路径=%s）", job.method, job.path, msg_id,
                             "直连" if isinstance(conn, DirectConnection) else "中继")
            else:  # PingJob
                await conn.send_msg(PingMsg(msg_id=msg_id))
            # 返回 WireMsg（ApiResp 或 PongMsg）; api 窄化在 request()——
            # probe 的 pong 在此通过（此前误置于此导致 probe 恒失败）
            return await asyncio.wait_for(
                fut,
                timeout=(job.timeout_sec if isinstance(job, ApiJob) and job.timeout_sec > 0
                         else self._cfg.api_timeout_sec))
        except (ConnectionError, OSError, asyncio.TimeoutError, CryptoError,
                ValueError) as e:
            await self._drop_session()
            raise TransportError(f"请求失败: {e}") from e
        finally:
            self._pending.pop(msg_id, None)

    async def _ensure_session(self) -> "DirectConnection | RelayConnection":
        """会话复用/重建（直连优先、中继兜底; Lock 串行化——并发 job 不重复建立）。"""
        if self._conn is not None and not self._conn.broken:
            return self._conn
        async with self._session_lock:
            if self._conn is not None and not self._conn.broken:
                return self._conn  # 等锁期间他人已建好
            await self._drop_session()
            handler = self._on_msg
        # ① 直连
        try:
            connector = DirectConnector(
                self._cfg.psk, self._cfg.relay_host, self._cfg.relay_port,
                punch_timeout=self._cfg.punch_timeout_sec)
            session, proto = await connector.connect(self._cfg.node_id, handler)
            conn = DirectConnection(session, proto)
            conn.start_pump()
            self._conn = conn
            logger.info("transport 会话建立: 直连")
            return conn
        except TransportError as e:
            logger.info("直连失败（落中继）: %s", e)
        # ② 中继
        conn = await RelayConnection.establish(
            self._cfg.psk, self._cfg.relay_host, self._cfg.relay_port,
            self._cfg.node_id, handler)
        conn.start_pump()
        self._conn = conn
        logger.info("transport 会话建立: 中继")
        return conn

    async def _drop_session(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.aclose()
            except (ConnectionError, OSError) as e:
                logger.debug("会话 close 异常（忽略）: %s", e)
            self._conn = None

    async def _on_msg(self, msg: "object") -> None:
        """会话入站分发: ApiResp/PongMsg → future（同池，msg_id 对应）; 其他忽略。"""
        from services.remote_wire import ApiResp, PongMsg, WireMsg
        if isinstance(msg, (ApiResp, PongMsg)):
            fut = self._pending.get(msg.msg_id)
            if fut is not None and not fut.done():
                fut.set_result(cast("WireMsg", msg))
                return
        logger.debug("transport 未匹配消息: %s", type(msg).__name__)
